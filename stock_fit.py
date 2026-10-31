"""個股認證：一檔股票的「股性」適不適合正式版策略？加進股票池會變好還是變差？

三層檢查，由快到慢：
  第一層 殖利率面（股票本身的體質）：十年內預估殖利率算得出來的天數、≥5% 與 ≥ 買進門檻的天數比例、
         配息年數與配息率的穩定度、近四季 EPS 合計轉負的天數比例。
  第二層 買點事件（不受名額與資金影響的純股性）：每個買點叢集（買點日 20 個交易日內合併）隔天開盤買進後，
         250／500 個交易日內達 +12% 的比例、達標所需天數、250 日報酬、最大不利變動（MAE）。
         這一層直接回答「這檔出現買點之後，會不會像池子裡的股票一樣回升」。
  第三層 單檔模擬：只有這一檔、照正式版全部規則（額度仍是總資產 ÷ 5、首買一半、加碼、續抱、不停損）
         從 2017-01-03 跑到最新：筆數、勝率、平均持有、超過 2 年比例、最深套牢、EPS 轉負出場。
  以上三層對「股性」都用全期間（不管它何時才是成分股），結果跟 75 檔電子股池的分佈對照後給等級：
         適合／普通／不適合（門檻見 GRADE 說明與 results/stock_fit_pool.csv 的池內分佈）。
  第四層（--pool，慢，每組約 1 分鐘）：把候選股加進 75 檔池，跑 20 情境（前 7 年）＋後 3 年延續／單獨，
         與正式版並排：三段平均、最差 10%、標準差。標準差上升視為靠運氣，不採用。
         成分股用真實的成分股期間；非成分股視為全期間可買。另附 500 萬試算（2017-01-03 起）。

用法：
  python stock_fit.py 2330 2412 1216            # 認證指定股票（需在 data/universe 或 data/candidates 有資料）
  python stock_fit.py --calibrate               # 75 檔電子股池全部跑一遍，建立對照基準 results/stock_fit_pool.csv
  python stock_fit.py --non-electronics         # 149 檔成分股裡 74 檔非電子股全部認證
  python stock_fit.py 2330 2412 --pool          # 再加第四層：加入池子後 20 情境的變化（候選股一起加入）
  python stock_fit.py 2330 2412 --pool --each   # 每一檔分別加入各測一次
  python stock_fit.py --check 2330              # 只檢查資料齊不齊

別人推薦的股票怎麼餵資料：放到 data/candidates/（格式與 data/universe 完全相同，不要動 universe）
  data/candidates/prices/<代號>.csv              date,open,high,low,close,adj_close,volume（yfinance auto_adjust=False）
  data/candidates/eps_all.csv                    stock_id,date,value（FinMind TaiwanStockFinancialStatements，type=EPS，單季）
  data/candidates/dividend_all.csv               FinMind TaiwanStockDividend 原始欄位
  data/candidates/dividend_result_all.csv        FinMind TaiwanStockDividendResult 原始欄位
  （雲端環境連不到金融網站，請在本機抓；至少要 2015 年起的資料，EPS 與股利缺了殖利率就算不出來）
"""
import argparse
import pickle
import sys

import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, ELECTRONICS
from yield_entry_study import entries

CAND = ROOT / "data" / "candidates"
CLUSTER_GAP = 20          # 買點日相隔不到 20 個交易日視為同一個買點叢集
HORIZON = 500             # 事件觀察最長 500 個交易日（約 2 年）
START = pd.Timestamp("2017-01-03")

# 等級門檻（依 75 檔電子股池的分佈訂，見 results/stock_fit_pool.csv）
# 不適合：任一成立。適合：全部成立。其餘普通。
GRADE = {
    "不適合": {"買點叢集": ("<", 3), "250日達標%": ("<", 50), "EPS轉負天數%": (">", 15), "配息年數": ("<", 5)},
    "適合": {"買點叢集": (">=", 5), "250日達標%": (">=", 70), "500日達標%": (">=", 80), "MAE中位%": (">", -20),
             "模擬勝率%": (">=", 80), "EPS轉負天數%": ("<=", 5)},
}


