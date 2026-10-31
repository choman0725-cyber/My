"""正式版做多 ＋ 正式版放空（SHORT_RULES.md）合併：放空只用多頭的閒置現金，看合併後的績效。

多頭：FINAL_RULES.md 正式版（max(中位數,5%)／12%／4.75%），決策不受放空影響。
放空：SHORT_RULES.md 進取版（殖利率 <2%＋大盤空頭排列＋乖離 −10%～+1%＋鏡像技術放空點；跌 5% 回補、
      大盤轉多且賺 2% 連兩日回補；距最後回補日 <30 天不空；不停損；斷頭 46%；平盤下禁空；成本同 short_strategy.py）。
      訊號、制度、成本全部直接用 short_strategy.py 的函式與常數，只改「錢從哪裡來」：
  separate：SHORT_RULES 原設定，另一個 500 萬帳戶獨立記帳（對照，應與 short_strategy.py 逐筆一致）
  idle    ：同一個帳戶。每筆名目＝前一日多頭總資產 × size；融券保證金 90% 只能用
            「多頭現金 ＋ 放空累計損益 − 預留（總資產 × reserve）」，不夠就縮小名目（低於原名目 25% 就放棄）；
            多頭買股後現金不夠維持保證金 → 同一天開盤先回補放空（多頭優先）
合併資產 ＝ 多頭資產 ＋ 放空已實現 ＋ 放空未實現（含借券費）。
用法：python short_combo_study.py
"""
import pickle

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
import short_strategy as ss
from backtest import BUY_COST, RESULTS, ROOT, SELL_COST
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
import short_idle_study as si
from short_idle_study import long_path, nav_mdd, IS_END

MARGIN = 0.90
G = rs.G
S = {}


def setup():
    po.setup(); po.apply(dr.FINAL)
    dates = G["dates"]
    data, _ = pickle.loads((RESULTS / "portfolio_prepared.pkl").read_bytes())
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype=str)
    member = ps.membership(cons, dates)
    names = cons.drop_duplicates("stock_id").set_index("stock_id")["name"]
    res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv", dtype={"stock_id": str}, parse_dates=["date"])
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    bear, bias_ok, _ = ss.market_state(tai)
    bear = bear.reindex(dates).fillna(False).to_numpy(bool); bias_ok = bias_ok.reindex(dates).fillna(False).to_numpy(bool)
    A = {}
    for sid, d in data.items():
        if sid not in member:
            continue
        px = d["df"].dropna(subset=["open", "close"])
        px = px[px.index >= pd.Timestamp("2015-01-01")]
        if len(px) < 300 or px.index[-1] < ss.START + pd.Timedelta(days=ss.WARMUP_DAYS):
            continue
        ex = res_all.loc[(res_all["stock_id"] == sid) & res_all["stock_or_cache_dividend"].astype(str).str.contains("息|權"), "date"]
        force, block, gap = ss.ex_dividend_schedule(px.index, ex.tolist())
        sig = ss.short_signal(px)
        df = px.reindex(dates)
        y = d["yield"]
        A[sid] = {
            "name": names.get(sid, ""),
            "open": df["open"].to_numpy(), "close": df["close"].to_numpy(), "close_ff": df["close"].ffill().to_numpy(),
            "chg": df["close"].pct_change().to_numpy(), "yield": y,
            "entry": (sig.reindex(dates).fillna(False).to_numpy(bool) & member[sid].to_numpy(bool)
                      & (np.nan_to_num(y, nan=np.inf) < ss.MAX_YIELD) & bear & bias_ok
                      & ~(np.nan_to_num(gap.reindex(dates).to_numpy(), nan=np.inf) < ss.MIN_DAYS_TO_FORCE)),
            "force": force.reindex(dates).fillna(False).to_numpy(bool), "block": block.reindex(dates).fillna(False).to_numpy(bool),
            "start_n": dates.searchsorted(max(ss.START, px.index[0] + pd.Timedelta(days=ss.WARMUP_DAYS))),
            "delist_n": d["last_n"],
        }
    S.update(dates=dates, A=A, bear=bear)
    si.S.update(dates=dates, N=len(dates))


