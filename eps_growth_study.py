"""成長股改用「預估 EPS × 0.5 ÷ 股價」當殖利率、門檻 2%／2.5%（2026-11-03 使用者）。
意思：成長股配息率假設五成，近四季 EPS × 0.5 ÷ 收盤 ≥ 2% ⇔ 本益比 ≤ 25；≥ 2.5% ⇔ 本益比 ≤ 20。等於給成長股一條本益比買法。
成長股判定用 MSCI 近似版（msci_growth.py）；兩種範圍：只套用在不是偏低股的成長股（偏低股照舊），以及所有成長股（偏低股也改）。
續抱：預設一般 4.75%（買進後殖利率一定 <4.75，賺 12% 就停利）；另測續抱也用同一條（EPS 殖利率 ≥ 2%，即本益比 ≤ 25 就續抱）。
引擎：growth_relative(second=(flag, k, k_hold, "eps", scope, payout))，資料 d["eps_ttm"]（attach_fundamentals）。
用法：python eps_growth_study.py　輸出：results/eps_growth_eval.csv、eps_growth_money.csv、eps_growth_summary.md"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from msci_growth import msci_flags
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

B = rr.BASE
V = {"正式版": B,
     "成長股（非偏低股）EPS×0.5 殖利率≥2%（PE≤25）": {**B, "growth_second": ("msci", 2.0, None, "eps", "nonlow", 0.5)},
     "成長股（非偏低股）EPS×0.5 殖利率≥2.5%（PE≤20）": {**B, "growth_second": ("msci", 2.5, None, "eps", "nonlow", 0.5)},
     "成長股（非偏低股）≥2%，續抱也≥2%": {**B, "growth_second": ("msci", 2.0, 2.0, "eps", "nonlow", 0.5)},
     "所有成長股（含偏低股）EPS×0.5 殖利率≥2%": {**B, "growth_second": ("msci", 2.0, None, "eps", "all", 0.5)},
     "所有成長股（含偏低股）EPS×0.5 殖利率≥2.5%": {**B, "growth_second": ("msci", 2.5, None, "eps", "all", 0.5)}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.GROWTH_FLAGS["msci"] = msci_flags(G)
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"eg_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("eg_0", f"eg_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
            tr.to_csv(RESULTS / f"eps_growth_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f} 筆數 {money[(name, '2016-12-28')]['筆數']}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "eps_growth_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "eps_growth_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_eg_*"):
        f.unlink()
    b = res["正式版"]
    lines = ["# 成長股用 EPS×0.5 當殖利率、門檻 2%／2.5%（eps_growth_study.py）", "", "紅線：σ ≤+0.15 且前 7 年配對 ≥14/20。", "",
             "| 版本 | 筆數 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} |")
    (RESULTS / "eps_growth_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
