"""同一產業最多佔 k 個名額（HANDOFF 第 9 節，2026-11-02 使用者待辦）。
依據 results/timing_report.md：同產業買點同步度 0.18～0.39 高於跨產業，同時出現買點時會擠在同一產業。
產業＝證交所產業別（data/universe/industry_twse_elec.csv）；47 檔池只有半導體業、電腦及週邊設備業兩類，
所以 ≤2 等於最多只用 4 個名額，≤3 是「3＋2」，≤4 是「4＋1」。只算佔名額的部位（套牢、被剔除的不算）。
用法：python ind_cap_study.py　輸出：results/ind_cap_eval.csv、results/ind_cap_money.csv"""
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

IND = pd.read_csv(ps.UNI / "industry_twse_elec.csv", dtype=str).set_index("stock_id")["industry"].to_dict()
VARIANTS = {"正式版": dr.FINAL}
for k in (2, 3, 4):
    VARIANTS[f"同產業 ≤{k}"] = {**dr.FINAL, "ind_cap": {"cap": k, "ind": IND}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    print("池內產業：", pd.Series([IND.get(s) for s in G["sub"]]).value_counts().to_dict(), flush=True)
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(VARIANTS.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"ic_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("ic_0", f"ic_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
            tr.to_csv(RESULTS / f"ind_cap_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "ind_cap_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "ind_cap_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_ic_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
