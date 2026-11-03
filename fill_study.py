"""成交價：訊號日收盤 vs 隔天開盤（2026-11-03 使用者「回測一下當天收盤價買比較好還是隔天開盤價」）。
正式版：訊號以收盤判定、隔天開盤成交。這裡測：首買改用訊號日收盤（尾盤看到訊號就買；加碼、賣出仍隔天開盤）、
以及所有買賣都用訊號日收盤（引擎 fill_close="buy"/"all"）。注意：收盤價成交在實務上要在收盤前幾分鐘判定訊號，指標用的是未定收盤，
所以「收盤版」是上限，不是真的做得到的數字。
用法：python fill_study.py　輸出：results/fill_eval.csv、fill_money.csv、fill_summary.md"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

V = {"正式版（隔天開盤）": rr.BASE,
     "首買用訊號日收盤": {**rr.BASE, "fill_close": "buy"},
     "所有買賣用訊號日收盤": {**rr.BASE, "fill_close": "all"}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"fl_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("fl_0", f"fl_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "fill_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "fill_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_fl_*"):
        f.unlink()
    b = res["正式版（隔天開盤）"]
    lines = ["# 成交價：訊號日收盤 vs 隔天開盤（fill_study.py）", "", "| 版本 | 筆數 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} |")
    (RESULTS / "fill_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