# ---------- 資料 ----------

def tables():
    t = {}
    for name in ("eps_all", "dividend_all", "dividend_result_all"):
        parts = [pd.read_csv(ps.UNI / f"{name}.csv")]
        if (CAND / f"{name}.csv").exists():
            parts.append(pd.read_csv(CAND / f"{name}.csv"))
        t[name] = pd.concat(parts, ignore_index=True)
        t[name]["stock_id"] = t[name]["stock_id"].astype(str)
    return t


def price_path(sid):
    for base in (ps.UNI, CAND):
        p = base / "prices" / f"{sid}.csv"
        if p.exists():
            return p
    return None


def load_prices(sid):
    """同 portfolio_study.load_prices，但也找 data/candidates。"""
    path = price_path(sid)
    if path is None:
        return None
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    df = df[df["volume"] > 0].dropna(subset=["open", "high", "low", "close"])
    raw_close = df["close"].copy()
    if "adj_close" in df:
        factor = (df["adj_close"] / df["close"]).fillna(1.0)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col] * factor
    return df.drop(columns=["adj_close"], errors="ignore"), raw_close


def check(sid, t):
    """資料齊不齊：回傳 (ok, 說明)。"""
    msgs = []
    loaded = load_prices(sid)
    if loaded is None:
        return False, f"{sid}: 沒有價格檔（data/universe/prices 或 data/candidates/prices/{sid}.csv）"
    df, _ = loaded
    msgs.append(f"價格 {len(df)} 筆 {df.index[0].date()}～{df.index[-1].date()}")
    if df.index[0] > pd.Timestamp("2016-06-30"):
        msgs.append("價格 2016-06 以後才開始，十年統計不完整")
    e = t["eps_all"][t["eps_all"]["stock_id"] == sid]
    d = t["dividend_all"][t["dividend_all"]["stock_id"] == sid]
    r = t["dividend_result_all"][t["dividend_result_all"]["stock_id"] == sid]
    msgs.append(f"EPS {len(e)} 季、股利政策 {len(d)} 筆、除權息結果 {len(r)} 筆")
    ok = len(df) >= 260 and len(e) >= 8 and (len(d) + len(r)) >= 2
    if len(e) < 8:
        msgs.append("EPS 不足 8 季，殖利率算不出來")
    if len(d) + len(r) < 2:
        msgs.append("沒有股利資料，殖利率算不出來")
    return ok, f"{sid}: " + "；".join(msgs)


def build(sid, dates, t):
    """建立一檔的引擎資料（同 prepare ＋ attach_fundamentals），外加四種技術買點訊號。"""
    df, raw_close = load_prices(sid)
    dps = ps.forward_dividend(df.index, ps.eps_table(t["eps_all"], sid),
                              ps.dividend_events(t["dividend_all"], sid, t["dividend_result_all"]))
    sigs, add = entries(df)
    d = df.reindex(dates)
    last = d["close"].last_valid_index()
    delisted = last is not None and last < dates[-1] - pd.Timedelta(days=10)
    y = (100 * dps / raw_close).reindex(dates).values
    out = {"df": d, "open": d["open"].values, "close": d["close"].values, "low": d["low"].values,
           "close_ff": d["close"].ffill().values, "last_n": dates.get_loc(last) if delisted else len(dates) + 1,
           "add": add.reindex(dates).fillna(False).astype(bool).values, "yield": y,
           "buy": np.zeros(len(dates), bool),
           "sig": {v: sigs[v].reindex(dates).fillna(False).astype(bool).values for v in po.ENTRIES.values()}}
    # attach_fundamentals 讀 UNI/eps_all.csv；候選股的 EPS 可能在 candidates，暫時換掉
    orig = pd.read_csv
    pd.read_csv = lambda p, *a, **k: t["eps_all"] if str(p).endswith("eps_all.csv") else orig(p, *a, **k)
    try:
        ps.attach_fundamentals({sid: out}, dates)
    finally:
        pd.read_csv = orig
    return out


