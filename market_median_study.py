"""市場相對版：買進門檻＝「當天所有 0050＋0056 成分股（含非電子，149 檔）預估殖利率的中位數」，
續抱門檻＝「中位數 − k × 當天橫斷面標準差」（使用者指定 k=0.08，另測 0.5、1.0）。
每天只用當天資料，無前視。對照正式版（固定 5% / 4.75%）。用法：python market_median_study.py"""
import pickle
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

_mk = {}

def market_stats(universe):
    """每日橫斷面中位數／標準差。universe: 'all'＝149 檔成分股、'elec'＝電子股池。"""
    if universe in _mk:
        return _mk[universe]
    dates = rs.G["dates"]
    if universe == "all":
        data, _ = pickle.loads(ps.PREPARED.read_bytes())
        cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
        mem = ps.membership(cons, dates)
        Y = pd.DataFrame({s: np.where(mem[s].values, data[s]["yield"], np.nan) for s in data if s in mem}, index=dates)
    else:
        mem = rs.G["member"]
        Y = pd.DataFrame({s: np.where(mem[s].values, d["yield"], np.nan) for s, d in rs.G["sub"].items()}, index=dates)
    _mk[universe] = (Y.median(axis=1).values, Y.std(axis=1).values, Y.notna().sum(axis=1).values)
    return _mk[universe]

_orig_apply = po.apply
def apply2(cfg):
    _orig_apply(cfg)
    rel = cfg.get("mkt")
    if not rel:
        return
    universe, buy_k, hold_k, floor = rel
    med, sd, _ = market_stats(universe)
    thr_buy = med + buy_k * sd
    if floor:
        thr_buy = np.fmax(thr_buy, floor)
    hy = med - hold_k * sd
    sig = rs.G["sig"]["任一"]
    for sid, d in rs.G["sub"].items():
        y = np.nan_to_num(d["yield"], nan=-1)
        d["buy"] = sig[sid] & ~np.isnan(thr_buy) & (y >= thr_buy)
        d["hy_rel"] = hy
    po._applied["buy"] = None
_orig_to_kw = po.to_kw
def to_kw2(cfg):
    kw = _orig_to_kw({k: v for k, v in cfg.items() if k != "mkt"})
    if cfg.get("mkt"):
        kw["hold_yield"] = "hy_rel"
    return kw

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    med, sd, cnt = market_stats("all")
    S = pd.DataFrame({"中位數": med, "標準差": sd, "檔數": cnt}, index=dates)
    yr = S.groupby(S.index.year).agg(中位數=("中位數", "median"), 中位數最低=("中位數", "min"), 中位數最高=("中位數", "max"), 標準差=("標準差", "median"), 檔數=("檔數", "median"))
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【全成分股預估殖利率的橫斷面中位數，每年】"); print(yr.round(2).to_string())
    C = {"正式版（固定 5% / 4.75%）": {}}
    for un, ul in (("全成分股", "all"), ("電子股池", "elec")):
        C[f"{un}中位數買／中位數−0.08σ續抱"] = {"mkt": (ul, 0.0, 0.08, None)}
        C[f"{un}中位數買／中位數−0.5σ續抱"] = {"mkt": (ul, 0.0, 0.5, None)}
        C[f"{un}中位數買／中位數−1σ續抱"] = {"mkt": (ul, 0.0, 1.0, None)}
        C[f"{un}中位數＋0.5σ買／中位數−0.08σ續抱"] = {"mkt": (ul, 0.5, 0.08, None)}
        C[f"{un}中位數＋1σ買／中位數−0.08σ續抱"] = {"mkt": (ul, 1.0, 0.08, None)}
        C[f"{un}中位數買(至少5%)／中位數−0.08σ續抱"] = {"mkt": (ul, 0.0, 0.08, 5.0)}
        C[f"{un}中位數買(至少5%)／固定4.75%續抱"] = {"mkt_buy_only": (ul, 0.0, 5.0)}
    names = []
    for n, x in C.items():
        cfg = {**dr.FINAL, **x}
        if "mkt_buy_only" in x:   # 只改買進門檻，續抱維持固定 4.75%
            ul, k, fl = x.pop("mkt_buy_only"); cfg = {**dr.FINAL, "mkt": (ul, k, None, fl), "hold_fixed": True}
        po.CONFIGS[n] = cfg; names.append(n)
    # hold_fixed：to_kw 不把 hold_yield 換成陣列
    def to_kw3(cfg):
        kw = to_kw2(cfg)
        if cfg.get("hold_fixed"):
            kw["hold_yield"] = 4.75
        return {k: v for k, v in kw.items() if k != "hold_fixed"}
    po.to_kw = to_kw3
    def apply3(cfg):
        if cfg.get("hold_fixed"):
            cfg = {**cfg, "mkt": (cfg["mkt"][0], cfg["mkt"][1], 0.0, cfg["mkt"][3])}
        apply2({k: v for k, v in cfg.items() if k != "hold_fixed"})
    po.apply = apply3
    m = po.evaluate(names, "mktmedian")
    print("\n【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw)
        cl = tr[tr["出場"].notna()]
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                        平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 全池買訊日數=sum(int(d["buy"].sum()) for d in G["sub"].values()),
                        期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "market_median_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2017 起不追加】"); print(M.to_string(index=False))

if __name__ == "__main__":
    main()