def simulate(L, mode="idle", size=0.20, reserve=0.10, shrink=True, min_frac=0.25, max_short=ss.SLOTS):
    """mode separate：放空帳戶自有資金 1.0（=CAPITAL），名目＝權益/5，與 short_strategy.py 相同。
    mode idle：名目＝前一日多頭總資產 × size，受多頭閒置現金限制。回傳 (逐筆, 合併資產曲線, 放空損益曲線)。"""
    dates, A, bear = S["dates"], S["A"], S["bear"]
    N = len(dates); s_n = L["s_n"]
    eq_long, cash_long, held_long = L["eq"], L["cash"], L["held"]
    pos, trades = {}, []
    realized, locked = 0.0, 0.0
    comb = np.full(N, np.nan); short_curve = np.full(N, np.nan)
    comb[s_n] = eq_long[s_n]; short_curve[s_n] = 0.0
    sep_eq = 1.0

    def pnl(p, px, n):
        days = (dates[n] - dates[p["n0"]]).days
        return p["N"] * (p["p0"] * (1 - SELL_COST - ss.SHORT_FEE) - px * (1 + BUY_COST)) - p["N"] * p["p0"] * ss.BORROW_RATE * days / 365

    def cover(sid, n, px, reason):
        nonlocal realized, locked, sep_eq
        p = pos.pop(sid)
        g = pnl(p, px, n)
        realized += g; sep_eq += g; locked -= p["margin"]
        trades.append(dict(代號=sid, 名稱=A[sid]["name"], 進場=dates[p["n0"]], 放空價=p["p0"], 出場=dates[n], 回補價=px,
                           天數=(dates[n] - dates[p["n0"]]).days, 名目=p["notional"], 報酬率=g / p["notional"], 損益=g, 原因=reason,
                           名目占原規則=p["frac"]))

    mtm_prev = 0.0
    for n in range(s_n + 1, N):
        p_ = n - 1
        # 1. 前一天收盤決定的回補
        for sid in list(pos):
            p = pos[sid]
            if p["exit"] is None:
                continue
            a = A[sid]
            px = a["open"][n] if not np.isnan(a["open"][n]) else a["close_ff"][p_]
            cover(sid, n, px, p["exit"])
        assets_p = eq_long[p_] + realized + mtm_prev
        # 2. 多頭優先：多頭今天買股後現金不夠維持保證金 → 先回補（浮虧最大的先）
        if mode == "idle":
            while pos and cash_long[n] + realized + mtm_prev < locked:
                worst = min(pos, key=lambda q: 1 - A[q]["close_ff"][p_] / pos[q]["p0"])
                a = A[worst]
                cover(worst, n, a["open"][n] if not np.isnan(a["open"][n]) else a["close_ff"][p_], "多頭要用錢")
        # 3. 新放空
        cands = []
        for sid, a in A.items():
            if sid in pos or n < a["start_n"] or n >= a["delist_n"] or not a["entry"][p_] or a["block"][n]:
                continue
            if np.isnan(a["open"][n]) or (a["chg"][p_] <= ss.UPTICK_DROP and a["open"][n] < a["close"][p_]):
                continue
            if mode == "idle" and sid in held_long[n]:
                continue
            cands.append((a["yield"][p_], sid))
        free = min(max_short, ss.SLOTS) - len(pos)
        avail = cash_long[n] + realized + mtm_prev - reserve * assets_p - locked
        for _, sid in sorted(cands)[:max(0, free)]:
            a = A[sid]
            if mode == "separate":
                notional, margin, frac = sep_eq / ss.SLOTS, 0.0, 1.0
            else:
                full = assets_p * size
                notional = full
                if MARGIN * notional > avail:
                    if not shrink:
                        continue
                    notional = max(avail, 0.0) / MARGIN
                if notional < min_frac * full:
                    continue
                margin, frac = MARGIN * notional, notional / full
                locked += margin; avail -= margin
            pos[sid] = {"n0": n, "p0": a["open"][n], "N": notional / a["open"][n], "notional": notional, "margin": margin,
                        "exit": None, "streak": 0, "frac": frac}
        # 4. 收盤評價、決定明天回補
        mtm = 0.0
        for sid, p in pos.items():
            a = A[sid]
            c = a["close_ff"][n]
            mtm += pnl(p, c, n)
            gain = 1 - c / p["p0"]
            p["streak"] = p["streak"] + 1 if (not bear[n] and gain >= ss.FLIP_GAIN) else 0
            reason = None
            if p["streak"] >= ss.FLIP_CONFIRM:
                reason = "轉多有賺"
            if gain >= ss.TARGET:
                reason = "獲利5%"
            if -gain >= ss.MARGIN_CALL:
                reason = "斷頭"
            if a["force"][n]:
                reason = "強制回補"
            if n + 1 >= a["delist_n"]:
                reason = "下市"
            p["exit"] = reason
        mtm_prev = mtm
        short_curve[n] = realized + mtm
        comb[n] = eq_long[n] + realized + mtm
    for sid, p in pos.items():
        a = A[sid]; c = a["close_ff"][N - 1]; g = pnl(p, c, N - 1)
        trades.append(dict(代號=sid, 名稱=a["name"], 進場=dates[p["n0"]], 放空價=p["p0"], 出場=None, 回補價=c, 天數=(dates[N - 1] - dates[p["n0"]]).days,
                           名目=p["notional"], 報酬率=g / p["notional"], 損益=g, 原因="持有中", 名目占原規則=p["frac"]))
    T = pd.DataFrame(trades)
    return T, pd.Series(comb[s_n:], index=dates[s_n:]), pd.Series(short_curve[s_n:], index=dates[s_n:])


