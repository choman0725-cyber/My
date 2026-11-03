"""MSCI 風格的成長股判定（近似版，2026-11-03 使用者「使用 MSCI 的規則判斷成長股」）。
MSCI 成長／價值風格指數用 8 個變數：成長 5 個（長期預估 EPS 成長、短期預估 EPS 成長、當前內部成長率＝ROE×(1−配息率)、長期歷史 EPS 成長趨勢、
長期歷史每股營收成長趨勢），價值 3 個（B/P、12 個月預估 E/P、D/P）。每個變數做橫斷面 z 分數，平均成成長分數與價值分數，再看哪邊強。
這裡沒有分析師預估、也沒有淨值，所以用手上有的 5 個：
  成長：①長期歷史 EPS 成長趨勢（最近 5 個已知完整年度 EPS 的回歸斜率 ÷ 平均絕對值）、②長期歷史營收成長趨勢（同法，年營收）、
        ③短期 EPS 成長（最近四季 EPS 合計 ÷ 前四季 − 1，當作「短期預估」的替身）
  價值：④E/P（最近四季 EPS ÷ 收盤）、⑤D/P（最近 12 個月現金股利 ÷ 收盤）
財報「已知日」照 portfolio_study.eps_table 的法定公布期限；每個公布日重算一次，日與日之間沿用；z 分數在股票池內算（47 檔）、截尾 ±3。
成長股＝成長分數 − 價值分數 > 0（MSCI 是看兩個分數的相對位置分配到成長／價值，這裡簡化成差 > 0；buffer 參數可加遲滯）。
用法：from msci_growth import msci_flags；flags = msci_flags(G)  → {sid: bool 陣列（對齊 G["dates"]）}
     python msci_growth.py  印今天的分類與歷年成長股檔數。"""
import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import ROOT
from yield_study import REPORT_DEADLINE

UNI = ROOT / "data" / "universe"


def _known(q):
    return pd.Timestamp(q.year + (q.month == 12), *REPORT_DEADLINE[q.month])


def _trend(vals):
    """回歸斜率 ÷ 平均絕對值（MSCI 的「長期歷史成長趨勢」定義）；至少 3 點。"""
    v = np.asarray(vals, float)
    v = v[~np.isnan(v)]
    if len(v) < 3 or np.mean(np.abs(v)) == 0:
        return np.nan
    x = np.arange(len(v))
    slope = np.polyfit(x, v, 1)[0]
    return slope / np.mean(np.abs(v))


def _series(sid, eps_all, fin, div):
    """每個財報公布日的五個原始變數（還沒除以價格的先存分子）。回傳 DataFrame(index=公布日)。"""
    e = ps.eps_table(eps_all, sid)
    r = fin[(fin["stock_id"] == sid) & (fin["type"] == "Revenue")][["date", "value"]].copy()
    r["date"] = pd.to_datetime(r["date"]); r = r.sort_values("date").drop_duplicates("date")
    r["fy"] = r["date"].dt.year; r["published"] = pd.to_datetime([_known(q) for q in r["date"]])
    dv = div[div["stock_id"] == sid].copy()
    dv["ex"] = pd.to_datetime(dv["CashExDividendTradingDate"], errors="coerce")
    dv["cash"] = pd.to_numeric(dv["CashEarningsDistribution"], errors="coerce").fillna(0) + pd.to_numeric(dv["CashStatutorySurplus"], errors="coerce").fillna(0)
    dv = dv.dropna(subset=["ex"]).sort_values("ex")
    rows = []
    for _, row in e.iterrows():
        pub = row["published"]
        known_e = e[e["published"] <= pub]
        ttm = known_e["eps"].iloc[-4:].sum() if len(known_e) >= 4 else np.nan
        prev = known_e["eps"].iloc[-8:-4].sum() if len(known_e) >= 8 else np.nan
        st = ttm / abs(prev) - 1 if not np.isnan(prev) and prev != 0 else np.nan
        fy_e = known_e.groupby("fy")["eps"].agg(["sum", "count"])
        fy_e = fy_e[fy_e["count"] == 4]["sum"].iloc[-5:]
        known_r = r[r["published"] <= pub]
        fy_r = known_r.groupby("fy")["value"].agg(["sum", "count"])
        fy_r = fy_r[fy_r["count"] == 4]["sum"].iloc[-5:]
        d12 = dv[(dv["ex"] <= pub) & (dv["ex"] > pub - pd.Timedelta(days=365))]["cash"].sum()
        rows.append(dict(published=pub, eps_trend=_trend(fy_e.values), rev_trend=_trend(fy_r.values), st_growth=st, ttm_eps=ttm, div12=d12))
    if not rows:      # 沒有 EPS 紀錄的股票（例如 2017 前下市）
        return pd.DataFrame(columns=["eps_trend", "rev_trend", "st_growth", "ttm_eps", "div12"], index=pd.DatetimeIndex([], name="published"))
    return pd.DataFrame(rows).drop_duplicates("published", keep="last").set_index("published").sort_index()


