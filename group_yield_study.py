"""成長股第二類規則（2026-11-03 使用者「成長股改用所有成長股平均殖利率中值 ×K」＋更正「偏低股照正常方式」）。
正式版：長期殖利率偏低股（3 年殖利率中位 <4%）用「殖利率 ≥ 自己中位 ×1.25」買、「≥ 自己中位」續抱——**不動**。
新增第二類：MSCI 近似版判定的成長股（msci_growth.py），**不是偏低股的**改用「殖利率 ≥ 當天所有成長股殖利率中位 ×K」買；
續抱維持一般 4.75%，另測「≥ 群體中位 ×1.0」續抱。其餘股票照一般門檻 max(市場中位, 5%)。K 掃 1.0／1.25／1.5。
（第一版曾把偏低股本身改成群體中位 ×K：三段 −6～−10、σ +1.1～1.4，使用者隨即更正為本版；結果留在 results/group_yield_v1_summary.md）
用法：python group_yield_study.py　輸出：results/group_yield_eval.csv、group_yield_money.csv、group_yield_summary.md"""
import numpy as np
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

BASE_NAME = "正式版（偏低股 自己中位×1.25）"
V = {BASE_NAME: rr.BASE}
for k in (1.0, 1.25, 1.5):
    V[f"＋成長股 群體中位×{k}"] = {**rr.BASE, "growth_second": ("msci", k, None)}
V["＋成長股 群體中位×1.25，續抱群體中位×1.0"] = {**rr.BASE, "growth_second": ("msci", 1.25, 1.0)}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.GROWTH_FLAGS["msci"] = msci_flags(G)
    F = po.GROWTH_FLAGS["msci"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        if i == 0:
            low = {s: G["sub"][s]["growth_flag"].copy() for s in G["sub"]}
            gm = np.nanmedian(np.array([np.where(F[s], G["sub"][s]["yield"], np.nan) for s in G["sub"]]), axis=0)
            gs = pd.Series(gm, index=dates)
            print("當日成長股群體殖利率中位數每年年底：", gs.groupby(gs.index.year).last().round(2).to_dict(), flush=True)
            n2 = pd.DataFrame({s: F[s] & ~low[s] for s in G["sub"]}, index=dates).sum(axis=1)
            print("「成長股但非偏低股」每年年底檔數：", n2.groupby(n2.index.year).last().to_dict(), flush=True)
        m = po.evaluate([name], f"gy_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("gy_0", f"gy_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
            tr.to_csv(RESULTS / f"group_yield_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f} 筆數 {money[(name, '2016-12-28')]['筆數']}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "group_yield_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "group_yield_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_gy_*"):
        f.unlink()
    b = res[BASE_NAME]
    lines = ["# 成長股第二類：MSCI 成長股（非偏低股）用群體殖利率中位 ×K（group_yield_study.py）", "", "紅線：σ ≤+0.15 且前 7 年配對 ≥14/20。", "",
             "| 版本 | 筆數 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} |")
    (RESULTS / "group_yield_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
