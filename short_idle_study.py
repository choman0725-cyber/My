"""做多為主、空檔放空：正式版多頭策略完全不動，用「空出來的名額與閒置現金」疊加放空，看能不能多賺。

多頭：正式版（買進門檻 max(市場中位數, 5%)、停利 12%、續抱 4.75%、最多 5 檔），決策完全不受放空影響。
放空只能用多頭用不到的資源：
  名額：預設只看現金（slot_mode="cash"，放空最多 max_short 檔）。多頭的 5 檔名額幾乎永遠滿的——套牢／久抱部位不佔名額，
        實際持股常有 7～11 檔，所以「空名額」幾乎不存在；slot_mode="slots" 時放空檔數 <= min(上限, 5 − 多頭持股數)，只做對照
  現金：融券保證金 90% 只能用「多頭現金 ＋ 放空累計損益 − 預留（總資產 × reserve）」；
        多頭買股後現金不夠維持保證金 → 同一天開盤先回補放空（多頭優先）
放空進場（收盤訊號，隔天開盤放空）：
  共振超買：近 3 日 KD>80／RSI>70／WR>−20／CCI>100 至少 3 個 ＋ KD 死叉（多頭「共振」買點的鏡像）
  高檔出貨：近 5 日曾觸布林上軌且 K>70 ＋ 爆量長上影線／爆量長黑／價創高量縮（多頭「混合」買點的鏡像）
  布林KD超買：近 3 日曾觸布林上軌 ＋ K>70 死叉（多頭「布林KD」買點的鏡像）
  任一：三者任一
濾網：無／預估殖利率 <3%（貴）／殖利率 < 市場中位數／股價 < 季線／大盤 < 季線／殖利率<中位數＋大盤<季線
回補（收盤判斷，隔天開盤）：停利 X%／停損 Y%／最多 N 個交易日／出現多頭技術買訊／站回月線／固定 N 日
  另外一律：除息（權）日前 5 個交易日強制回補且除息前不新放空、每年 4 月第一個交易日強制回補
  （融券停止過戶強制回補的近似），force=False 可關掉（借券賣出沒有這個限制）
成本：放空 0.1425%＋證交稅 0.3%，回補 0.1425%，借券費 2%/年；用還原價（放空者要付股利，剛好與還原價不跳空相抵）
部位：每筆放空金額＝前一日總資產 ÷ 5 × size（預設 0.5，與多頭首買一樣是總資產 10%）；同日多檔依殖利率低到高挑（最貴的先）
評估：合併資產 = 多頭資產 ＋ 放空已實現 ＋ 放空未實現（含借券費）。先用 2017～2023 的多空合併 IRR 選，2024～2026 只驗證。
用法：python short_idle_study.py grid      # 全部組合（結果 results/short_idle_grid.csv）
      python short_idle_study.py detail    # 前幾名的敏感度、其他起始日、追加資金、逐筆
"""
import pickle
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import BUY_COST, RESULTS, ROOT, SELL_COST
from indicators import bollinger, cci_line, cross_down, kd, pv_triggers, rsi, setup_zones, sma, williams_r
from meanrev_study import _recent
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, ELECTRONICS
from yield_entry_study import entries

IS_END = pd.Timestamp("2023-12-31")
MARGIN, BORROW = 0.90, 0.02
G = rs.G
S = {}   # 放空用資料：訊號、價格、濾網

ENTRIES = ["共振超買", "高檔出貨", "布林KD超買", "任一"]
FILTERS = {
    "無": lambda s, n: np.ones(n, bool),
    "殖利率<3%": lambda s, n: np.nan_to_num(s["yield"], nan=np.inf) < 3.0,
    "殖利率<中位數": lambda s, n: np.nan_to_num(s["yield"], nan=np.inf) < S["med"],
    "股價<月線": lambda s, n: ~s["above_ma20"],
    "股價<季線": lambda s, n: s["below_ma60"],
    "大盤<月線": lambda s, n: S["taiex_below20"],
    "大盤<季線": lambda s, n: S["taiex_below60"],
    "殖利率<中位數＋大盤<季線": lambda s, n: (np.nan_to_num(s["yield"], nan=np.inf) < S["med"]) & S["taiex_below60"],
}
# (停利, 停損, 最多交易日, 多頭買訊回補, 站回月線回補)
COVERS = {
    "停利10停損10最多60日": (0.10, 0.10, 60, False, False),
    "停利10停損10最多120日": (0.10, 0.10, 120, False, False),
    "停利15停損10最多120日": (0.15, 0.10, 120, False, False),
    "停利20停損10最多250日": (0.20, 0.10, 250, False, False),
    "多頭買訊或停損10": (None, 0.10, None, True, False),
    "站回月線或停利10": (0.10, None, None, False, True),
    "固定20日": (None, None, 20, False, False),
}
POOLS = {"電子股": None, "全成分股": None}