def msci_flags(G, buffer=0.0, detail=False):
    """{sid: bool 陣列}：成長分數 − 價值分數 > buffer。detail=True 另回傳每檔每個評分日的分數表。"""
    dates = G["dates"]
    eps_all = pd.read_csv(UNI / "eps_all.csv", dtype={"stock_id": str})
    fin = pd.read_csv(UNI / "financials_all.csv", dtype={"stock_id": str})
    div = pd.read_csv(UNI / "dividend_all.csv", dtype={"stock_id": str})
    raw = {sid: _series(sid, eps_all, fin, div) for sid in G["sub"]}
    pubs = sorted(set(pd.concat([s.index.to_series() for s in raw.values()])))
    pubs = [p_ for p_ in pubs if p_ >= dates[0] - pd.Timedelta(days=400)]
    score = {sid: pd.Series(np.nan, index=pubs) for sid in G["sub"]}
    tables = []
    for pub in pubs:
        pos = dates.searchsorted(pub)
        if pos >= len(dates):
            break
        rows = {}
        for sid, s in raw.items():
            if not len(s):
                continue
            k = s[s.index <= pub]
            if not len(k):
                continue
            last = k.iloc[-1]
            px = G["sub"][sid]["close_ff"][pos]
            if np.isnan(px) or px <= 0:
                continue
            rows[sid] = dict(eps_trend=last["eps_trend"], rev_trend=last["rev_trend"], st_growth=last["st_growth"],
                             ep=last["ttm_eps"] / px if not np.isnan(last["ttm_eps"]) else np.nan, dp=last["div12"] / px)
        t = pd.DataFrame(rows).T
        if len(t) < 5:
            continue
        z = (t - t.mean()) / t.std(ddof=0)
        z = z.clip(-3, 3)
        g = z[["eps_trend", "rev_trend", "st_growth"]].mean(axis=1, skipna=True)
        v = z[["ep", "dp"]].mean(axis=1, skipna=True)
        t["growth_score"], t["value_score"] = g, v
        t["date"] = pub
        tables.append(t)
        for sid in t.index:
            score[sid][pub] = g[sid] - v[sid]
    flags = {}
    for sid in G["sub"]:
        s = score[sid].dropna()
        daily = s.reindex(dates, method="ffill") if len(s) else pd.Series(np.nan, index=dates)
        flags[sid] = (daily > buffer).fillna(False).values
    if detail:
        return flags, pd.concat(tables)
    return flags


if __name__ == "__main__":
    import param_opt as po
    import robust_study as rs
    from rules_live import FINAL
    po.setup(live=True); G = rs.G; d = G["dates"]; po.apply(FINAL)
    flags, tab = msci_flags(G, detail=True)
    names = pd.read_csv(UNI / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]
    last = tab[tab["date"] == tab["date"].max()].sort_values("growth_score", ascending=False)
    last["名稱"] = [names.get(s, "") for s in last.index]
    last["MSCI成長"] = last["growth_score"] - last["value_score"] > 0
    last["原定義成長"] = [bool(G["sub"][s]["growth_flag"][-1]) for s in last.index]
    last["殖利率中位"] = [round(float(G["sub"][s]["own_median"][-1]), 2) for s in last.index]
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True, "display.max_rows", 100):
        print(f"最近評分日 {tab['date'].max().date()}")
        print(last[["名稱", "eps_trend", "rev_trend", "st_growth", "ep", "dp", "growth_score", "value_score", "MSCI成長", "原定義成長", "殖利率中位"]].round(2).to_string())
    f = pd.DataFrame(flags, index=d); o = pd.DataFrame({s: G["sub"][s]["growth_flag"] for s in G["sub"]}, index=d)
    print("每年年底成長股檔數（MSCI／原定義／兩者都是）：")
    ye = f.groupby(f.index.year).last(); yo = o.groupby(o.index.year).last()
    print(pd.DataFrame({"MSCI": ye.sum(axis=1), "原定義": yo.sum(axis=1), "交集": (ye & yo).sum(axis=1)}).to_string())