def payout_stats(sid, t):
    """配息年數、配息率平均與變異係數（同 forward_dividend 的年度配息率定義）。"""
    e, div = ps.eps_table(t["eps_all"], sid), ps.dividend_events(t["dividend_all"], sid, t["dividend_result_all"])
    if e.empty or div.empty:
        return 0, np.nan, np.nan
    annual = e.groupby("fy")["eps"].agg(["sum", "size"])
    annual = annual[annual["size"] == 4]["sum"]
    by_fy = div.groupby("fy")["cash"].sum()
    payout = (by_fy / annual.reindex(by_fy.index)).dropna()
    payout = payout[annual.reindex(payout.index) > 0]
    n_years = int((by_fy > 0).sum())
    if len(payout) < 2:
        return n_years, payout.mean() if len(payout) else np.nan, np.nan
    return n_years, payout.clip(0, 2).mean(), payout.clip(0, 2).std() / max(payout.clip(0, 2).mean(), 1e-9)


# ---------- 三層指標 ----------

def yield_metrics(d, thr, s_n):
    y = d["yield"][s_n:]
    th = thr[s_n:]
    has = ~np.isnan(y)
    tradable = ~np.isnan(d["close"][s_n:])
    n = max(tradable.sum(), 1)
    return {"殖利率有值%": 100 * has.sum() / n, "殖利率中位%": np.nanmedian(y) if has.any() else np.nan,
            "殖利率≥5天數%": 100 * (np.nan_to_num(y, nan=-1) >= 5).sum() / n,
            "≥買進門檻天數%": 100 * (np.nan_to_num(y, nan=-1) >= th).sum() / n,
            "EPS轉負天數%": 100 * d["eps_loss"][s_n:][tradable].mean() if tradable.any() else np.nan}


def event_metrics(d, buy, s_n):
    idx = [i for i in np.flatnonzero(buy) if i >= s_n and i + 1 < len(buy) and not np.isnan(d["open"][i + 1])]
    starts, last = [], -10 ** 9
    for i in idx:
        if i - last >= CLUSTER_GAP:
            starts.append(i)
        last = i
    rows = []
    cf = d["close_ff"]
    for i in starts:
        entry = d["open"][i + 1]
        path = cf[i + 1: i + 1 + HORIZON] / entry - 1
        hit = np.flatnonzero(path >= 0.12)
        first = hit[0] if len(hit) else np.nan
        rows.append({"訊號日": d["df"].index[i], "進場價": entry, "達標日數": first,
                     "250日內達標": bool(len(hit) and hit[0] < 250), "500日內達標": bool(len(hit)),
                     "觀察日數": len(path),
                     "250日報酬%": 100 * path[min(249, len(path) - 1)] if len(path) else np.nan,
                     "MAE%": 100 * path[:250].min() if len(path) else np.nan})
    ev = pd.DataFrame(rows)
    if ev.empty:
        return {"買點叢集": 0, "有買點年數": 0, "250日達標%": np.nan, "500日達標%": np.nan, "達標天數中位": np.nan,
                "250日報酬中位%": np.nan, "MAE中位%": np.nan, "MAE最差%": np.nan}, ev
    # 達標率只算觀察得滿的事件（最近 1 年／2 年的買點還沒走完，不算分母）
    m250, m500 = ev["觀察日數"] >= 250, ev["觀察日數"] >= HORIZON
    return {"買點叢集": len(ev), "有買點年數": ev["訊號日"].dt.year.nunique(),
            "250日達標%": 100 * ev.loc[m250, "250日內達標"].mean() if m250.any() else np.nan,
            "500日達標%": 100 * ev.loc[m500, "500日內達標"].mean() if m500.any() else np.nan,
            "達標天數中位": ev["達標日數"].median(), "250日報酬中位%": ev.loc[m250, "250日報酬%"].median() if m250.any() else np.nan,
            "MAE中位%": ev["MAE%"].median(), "MAE最差%": ev["MAE%"].min()}, ev