# ---------- 資料 ----------

def short_signals(d, dates):
    px = d["df"].dropna(subset=["open", "close"])
    c = px["close"]
    k, dd = kd(px)
    r, wr, cc = rsi(c), williams_r(px), cci_line(px)
    n_ob = sum(_recent(x, 3).astype(int) for x in (k > 80, r > 70, wr > -20, cc > 100))
    _, high_zone, mid, _, _ = setup_zones(px)
    t = pv_triggers(px)
    _, _, upper = bollinger(px)
    touched_up = (px["high"] >= upper).astype(int).rolling(3).max().astype(bool)
    e, _ = entries(px)
    rx = lambda s_: s_.reindex(dates).fillna(False).astype(bool).values
    sig = {
        "共振超買": rx((n_ob >= 3) & cross_down(k, dd)),
        "高檔出貨": rx(high_zone & (t["wick_sell"] | t["pv_sell"])),
        "布林KD超買": rx(touched_up & cross_down(k, dd) & (k > 70)),
    }
    sig["任一"] = sig["共振超買"] | sig["高檔出貨"] | sig["布林KD超買"]
    return sig | {
        "buy_any": rx(e["任一"]),
        "above_ma20": rx(c > sma(c, 20)),
        "below_ma60": rx(c < sma(c, 60)),
    }


def setup():
    po.setup()
    po.apply(dr.FINAL)
    dates = G["dates"]
    N = len(dates)
    data, _ = pickle.loads((RESULTS / "portfolio_prepared.pkl").read_bytes())
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    member_all = ps.membership(cons, dates)
    member_elec = G["member"]
    med, _, _ = po.market_stats("all")
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    taiex_below60 = (tx < sma(tx, 60)).reindex(dates).fillna(False).astype(bool).values
    taiex_below20 = (tx < sma(tx, 20)).reindex(dates).fillna(False).astype(bool).values
    res = pd.read_csv(ps.UNI / "dividend_result_all.csv", dtype={"stock_id": str}, parse_dates=["date"])
    apr = np.zeros(N, bool)
    for y in sorted(set(dates.year)):
        i = np.flatnonzero((dates.year == y) & (dates.month >= 4))
        if len(i):
            apr[i[0]] = True
    stocks = {}
    for sid, d in data.items():
        if sid not in member_all:
            continue
        s = short_signals(d, dates)
        s.update(open=d["open"], close=d["close"], close_ff=d["close_ff"], yield_=d["yield"], last_n=d["last_n"],
                 member_all=member_all[sid].values, member_elec=member_elec[sid].values if sid in member_elec else np.zeros(N, bool))
        s["yield"] = s.pop("yield_")
        force, block = apr.copy(), np.zeros(N, bool)
        ex = res[res["stock_id"] == sid]["date"]
        for n_ex in dates.get_indexer(ex[(ex >= dates[0]) & (ex <= dates[-1])], method="bfill"):
            if n_ex >= 5:
                force[n_ex - 5] = True
                block[max(n_ex - 6, 0):n_ex + 1] = True
        s["force"], s["block"] = force, block
        stocks[sid] = s
    S.update(dates=dates, N=N, stocks=stocks, med=np.nan_to_num(med, nan=np.inf), taiex_below60=taiex_below60, taiex_below20=taiex_below20)
    POOLS["電子股"] = sorted(sid for sid in stocks if sid in ELECTRONICS)
    POOLS["全成分股"] = sorted(stocks)


