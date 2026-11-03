"""成長股改用 MSCI 近似判定（2026-11-03 使用者「使用 MSCI 的規則判斷成長股」；判定見 msci_growth.py）。
正式版的「成長股」＝過去 3 年殖利率中位數 < 4%，成長股改用「殖利率 ≥ 自己中位 ×1.25」買、「≥ 自己中位」續抱。
這裡只換「誰是成長股」，買賣規則不動；三版：取代（只用 MSCI）、交集（兩者都要）、聯集（任一）。
用法：python msci_growth_study.py　輸出：results/msci_growth_eval.csv、msci_growth_money.csv、msci_growth_summary.md"""
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


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.GROWTH_FLAGS["msci"] = msci_flags(G)
    V = {"正式版（殖利率中位<4%）": rr.BASE,
         "MSCI 取代": {**rr.BASE, "growth_flag": ("msci", "replace")},
         "交集（中位<4% 且 MSCI）": {**rr.BASE, "growth_flag": ("msci", "and")},
         "聯集（中位<4% 或 MSCI）": {**rr.BASE, "growth_flag": ("msci", "or")}}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        n_g = int(sum(G["sub"][s]["growth_flag"].sum() for s in G["sub"]))
        m = po.evaluate([name], f"mg_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("mg_0", f"mg_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 成長股檔日=n_g)
            tr.to_csv(RESULTS / f"msci_growth_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f} 筆數 {money[(name, '2016-12-28')]['筆數']}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "msci_growth_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "msci_growth_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_mg_*"):
        f.unlink()
    b = res["正式版（殖利率中位<4%）"]
    lines = ["# 成長股改用 MSCI 近似判定（msci_growth_study.py）", "", "紅線：σ ≤+0.15 且前 7 年配對 ≥14/20。", "",
             "| 版本 | 筆數 | 成長股檔日 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {a['成長股檔日']:,} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} |")
    (RESULTS / "msci_growth_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
