"""股票池納入 0051（中型 100）、0052（富邦科技）成分股會怎樣（2026-11-01 使用者要求）。
正式版規則（E＋D＋U1）不變，只換「可買的股票」：
  P0 現行：0050／0056 歷年成分股中的電子股（ELECTRONICS 75 檔）
  P1 P0 ＋ 0052 成分股（富邦科技＝台灣資訊科技指數，全部是科技股）
  P2 P0 ＋ 0052 ＋ 0051 成分股中的科技股（代理分類：曾是 0052 成分股或在 ELECTRONICS 名單；0051 沒有產業分類資料，會漏掉部分電子股）
  P3 P0 ＋ 0052 ＋ 0051 全部成分股（含金融、傳產）
成分股資格仍是「當天在該 ETF 名單內」；買進門檻的市場中位數維持「0050＋0056 全部成分股」的定義。
期間：過去 10 年（2016-11-01 起）、20 年（2006-11-01 起）；條件：500 萬＋每月 10 萬、1,000 萬＋每月 5 萬。
資料：results/portfolio_prepared_2006_all.pkl（含四檔 ETF 所有成分股的 2006 起快取）。
輸出 results/pool_expand.csv"""
import pickle
import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import ELECTRONICS
from yield_entry_study import entries

START = pd.Timestamp("2006-01-01")
PKL = RESULTS / "portfolio_prepared_2006_all.pkl"
SIGS = RESULTS / "param_opt_sigs_2006_all.pkl"
HORIZONS = {"過去10年": "2016-11-01", "過去20年": "2006-11-01"}
CONDS = ((5_000_000, 100_000), (10_000_000, 50_000))


def load():
    cons = {e: pd.read_csv(ps.UNI / f, dtype={"stock_id": str, "etf": str}) for e, f in
            (("0050", "constituents.csv"), ("0051", "constituents_0051.csv"), ("0052", "constituents_0052.csv"))}
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= START - pd.Timedelta(days=5)]).sort_values()
    data, _ = pickle.loads(PKL.read_bytes())
    ps.attach_fundamentals(data, dates)
    if SIGS.exists():
        sig = pickle.loads(SIGS.read_bytes())
    else:
        sig = {k: {} for k in po.ENTRIES.values()}
        for sid in data:
            df, _ = ps.load_prices(sid)
            e, _ = entries(df)
            for k in sig:
                sig[k][sid] = e[k].reindex(dates).fillna(False).astype(bool).values
        SIGS.write_bytes(pickle.dumps(sig))
    # 市場中位數：0050＋0056 全部成分股（定義不變）
    mem_all = ps.membership(cons["0050"], dates)
    Y = pd.DataFrame({s: np.where(mem_all[s].values, data[s]["yield"][:len(dates)], np.nan) for s in data if s in mem_all}, index=dates)
    po._mk[("all", len(dates))] = (Y.median(axis=1).values, Y.std(axis=1).values, Y.notna().sum(axis=1).values)
    return cons, dates, data, sig


ELEC_CATS = {"半導體業", "電腦及週邊設備業", "光電業", "通信網路業", "電子零組件業", "電子通路業", "資訊服務業", "其他電子業", "電子工業"}
EXCL = {"2412", "3045", "4904", "2059"}          # 電信三雄、川湖（與現行名單一致）
MANUAL_ELEC = {"2394", "3012"}                   # 普立爾、廣輝：早期併購下市，FinMind 查不到分類，依名稱歸電子


def electronics_ids():
    """FinMind TaiwanStockInfo 的產業分類（data/universe/industry_finmind.csv，2026-11-01 抓）→ 屬於證交所電子工業八類的代號。"""
    ind = pd.read_csv(ps.UNI / "industry_finmind.csv", dtype=str).set_index("stock_id")["industry_category"]
    return (set(ind[ind.isin(ELEC_CATS)].index) | MANUAL_ELEC) - EXCL