def long_path(start="2017-01-03", contrib_sched=None):
    """跑正式版多頭，回傳每日多頭資產、交易後現金、持股檔數、持股集合（以初始資金 1.0 計）與現金流。"""
    dates = S["dates"]; N = S["N"]
    kw = po.to_kw(dr.FINAL)
    s_n = dates.get_indexer([pd.Timestamp(start)], method="bfill")[0]
    sched = {y: a for y, a in (contrib_sched or {}).items() if dates[s_n].year < y}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched}
    contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
    ledger = []
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, start_n=s_n, ledger=ledger, **kw)
    cash = np.full(N, np.nan); count = np.zeros(N, int); held = [set() for _ in range(N)]
    cash[s_n] = 1.0
    L = pd.DataFrame(ledger)
    if len(L):
        L["n"] = dates.get_indexer(L["日期"])
        last = L.groupby("n").last()
        for n, row in last.iterrows():
            cash[n] = row["現金"]
            held[n] = {x.split("(")[0] for x in row["持股"].split("、") if x}
            count[n] = len(held[n])
    for n in range(s_n + 1, N):
        if np.isnan(cash[n]):
            cash[n] = cash[n - 1]; held[n] = held[n - 1]; count[n] = count[n - 1]
    eq_arr = np.full(N, np.nan); eq_arr[s_n:] = eq.values
    flows = [CAPITAL] + list(sched.values()); flow_dates = [dates[s_n]] + [dates[first_day[y]] for y in sched]
    return dict(s_n=s_n, eq=eq_arr, cash=cash, count=count, held=held, trades=tr, contrib=contrib or {},
                flows=flows, flow_dates=flow_dates)


# ---------- 放空疊加 ----------

def simulate(L, pool, entry, filt, cover, max_short=3, size=0.5, reserve=0.10, force=True, borrow=BORROW, min_frac=0.25,
             slot_mode="cash"):
    dates, N, stocks = S["dates"], S["N"], S["stocks"]
    s_n, eq_long, cash_long, count_long, held_long = L["s_n"], L["eq"], L["cash"], L["count"], L["held"]
    tp, sl, max_days, cover_buy, cover_ma20 = COVERS[cover]
    mkey = "member_elec" if pool == "電子股" else "member_all"
    E = {sid: stocks[sid][entry] & FILTERS[filt](stocks[sid], N) & stocks[sid][mkey] for sid in POOLS[pool]}
    shorts, trades, comb = {}, [], np.full(N, np.nan)
    realized, mtm_prev, locked = 0.0, 0.0, 0.0
    comb[s_n] = eq_long[s_n]

    def cover_at(sid, n, price, reason):
        nonlocal realized, locked
        s = shorts.pop(sid)
        days = n - s["start"]
        fee = s["notional"] * borrow * (dates[n] - dates[s["start"]]).days / 365
        pnl = s["shares"] * s["price_net"] - s["shares"] * price * (1 + BUY_COST) - fee
        realized += pnl
        locked -= s["margin"]
        trades.append({"代號": sid, "放空": dates[s["start"]], "回補": dates[n], "原因": reason, "放空價": s["entry_px"], "回補價": price,
                       "金額": s["notional"], "損益": pnl, "報酬%": 100 * pnl / s["notional"], "交易日": days,
                       "持有日": (dates[n] - dates[s["start"]]).days})

    for n in range(s_n + 1, N):
        p = n - 1
        assets_p = eq_long[p] + realized + mtm_prev
        for sid in list(shorts):
            s, st = shorts[sid], stocks[sid]
            if p >= st["last_n"] and n > st["last_n"]:
                cover_at(sid, n, st["close_ff"][st["last_n"]], "下市結算"); continue
            o, c = st["open"][n], st["close"][p]
            if np.isnan(o) or np.isnan(c):
                continue
            gain = (s["price_net"] - c * (1 + BUY_COST)) / s["entry_px"]
            reason = None
            if force and st["force"][n]:
                reason = "強制回補(除息/停止過戶)"
            elif tp is not None and gain >= tp:
                reason = "停利"
            elif sl is not None and gain <= -sl:
                reason = "停損"
            elif max_days is not None and n - s["start"] >= max_days:
                reason = "到期"
            elif cover_buy and st["buy_any"][p]:
                reason = "多頭買訊"
            elif cover_ma20 and st["above_ma20"][p]:
                reason = "站回月線"
            if reason:
                cover_at(sid, n, o, reason)
        # 多頭優先：多頭買股後現金不夠維持保證金 → 先回補（虧最多的先）
        while shorts and cash_long[n] + realized + mtm_prev < locked:
            worst = min(shorts, key=lambda q: (shorts[q]["price_net"] - stocks[q]["close_ff"][p]) / shorts[q]["entry_px"])
            o = stocks[worst]["open"][n]
            cover_at(worst, n, o if not np.isnan(o) else stocks[worst]["close_ff"][p], "多頭要用錢")
        free = (max_short if slot_mode == "cash" else min(max_short, ps.MAX_SLOTS - count_long[n])) - len(shorts)
        avail = cash_long[n] + realized + mtm_prev - reserve * assets_p - locked
        if free > 0 and avail > 0:
            cands = [(np.nan_to_num(stocks[sid]["yield"][p], nan=np.inf), sid) for sid in POOLS[pool]
                     if E[sid][p] and sid not in shorts and sid not in held_long[n]
                     and not np.isnan(stocks[sid]["open"][n]) and not (force and stocks[sid]["block"][n])
                     and p < stocks[sid]["last_n"]]
            for _, sid in sorted(cands)[:free]:
                notional = assets_p / ps.MAX_SLOTS * size
                if MARGIN * notional > avail:
                    notional = avail / MARGIN
                if notional < min_frac * assets_p / ps.MAX_SLOTS * size:
                    break
                o = stocks[sid]["open"][n]
                shorts[sid] = {"start": n, "entry_px": o, "price_net": o * (1 - SELL_COST), "shares": notional / o,
                               "notional": notional, "margin": MARGIN * notional}
                locked += MARGIN * notional
                avail -= MARGIN * notional
        mtm = 0.0
        for sid, s in shorts.items():
            st = stocks[sid]
            mtm += s["shares"] * (s["price_net"] - st["close_ff"][n]) \
                - s["notional"] * borrow * (dates[n] - dates[s["start"]]).days / 365
        mtm_prev = mtm
        comb[n] = eq_long[n] + realized + mtm
    for sid, s in shorts.items():
        st = stocks[sid]
        px = st["close_ff"][N - 1]
        pnl = s["shares"] * (s["price_net"] - px * (1 + BUY_COST)) - s["notional"] * borrow * (dates[N - 1] - dates[s["start"]]).days / 365
        trades.append({"代號": sid, "放空": dates[s["start"]], "回補": None, "原因": "持有中", "放空價": s["entry_px"], "回補價": px,
                       "金額": s["notional"], "損益": pnl, "報酬%": 100 * pnl / s["notional"], "交易日": N - 1 - s["start"],
                       "持有日": (dates[N - 1] - dates[s["start"]]).days})
    return pd.DataFrame(trades), pd.Series(comb[s_n:], index=dates[s_n:])