def sim_metrics(sid, d, member, dates, s_n, kw):
    tr, eq = ps.run({sid: d}, {sid: member}, dates, capital=CAPITAL, start_n=s_n, **kw)
    closed = tr[tr["出場"].notna()]
    held = (pd.to_datetime(tr["出場"]).fillna(dates[-1]) - pd.to_datetime(tr["進場"])).dt.days if len(tr) else pd.Series(dtype=float)
    unreal = (tr.loc[tr["出場"].isna(), "市值"] - tr.loc[tr["出場"].isna(), "投入"]).sum()
    real = (closed["回收"] - closed["投入"]).sum()
    return {"模擬筆數": len(tr), "模擬已結案": len(closed),
            "模擬勝率%": 100 * (closed["報酬%"] > 0).mean() if len(closed) else np.nan,
            "模擬平均報酬%": closed["報酬%"].mean() if len(closed) else np.nan,
            "模擬持有中位天": held.median() if len(held) else np.nan,
            "模擬>2年%": 100 * (held > 730).mean() if len(held) else np.nan,
            "模擬最深套牢%": tr["最深套牢%"].min() if len(tr) else np.nan,
            "EPS轉負出場": int(tr["原因"].astype(str).str.contains("EPS").sum()),
            "模擬損益萬": (real + unreal) * CAPITAL / 1e4}, tr


