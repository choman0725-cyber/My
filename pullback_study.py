"""「已經漲了但回撤了」的相對便宜（2026-11-03 使用者：高殖利率股轉成長股後，殖利率法要等 3 年中位切換才抓得到；
想個方法讓它回撤時能被找出來相對便宜）。
兩個方向，都只用殖利率、不用 MSCI：
  A 縮短身分切換窗口：偏低股判定改用 1 年（250 日）／2 年（500 日）殖利率中位數（正式版 750 日；5 年測過較差）
  B 回撤規則（引擎 pullback=(N, k_buy, k_hold, low)）：不是偏低股、但近 N 日殖利率最低值 < low（最近曾被市場用低殖利率定價＝已重新評價），
    加一條買法「殖利率 ≥ 近 N 日最低殖利率 × k_buy」——股利不變時等於股價從最貴點回撤 1−1/k_buy（1.25＝回撤 20%、1.5＝回撤 33%）；
    續抱改「≥ 近 N 日最低 × k_hold」（1.1＝回到離最貴只剩 10% 就可停利）。一般門檻買法保留。
用法：python pullback_study.py　輸出：results/pullback_eval.csv、pullback_money.csv、pullback_summary.md"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

B = rr.BASE
V = {"正式版（3 年中位）": B,
     "A1 偏低股判定改 1 年中位": {**B, "growth_rel": (1.25, 4.0, 250)},
     "A2 偏低股判定改 2 年中位": {**B, "growth_rel": (1.25, 4.0, 500)},
     "B1 回撤 N=250 ×1.25（回撤 20%）續抱×1.1": {**B, "pullback": (250, 1.25, 1.1, 4.0)},
     "B2 回撤 N=250 ×1.5（回撤 33%）續抱×1.1": {**B, "pullback": (250, 1.5, 1.1, 4.0)},
     "B3 回撤 N=120 ×1.25 續抱×1.1": {**B, "pullback": (120, 1.25, 1.1, 4.0)},
     "B4 回撤 N=250 ×1.25 續抱不改（4.75%）": {**B, "pullback": (250, 1.25, None, 4.0)}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"pb_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("pb_0", f"pb_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
            tr.to_csv(RESULTS / f"pullback_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f} 筆數 {money[(name, '2016-12-28')]['筆數']}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "pullback_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "pullback_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_pb_*"):
        f.unlink()
    b = res["正式版（3 年中位）"]
    lines = ["# 已漲但回撤的相對便宜（pullback_study.py）", "", "紅線：σ ≤+0.15 且前 7 年配對 ≥14/20。", "",
             "| 版本 | 筆數 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} |")
    (RESULTS / "pullback_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