def nav_mdd(eq, contrib, dates):
    rets = eq.pct_change()
    for n, a in contrib.items():
        d = dates[n]
        if d in rets.index and d != eq.index[0]:
            rets.loc[d] = (eq.loc[d] - a) / eq.shift(1).loc[d] - 1
    nav = (1 + rets.fillna(0)).cumprod()
    return 100 * (nav / nav.cummax() - 1).min()


def metrics(L, tr, comb):
    dates = S["dates"]
    e_is = dates.get_indexer([IS_END], method="ffill")[0]
    def seg(eq, end_n):
        flows = [c for c, d in zip(L["flows"], L["flow_dates"]) if d <= dates[end_n]]
        fd = [d for d in L["flow_dates"] if d <= dates[end_n]]
        return irr(flows, fd, eq.iloc[end_n - L["s_n"]] * CAPITAL, dates[end_n])
    long_eq = pd.Series(L["eq"][L["s_n"]:], index=comb.index)
    closed = tr[tr["回補"].notna()] if len(tr) else tr
    is_tr = closed[closed["回補"] <= IS_END] if len(closed) else closed
    oos_tr = closed[closed["回補"] > IS_END] if len(closed) else closed
    m = {"放空筆數": len(tr), "勝率%": 100 * (closed["損益"] > 0).mean() if len(closed) else np.nan,
         "每筆平均%": closed["報酬%"].mean() if len(closed) else np.nan, "平均交易日": closed["交易日"].mean() if len(closed) else np.nan,
         "放空總損益萬": tr["損益"].sum() * CAPITAL / 1e4 if len(tr) else 0.0,
         "前7年放空損益萬": is_tr["損益"].sum() * CAPITAL / 1e4 if len(is_tr) else 0.0,
         "後3年放空損益萬": (oos_tr["損益"].sum() + tr[tr["回補"].isna()]["損益"].sum()) * CAPITAL / 1e4 if len(tr) else 0.0,
         "強制回補筆數": int(tr["原因"].astype(str).str.startswith("強制").sum()) if len(tr) else 0,
         "多頭要用錢筆數": int((tr["原因"] == "多頭要用錢").sum()) if len(tr) else 0,
         "期末萬": comb.iloc[-1] * CAPITAL / 1e4, "純多期末萬": long_eq.iloc[-1] * CAPITAL / 1e4,
         "IRR": seg(comb, len(dates) - 1), "純多IRR": seg(long_eq, len(dates) - 1),
         "前7年IRR": seg(comb, e_is), "純多前7年IRR": seg(long_eq, e_is),
         "回撤": nav_mdd(comb, L["contrib"], dates), "純多回撤": nav_mdd(long_eq, L["contrib"], dates)}
    m["後3年IRR"] = 100 * ((comb.iloc[-1] / comb.iloc[e_is - L["s_n"]]) ** (365.25 / (dates[-1] - dates[e_is]).days) - 1) if not L["contrib"] else np.nan
    m["純多後3年IRR"] = 100 * ((long_eq.iloc[-1] / long_eq.iloc[e_is - L["s_n"]]) ** (365.25 / (dates[-1] - dates[e_is]).days) - 1) if not L["contrib"] else np.nan
    return m