def grade(row):
    def test(col, op, v):
        x = row.get(col, np.nan)
        if pd.isna(x):
            return op in ("<", "<=")      # 算不出來的指標：當作不及格
        return {"<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v}[op]
    if any(test(c, *cond) for c, cond in GRADE["不適合"].items()):
        return "不適合"
    if all(test(c, *cond) for c, cond in GRADE["適合"].items()):
        return "適合"
    return "普通"


def certify(sids, dates, t, thr, kw, names, s_n):
    rows, events, trades = [], {}, {}
    for sid in sids:
        ok, msg = check(sid, t)
        if not ok:
            print("略過", msg)
            continue
        d = build(sid, dates, t)
        buy = d["sig"][po.ENTRIES[dr.FINAL["entry"]]] & ~np.isnan(thr) & (np.nan_to_num(d["yield"], nan=-1) >= thr)
        d["buy"] = buy
        member = pd.Series(True, index=dates)
        y = yield_metrics(d, thr, s_n)
        e, ev = event_metrics(d, buy, s_n)
        s, tr = sim_metrics(sid, d, member, dates, s_n, kw)
        ny, pm, pcv = payout_stats(sid, t)
        row = {"代號": sid, "名稱": names.get(sid, ""), "電子股": sid in ELECTRONICS,
               "資料起": d["df"]["close"].first_valid_index().date(), **y, "配息年數": ny, "配息率平均": pm, "配息率變異": pcv,
               **e, **s}
        row["等級"] = grade(row)
        rows.append(row)
        events[sid], trades[sid] = ev, tr
        print(f"{sid} {names.get(sid, ''):　<6} {row['等級']}　買點叢集 {e['買點叢集']:>3}　250日達標 {e['250日達標%']:5.0f}%　"
              f"MAE中位 {e['MAE中位%']:6.1f}%　模擬 {s['模擬筆數']:>2} 筆 勝率 {s['模擬勝率%']:5.0f}%　損益 {s['模擬損益萬']:7.0f} 萬", flush=True)
    return pd.DataFrame(rows), events, trades


# ---------- 第四層：加進池子 ----------

def official_500(sub, member, dates, kw, start=START):
    s_n = dates.get_indexer([start], method="bfill")[0]
    tr, eq = ps.run(sub, member, dates, capital=CAPITAL, start_n=s_n, **kw)
    eq = eq * CAPITAL
    return {"期末萬": eq.iloc[-1] / 1e4, "IRR%": irr([CAPITAL], [dates[s_n]], eq.iloc[-1], dates[-1]),
            "回撤%": 100 * (eq / eq.cummax() - 1).min(), "筆數": len(tr)}, tr


def pool_test(cands, dates, t, cons, kw, names, label, fname):
    """cands: 候選代號清單；label 顯示用、fname 檔名用。回傳 (20 情境彙整列, 500 萬試算列)。"""
    G = rs.G
    base = {k: dict(G[k]) for k in ("sub", "member")}
    base_sig = {k: dict(v) for k, v in G["sig"].items()}
    try:
        for sid in cands:
            d = build(sid, dates, t)
            G["sub"][sid] = d
            G["member"][sid] = ps.membership(cons[cons["stock_id"] == sid], dates)[sid] if sid in set(cons["stock_id"]) \
                else pd.Series(True, index=dates)
            for k, v in po.ENTRIES.items():
                G["sig"][v][sid] = d["sig"][v]
        po._applied["buy"] = None
        po.CONFIGS[label] = dr.FINAL
        m = po.evaluate([label], f"fit_{fname}").loc[label]
        po.apply(dr.FINAL)
        money, tr = official_500(G["sub"], G["member"], dates, kw)
        cand_tr = tr[tr["代號"].isin(cands)]
        closed = cand_tr[cand_tr["出場"].notna()]
        money.update({"候選股筆數": len(cand_tr),
                      "候選股損益萬": ((closed["回收"] - closed["投入"]).sum()
                                  + (cand_tr.loc[cand_tr["出場"].isna(), "市值"] - cand_tr.loc[cand_tr["出場"].isna(), "投入"]).sum()) * CAPITAL / 1e4})
        tr["名稱"] = tr["代號"].map(names)
        tr.to_csv(RESULTS / f"stock_fit_{fname}_pool_trades.csv", index=False, encoding="utf-8-sig")
    finally:
        for k in ("sub", "member"):
            G[k].clear(); G[k].update(base[k])
        G["sig"].clear(); G["sig"].update(base_sig)
        po._applied["buy"] = None
    return m, money


POOL_SHOW = ["前7年", "前7年最差10", "前7年標準差", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "最長持有", "超過2年比例"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--calibrate", action="store_true", help="75 檔電子股池全部認證，寫 results/stock_fit_pool.csv")
    ap.add_argument("--non-electronics", action="store_true", help="74 檔非電子成分股全部認證")
    ap.add_argument("--check", action="store_true", help="只檢查資料")
    ap.add_argument("--pool", action="store_true", help="加進池子跑 20 情境＋後 3 年")
    ap.add_argument("--each", action="store_true", help="--pool 時每檔分別加入")
    ap.add_argument("--tag", default=None, help="輸出檔名標籤")
    a = ap.parse_args()

    t = tables()
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    if (CAND / "names.csv").exists():
        names.update(dict(pd.read_csv(CAND / "names.csv", dtype=str)[["stock_id", "name"]].values))
    sids = list(a.sids)
    if a.calibrate:
        sids += sorted(ELECTRONICS & set(cons["stock_id"]))
    if a.non_electronics:
        sids += sorted(set(cons["stock_id"]) - ELECTRONICS)
    if a.check:
        for sid in sids:
            print(check(sid, t)[1])
        return
    if not sids:
        ap.print_help(); return

    po.setup()
    G = rs.G
    dates = G["dates"]
    po.apply(dr.FINAL)
    kw = po.to_kw(dr.FINAL)
    thr = po.buy_threshold(dr.FINAL)
    s_n = dates.get_indexer([START], method="bfill")[0]
    tag = a.tag or ("pool" if a.calibrate else "nonelec" if a.non_electronics else "_".join(sids[:6]))

    print(f"正式版規則、買進門檻 max(市場中位數, 5%)、全期間可買、{dates[s_n].date()} 起跑；池內對照基準：results/stock_fit_pool.csv\n")
    df, events, trades = certify(sids, dates, t, thr, kw, names, s_n)
    if df.empty:
        return
    df.round(2).to_csv(RESULTS / f"stock_fit_{tag}.csv", index=False, encoding="utf-8-sig")
    if any(len(ev) for ev in events.values()):
        pd.concat([ev.assign(代號=s) for s, ev in events.items() if len(ev)], ignore_index=True) \
            .to_csv(RESULTS / f"stock_fit_{tag}_events.csv", index=False, encoding="utf-8-sig", float_format="%.2f")
    if any(len(tr) for tr in trades.values()):
        pd.concat([tr.assign(名稱=names.get(s, "")) for s, tr in trades.items() if len(tr)], ignore_index=True) \
            .to_csv(RESULTS / f"stock_fit_{tag}_trades.csv", index=False, encoding="utf-8-sig", float_format="%.4f")

    show = ["代號", "名稱", "等級", "殖利率≥5天數%", "配息年數", "配息率變異", "EPS轉負天數%", "買點叢集", "有買點年數",
            "250日達標%", "500日達標%", "達標天數中位", "MAE中位%", "模擬筆數", "模擬勝率%", "模擬>2年%", "模擬最深套牢%", "模擬損益萬"]
    with pd.option_context("display.width", 320, "display.max_rows", 500, "display.unicode.east_asian_width", True):
        print("\n" + df[show].round(1).sort_values(["等級", "模擬損益萬"], ascending=[True, False]).to_string(index=False))
    pool_csv = RESULTS / "stock_fit_pool.csv"
    if pool_csv.exists() and not a.calibrate:
        ref = pd.read_csv(pool_csv, dtype={"代號": str})
        print("\n75 檔電子股池的分佈（25%／中位／75%）供對照：")
        q = ref[["買點叢集", "250日達標%", "500日達標%", "MAE中位%", "模擬勝率%", "模擬>2年%", "EPS轉負天數%", "模擬損益萬"]].quantile([.25, .5, .75]).round(1)
        q.index = ["25%", "中位", "75%"]
        print(q.to_string())
        print("池內等級分佈：", ref["等級"].value_counts().to_dict())

    if a.pool:
        groups = [[s] for s in df["代號"]] if a.each else [list(df["代號"])]
        print("\n第四層：加進 75 檔池（成分股用真實期間、其他全期間）跑 20 情境＋後 3 年，與正式版並排")
        po.CONFIGS["正式版"] = dr.FINAL
        po._applied["buy"] = None
        rows = {"正式版（75 檔）": po.evaluate(["正式版"], "fit_base").loc["正式版"]}
        po.apply(dr.FINAL)
        money = {"正式版（75 檔）": official_500(G["sub"], G["member"], dates, kw)[0]}
        for i, g in enumerate(groups, 1):
            label = "＋" + "、".join(f"{s}{names.get(s, '')}" for s in g[:4]) + (f"…共{len(g)}檔" if len(g) > 4 else "")
            rows[label], money[label] = pool_test(g, dates, t, cons, kw, names, label, f"{tag}_{i}")
            print(f"  {label} 完成", flush=True)
        out = pd.DataFrame(rows).T[POOL_SHOW]
        out["三段平均差"] = out["三段平均"] - out.iloc[0]["三段平均"]
        out["標準差差"] = out["標準差平均"] - out.iloc[0]["標準差平均"]
        mon = pd.DataFrame(money).T
        with pd.option_context("display.width", 320, "display.max_rows", 500, "display.unicode.east_asian_width", True):
            print("\n20 情境＋後 3 年（IRR％）")
            print(out.round(1).to_string())
            print("\n500 萬、2017-01-03 起跑、不追加")
            print(mon.round(1).to_string())
        out.round(2).to_csv(RESULTS / f"stock_fit_{tag}_pool20.csv", encoding="utf-8-sig")
        mon.round(2).to_csv(RESULTS / f"stock_fit_{tag}_pool500.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
