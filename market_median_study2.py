"""接續 market_median_study：買進門檻＝中位數＋0.5σ，續抱＝中位數（k=0），以及鄰近組合。"""
import pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
import market_median_study as mm
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    C = {"正式版（固定 5% / 4.75%）": {}}
    for un, ul in (("全成分股", "all"), ("電子股池", "elec")):
        for bk in (0.25, 0.5):
            for hk in (0.0, 0.25, 0.5):
                C[f"{un}中位數＋{bk}σ買／中位數−{hk}σ續抱"] = {"mkt": (ul, bk, hk, None)}
        C[f"{un}中位數＋0.5σ買／固定4.75%續抱"] = {"mkt": (ul, 0.5, None, None), "hold_fixed": True}
        C[f"{un}中位數＋0.5σ買(至少5%)／中位數續抱"] = {"mkt": (ul, 0.5, 0.0, 5.0)}
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**dr.FINAL, **x}; names.append(n)
    def to_kw3(cfg):
        kw = mm.to_kw2(cfg)
        if cfg.get("hold_fixed"):
            kw["hold_yield"] = 4.75
        return {k: v for k, v in kw.items() if k != "hold_fixed"}
    def apply3(cfg):
        if cfg.get("hold_fixed"):
            cfg = {**cfg, "mkt": (cfg["mkt"][0], cfg["mkt"][1], 0.0, cfg["mkt"][3])}
        mm.apply2({k: v for k, v in cfg.items() if k != "hold_fixed"})
    po.apply, po.to_kw = apply3, to_kw3
    m = po.evaluate(names, "mktmedian2")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw); cl = tr[tr["出場"].notna()]
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                        平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 全池買訊日數=sum(int(d["buy"].sum()) for d in G["sub"].values()),
                        期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "market_median2_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2017 起不追加】"); print(M.to_string(index=False))

if __name__ == "__main__":
    main()