_L = {}


def one(task):
    pool, entry, filt, cover, extra = task
    tr, comb = simulate(_L["base"], pool, entry, filt, cover, **extra)
    return task, metrics(_L["base"], tr, comb)


def grid():
    _L["base"] = long_path()
    tasks = [(pl, e, f, c, {}) for pl in POOLS for e in ENTRIES for f in FILTERS for c in COVERS]
    print(f"多空合併回測：{len(tasks)} 組（純多頭正式版 500 萬 2017-01 起：期末 {_L['base']['eq'][-1] * CAPITAL / 1e4:,.0f} 萬）", flush=True)
    with Pool(4) as p:
        res = p.map(one, tasks, chunksize=8)
    rows = [dict(股票池=t[0], 進場=t[1], 濾網=t[2], 回補=t[3], **m) for t, m in res]
    df = pd.DataFrame(rows)
    df["前7年IRR改善"] = df["前7年IRR"] - df["純多前7年IRR"]
    df["後3年IRR改善"] = df["後3年IRR"] - df["純多後3年IRR"]
    df["IRR改善"] = df["IRR"] - df["純多IRR"]
    df = df.sort_values("前7年IRR改善", ascending=False)
    df.round(2).to_csv(RESULTS / "short_idle_grid.csv", index=False, encoding="utf-8-sig")
    show = ["股票池", "進場", "濾網", "回補", "放空筆數", "勝率%", "每筆平均%", "平均交易日", "前7年放空損益萬", "後3年放空損益萬",
            "前7年IRR改善", "後3年IRR改善", "IRR改善", "期末萬", "回撤", "強制回補筆數", "多頭要用錢筆數"]
    with pd.option_context("display.width", 320, "display.max_rows", 500, "display.unicode.east_asian_width", True):
        print("\n【純多頭正式版】", {k: round(v, 1) for k, v in res[0][1].items() if k.startswith("純多")})
        print("\n【前 7 年（2017～2023）多空合併 IRR 改善前 25 名；後 3 年只做驗證】")
        print(df[show].head(25).round(1).to_string(index=False))
        print("\n【前 7 年改善最差 10 名】")
        print(df[show].tail(10).round(1).to_string(index=False))
        print("\n【各濾網平均（全部進場×回補×股票池）】")
        print(df.groupby("濾網")[["放空筆數", "勝率%", "每筆平均%", "前7年放空損益萬", "後3年放空損益萬", "前7年IRR改善", "後3年IRR改善"]].mean().round(1).to_string())
        print("\n【各回補規則平均】")
        print(df.groupby("回補")[["放空筆數", "勝率%", "每筆平均%", "前7年放空損益萬", "後3年放空損益萬", "前7年IRR改善", "後3年IRR改善"]].mean().round(1).to_string())
        print("\n【各進場訊號平均】")
        print(df.groupby("進場")[["放空筆數", "勝率%", "每筆平均%", "前7年放空損益萬", "後3年放空損益萬", "前7年IRR改善", "後3年IRR改善"]].mean().round(1).to_string())
        both = df[(df["前7年IRR改善"] > 0) & (df["後3年IRR改善"] > 0)]
        print(f"\n前 7 年與後 3 年都有改善的組合：{len(both)} / {len(df)}")
        if len(both):
            print(both[show].head(15).round(1).to_string(index=False))