def pools_elec(cons):
    """全部用產業分類挑電子股：E0 0050/0056 電子工業、E1 ＋0052 電子、E2 ＋0051 電子。"""
    el = electronics_ids()
    f = lambda c: c[c["stock_id"].isin(el)]
    base75 = cons["0050"][cons["0050"]["stock_id"].isin(ELECTRONICS)]
    e0 = f(cons["0050"])
    return {"P0 現行 75 檔（對照）": base75,
            "E0 0050/0056 電子工業（分類法）": e0,
            "E1 E0＋0052 電子": pd.concat([e0, f(cons["0052"])]),
            "E2 E1＋0051 電子": pd.concat([e0, f(cons["0052"]), f(cons["0051"])])}


def pools(cons):
    base = cons["0050"][cons["0050"]["stock_id"].isin(ELECTRONICS)]
    c52 = cons["0052"]
    tech = set(c52["stock_id"]) | set(ELECTRONICS)
    c51_tech = cons["0051"][cons["0051"]["stock_id"].isin(tech)]
    return {"P0 現行 0050/0056 電子股": base,
            "P1 ＋0052": pd.concat([base, c52]),
            "P2 ＋0052＋0051 科技股（代理分類）": pd.concat([base, c52, c51_tech]),
            "P3 ＋0052＋0051 全部": pd.concat([base, c52, cons["0051"]])}


def setup_pool(con_df, dates, data, sig):
    member = ps.membership(con_df, dates)
    G = rs.G; G.clear()
    G.update(dates=dates, member=member, sub={k: v for k, v in data.items() if k in member}, sig=sig, zone={},
             etf={e: ps.load_prices(e)[0]["close"].reindex(dates).ffill() for e in ("0050", "0056")})
    po._applied.clear()
    po.apply(dr.FINAL)
    return G


def main(elec=False):
    cons, dates, data, sig = load(); d = dates
    kw = None
    rows = []
    for pname, con_df in (pools_elec(cons) if elec else pools(cons)).items():
        G = setup_pool(con_df, dates, data, sig); kw = po.to_kw(dr.FINAL)
        n_stocks = len(G["sub"])
        for hname, hstart in HORIZONS.items():
            s = d.get_indexer([pd.Timestamp(hstart)], method="bfill")[0]
            sub = d[s + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
            for cap, monthly in CONDS:
                contrib = {i: monthly / cap for i in midx}
                flows = [cap] + [monthly] * len(midx); fdates = [d[s]] + [d[i] for i in midx]
                total_in = cap + monthly * len(midx)
                tr, eq = ps.run(G["sub"], G["member"], d, capital=cap, contributions=contrib, start_n=s, **kw)
                end = eq.iloc[-1] * cap
                top = tr.assign(獲利=tr["回收"].fillna(tr.get("市值", np.nan)) - tr["投入"]).groupby("代號")["獲利"].sum().sort_values(ascending=False)
                rows.append(dict(股票池=pname, 檔數=n_stocks, 期間=hname, 起始萬=cap / 1e4, 每月萬=monthly / 1e4, 總投入萬=round(total_in / 1e4),
                                 期末萬=round(end / 1e4), 淨獲利萬=round((end - total_in) / 1e4), IRR=round(irr(flows, fdates, end, d[-1]), 1),
                                 最大回撤=round(oos.nav_dd(eq, contrib), 1), 筆數=len(tr), 勝率=round((tr["報酬%"] > 0).mean() * 100) if len(tr) else None,
                                 資金使用率=round(eq.attrs["資金使用率%"]),
                                 新池貢獻萬=round(top[[i for i in top.index if i not in ELECTRONICS]].sum() * cap / 1e4) if len(top) else 0,
                                 前三名=", ".join(f"{i}" for i in top.index[:3])))
        print(f"  {pname}（{n_stocks} 檔）完成", flush=True)
    R = pd.DataFrame(rows); R.to_csv(RESULTS / ("pool_expand_elec.csv" if elec else "pool_expand.csv"), index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.max_columns", 40, "display.unicode.east_asian_width", True):
        print(R.to_string(index=False))


if __name__ == "__main__":
    import sys
    main(elec="--elec" in sys.argv)