def metrics(L, T, comb):
    dates = S["dates"]
    e_is = dates.get_indexer([IS_END], method="ffill")[0]
    long_eq = pd.Series(L["eq"][L["s_n"]:], index=comb.index)
    def seg(eq, end_n):
        flows = [c for c, d in zip(L["flows"], L["flow_dates"]) if d <= dates[end_n]]
        fd = [d for d in L["flow_dates"] if d <= dates[end_n]]
        return irr(flows, fd, eq.iloc[end_n - L["s_n"]] * CAPITAL, dates[end_n])
    closed = T[T["出場"].notna()] if len(T) else T
    yr = T.assign(年=pd.to_datetime(T["出場"].fillna(dates[-1])).dt.year).groupby("年")["損益"].sum() * CAPITAL / 1e4 if len(T) else pd.Series(dtype=float)
    return {"放空筆數": len(T), "勝率%": 100 * (closed["損益"] > 0).mean() if len(closed) else np.nan,
            "每筆平均%": 100 * closed["報酬率"].mean() if len(closed) else np.nan,
            "平均名目占原規則%": 100 * T["名目占原規則"].mean() if len(T) else np.nan,
            "放空總損益萬": T["損益"].sum() * CAPITAL / 1e4 if len(T) else 0.0,
            "前7年放空損益萬": yr[yr.index <= 2023].sum() if len(yr) else 0.0, "後3年放空損益萬": yr[yr.index >= 2024].sum() if len(yr) else 0.0,
            "多頭要用錢筆數": int((T["原因"] == "多頭要用錢").sum()) if len(T) else 0,
            "強制回補": int((T["原因"] == "強制回補").sum()) if len(T) else 0, "斷頭": int((T["原因"] == "斷頭").sum()) if len(T) else 0,
            "期末萬": comb.iloc[-1] * CAPITAL / 1e4, "純多期末萬": long_eq.iloc[-1] * CAPITAL / 1e4,
            "IRR": seg(comb, len(dates) - 1), "純多IRR": seg(long_eq, len(dates) - 1),
            "前7年IRR": seg(comb, e_is), "純多前7年IRR": seg(long_eq, e_is),
            "回撤": nav_mdd(comb, L["contrib"], dates), "純多回撤": nav_mdd(long_eq, L["contrib"], dates), "_yr": yr}