def detail():
    g = pd.read_csv(RESULTS / "short_idle_grid.csv")
    both = g[(g["前7年IRR改善"] > 0) & (g["後3年IRR改善"] > 0)].sort_values("前7年IRR改善", ascending=False)
    top = pd.concat([g.head(2), both.head(2)]).drop_duplicates(["股票池", "進場", "濾網", "回補"])
    _L["base"] = long_path()
    names = pd.read_csv(ps.UNI / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]
    rows = []
    with pd.option_context("display.width", 320, "display.max_rows", 500, "display.unicode.east_asian_width", True):
        for _, r in top.iterrows():
            key = (r["股票池"], r["進場"], r["濾網"], r["回補"])
            print(f"\n===== {'｜'.join(key)} =====")
            # 敏感度
            for label, extra in [("基準 3檔·0.5·預留10%", {}), ("放空上限1檔", {"max_short": 1}), ("放空上限2檔", {"max_short": 2}), ("放空上限5檔", {"max_short": 5}),
                                 ("每筆0.25", {"size": 0.25}), ("每筆1.0", {"size": 1.0}), ("不預留", {"reserve": 0.0}), ("預留20%", {"reserve": 0.20}),
                                 ("不強制回補(借券)", {"force": False}), ("借券費4%", {"borrow": 0.04}),
                                 ("只用多頭空名額", {"slot_mode": "slots"})]:
                tr, comb = simulate(_L["base"], *key, **extra)
                m = metrics(_L["base"], tr, comb)
                rows.append(dict(組合="｜".join(key), 測試=label, 起始="2017-01-03", 追加="不追加", **m))
            # 其他起始日與追加
            for start in ("2017-07-03", "2018-01-02", "2019-01-02"):
                Lx = long_path(start)
                tr, comb = simulate(Lx, *key)
                rows.append(dict(組合="｜".join(key), 測試="基準", 起始=start, 追加="不追加", **metrics(Lx, tr, comb)))
            for cname, sched in (("每年50萬", {y: 500_000 for y in range(2018, 2027)}), ("每年100萬", {y: 1_000_000 for y in range(2018, 2027)})):
                Lx = long_path("2017-01-03", sched)
                tr, comb = simulate(Lx, *key)
                rows.append(dict(組合="｜".join(key), 測試="基準", 起始="2017-01-03", 追加=cname, **metrics(Lx, tr, comb)))
            tr, comb = simulate(_L["base"], *key)
            tr["名稱"] = tr["代號"].map(names)
            for c in ("金額", "損益"):
                tr[c] = tr[c] * CAPITAL / 1e4
            num = tr.select_dtypes("number").columns
            tr[num] = tr[num].round(1)
            tr.to_csv(RESULTS / f"short_idle_trades_{'_'.join(key).replace('<', '＜')}.csv", index=False, encoding="utf-8-sig")
            print("逐筆（金額、損益單位：萬）")
            print(tr.to_string(index=False))
            yr = tr.assign(年=pd.to_datetime(tr["回補"].fillna(S["dates"][-1])).dt.year).groupby("年").agg(筆數=("損益", "size"), 損益萬=("損益", "sum"), 勝率=("損益", lambda x: 100 * (x > 0).mean()))
            long_eq = pd.Series(_L["base"]["eq"][_L["base"]["s_n"]:], index=comb.index)
            yl = pd.DataFrame({"純多年報酬%": long_eq.groupby(long_eq.index.year).last().pct_change() * 100,
                               "多空年報酬%": comb.groupby(comb.index.year).last().pct_change() * 100})
            print("\n每年：")
            print(yr.join(yl, how="outer").round(1).to_string())
        D = pd.DataFrame(rows)
        D["IRR改善"] = D["IRR"] - D["純多IRR"]; D["前7年IRR改善"] = D["前7年IRR"] - D["純多前7年IRR"]; D["回撤變化"] = D["回撤"] - D["純多回撤"]
        D.round(2).to_csv(RESULTS / "short_idle_detail.csv", index=False, encoding="utf-8-sig")
        print("\n【敏感度／其他起始日／追加資金】")
        print(D[["組合", "測試", "起始", "追加", "放空筆數", "勝率%", "每筆平均%", "放空總損益萬", "期末萬", "純多期末萬", "IRR", "純多IRR", "IRR改善", "前7年IRR改善", "回撤", "純多回撤", "多頭要用錢筆數"]].round(1).to_string(index=False))


if __name__ == "__main__":
    setup()
    {"grid": grid, "detail": detail}[sys.argv[1] if len(sys.argv) > 1 else "grid"]()
