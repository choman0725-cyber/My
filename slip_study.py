"""滑價影響（2026-11-03 使用者同意的測試方法補強第 4 項）：正式版加 run(slip=…)，買、賣成交價各比開盤差 0.1%／0.3%／0.5%，
看三段平均、最差 10%、σ 與 500 萬兩個起跑日掉多少。不是要改規則（正式版 slip 仍為 0），是要知道「實際比回測少賺多少」。
用法：python slip_study.py　輸出：results/slip_eval.csv、slip_money.csv、slip_summary.md"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

SLIPS = (0.001, 0.003, 0.005)
VARIANTS = {"正式版（無滑價）": rr.BASE, **{f"滑價 {s:.1%}": {**rr.BASE, "slip": s} for s in SLIPS}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(VARIANTS.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"sl_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("sl_0", f"sl_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "slip_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "slip_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_sl_*"):
        f.unlink()
    lines = ["# 滑價影響（slip_study.py）", "", "| 版本 | 三段平均 | 最差 10% | σ | 前 7 年配對 | 500 萬 12-28 | 500 萬 01-03 |", "|---|---|---|---|---|---|---|"]
    for name in VARIANTS:
        m = out.loc[name]
        lines.append(f"| {name} | {m['三段平均']:.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m.get('前7年配對', '—')} | "
                     f"{money[(name, '2016-12-28')]['期末萬']:,}（IRR {money[(name, '2016-12-28')]['IRR']}） | {money[(name, '2017-01-03')]['期末萬']:,}（IRR {money[(name, '2017-01-03')]['IRR']}） |")
    (RESULTS / "slip_summary.md").write_text("\n".join(lines), encoding="utf-8")
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