def main():
    setup()
    L = long_path()
    dates = S["dates"]
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True); pd.set_option("display.max_rows", 500)

    # 0. 對照：SHORT_RULES 原設定（獨立 500 萬帳戶）
    T0, _, sc0 = simulate(L, "separate")
    sep_eq = 1.0 + sc0
    years = (dates[-1] - dates[L["s_n"]]).days / 365.25
    print(f"【對照：SHORT_RULES 進取版，獨立 500 萬帳戶】{len(T0)} 筆，勝率 {100 * (T0['損益'] > 0).mean():.0f}%，每筆 {100 * T0['報酬率'].mean():+.1f}%，"
          f"期末 {sep_eq.iloc[-1] * CAPITAL / 1e4:,.0f} 萬，IRR {100 * (sep_eq.iloc[-1] ** (1 / years) - 1):.1f}%，回撤 {100 * (sep_eq / sep_eq.cummax() - 1).min():.1f}%")
    T0.to_csv(RESULTS / "short_combo_separate_trades.csv", index=False, encoding="utf-8-sig")

    # 1. 原規則的每一筆進場時，多頭帳戶有多少閒錢
    cash_pct = pd.Series(L["cash"] / L["eq"], index=dates)
    T0["進場時多頭現金%"] = (100 * cash_pct.reindex(T0["進場"]).to_numpy()).round(1)
    T0["原名目占總資產%"] = 20.0
    T0["保證金需求%"] = 18.0
    T0["閒錢夠放足"] = T0["進場時多頭現金%"] - 10 >= 18
    T0["閒錢夠放一半"] = T0["進場時多頭現金%"] - 10 >= 9
    print("\n【原規則 48 筆逐筆：進場當天多頭現金比例】")
    show = T0[["代號", "名稱", "進場", "出場", "天數", "報酬率", "損益", "原因", "進場時多頭現金%", "閒錢夠放足", "閒錢夠放一半"]].copy()
    show["報酬率"] = (100 * show["報酬率"]).round(1); show["損益萬"] = (show.pop("損益") * CAPITAL / 1e4).round(1)
    show["進場"] = show["進場"].dt.date; show["出場"] = pd.to_datetime(show["出場"]).dt.date
    print(show.to_string(index=False))
    byy = T0.assign(年=T0["進場"].dt.year).groupby("年").agg(筆數=("損益", "size"), 損益萬=("損益", lambda x: x.sum() * CAPITAL / 1e4),
                                                        進場時多頭現金pct=("進場時多頭現金%", "mean"), 夠放足=("閒錢夠放足", "sum"), 夠放一半=("閒錢夠放一半", "sum"))
    print("\n【逐年：原規則放空損益 vs 進場時多頭現金】"); print(byy.round(1).to_string())
    print(f"\n48 筆中進場時多頭現金 ≥ 28%（預留 10%＋保證金 18%）的：{int(T0['閒錢夠放足'].sum())} 筆；≥ 19%（放一半）的：{int(T0['閒錢夠放一半'].sum())} 筆")

    # 2. 合併：放空只用多頭閒錢
    variants = {
        "閒錢·名目1/5·預留10%（原規則名目）": dict(size=0.20, reserve=0.10),
        "閒錢·名目1/5·不預留": dict(size=0.20, reserve=0.0),
        "閒錢·名目1/10·預留10%": dict(size=0.10, reserve=0.10),
        "閒錢·名目1/10·不預留": dict(size=0.10, reserve=0.0),
        "閒錢·名目1/20·預留10%": dict(size=0.05, reserve=0.10),
        "閒錢·名目1/5·預留10%·不夠就不空（不縮小）": dict(size=0.20, reserve=0.10, shrink=False),
        "閒錢·名目1/10·預留10%·不夠就不空": dict(size=0.10, reserve=0.10, shrink=False),
    }
    rows, yrs = {}, {}
    for name, kw in variants.items():
        T, comb, _ = simulate(L, "idle", **kw)
        m = metrics(L, T, comb); yrs[name] = m.pop("_yr"); rows[name] = m
        T.to_csv(RESULTS / f"short_combo_trades_{name.replace('（', '(').replace('）', ')').replace('/', '比')}.csv", index=False, encoding="utf-8-sig")
    # 另一種：多頭 500 萬 ＋ 放空另外準備 500 萬保證金（SHORT_RULES 假設），合計 1,000 萬
    long_eq = pd.Series(L["eq"][L["s_n"]:], index=dates[L["s_n"]:])
    both = (long_eq + sep_eq) / 2
    rows["兩個帳戶各 500 萬（多頭＋獨立放空，合計 1,000 萬）"] = {
        "放空筆數": len(T0), "勝率%": 100 * (T0["損益"] > 0).mean(), "每筆平均%": 100 * T0["報酬率"].mean(), "平均名目占原規則%": 100.0,
        "放空總損益萬": T0["損益"].sum() * CAPITAL / 1e4, "前7年放空損益萬": np.nan, "後3年放空損益萬": np.nan, "多頭要用錢筆數": 0, "強制回補": 0, "斷頭": 0,
        "期末萬": both.iloc[-1] * 2 * CAPITAL / 1e4, "純多期末萬": long_eq.iloc[-1] * CAPITAL / 1e4,
        "IRR": 100 * (both.iloc[-1] ** (1 / years) - 1), "純多IRR": rows[next(iter(variants))]["純多IRR"], "前7年IRR": np.nan, "純多前7年IRR": np.nan,
        "回撤": 100 * (both / both.cummax() - 1).min(), "純多回撤": rows[next(iter(variants))]["純多回撤"]}
    D = pd.DataFrame(rows).T
    D["IRR改善"] = D["IRR"] - D["純多IRR"]; D["回撤變化"] = D["回撤"] - D["純多回撤"]
    D.round(2).to_csv(RESULTS / "short_combo_summary.csv", encoding="utf-8-sig")
    print("\n【合併：多頭正式版 ＋ 放空正式版，放空只用多頭閒錢】")
    print(D[["放空筆數", "勝率%", "每筆平均%", "平均名目占原規則%", "放空總損益萬", "前7年放空損益萬", "後3年放空損益萬", "多頭要用錢筆數", "強制回補", "斷頭",
             "期末萬", "純多期末萬", "IRR", "純多IRR", "IRR改善", "回撤", "純多回撤"]].astype(float).round(1).to_string())
    Y = pd.DataFrame(yrs).fillna(0.0)
    Y["原規則(獨立帳戶)"] = T0.assign(年=pd.to_datetime(T0["出場"].fillna(dates[-1])).dt.year).groupby("年")["損益"].sum() * CAPITAL / 1e4
    Y["多頭年底現金%"] = (100 * cash_pct[L["s_n"]:]).groupby(cash_pct.index[L["s_n"]:].year).mean()
    Y["純多年報酬%"] = long_eq.groupby(long_eq.index.year).last().pct_change() * 100
    print("\n【逐年放空損益（萬）】"); print(Y.fillna(0.0).round(1).to_string())
    Y.round(1).to_csv(RESULTS / "short_combo_yearly.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
