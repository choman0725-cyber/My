"""周轉研究的 20 年驗證（2026-11-03 使用者：「7 年驗證完再驗證後面三年，最後 20 年全部驗證」）。
資料：long_history.setup()（2006 起快取；殖利率要 4 季 EPS、5 年賺錢濾網要 1 年已知，所以最早買點約 2007）。
每個版本：①2007-01 起跑到回測截止日的期末倍數／IRR／筆數／回撤；②2007～2016 每年 1 月起跑，算到 2016 年底的 IRR（10 條、完全在 2017 樣本之外）
與算到今天的 IRR；③與正式版逐條配對（好／平／差，差 ≥0.5 個百分點才算）。
用法：python turnover_long.py A2 B1 E11 G1 …（版本名開頭；不給＝正式版＋全部）　輸出：results/turnover_long_*.csv、turnover_long_summary.md"""
import sys

import numpy as np
import pandas as pd

import long_history as lh
import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
import turnover_study as ts
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL


def main():
    want = [a for a in sys.argv[1:]]
    H = lh.setup(); d = H["dates"]
    raw, counts = ts.build_signals(H)
    V = ts.variants(H, raw)
    V = {k: v for k, v in V.items() if k == "正式版" or not want or any(k.startswith(w) for w in want)}
    e16 = d.get_indexer([pd.Timestamp("2016-12-30")], method="ffill")[0]
    full, hist = {}, []
    for name, cfg in V.items():
        po._applied.clear(); po.CONFIGS[name] = cfg; po.apply(cfg); kw = po.to_kw(cfg)
        sp = rs.SPLITS.get(cfg.get("split", "不分區"))
        extra = {"slot_split": sp} if isinstance(sp, dict) else {}
        for y in range(2007, 2017):
            s = d.get_indexer([pd.Timestamp(y, 1, 1)], method="bfill")[0]
            tr, eq = ps.run(H["sub"], H["member"], d, capital=CAPITAL, start_n=s, **kw, **extra)
            q16 = eq.loc[:d[e16]]
            row = dict(版本=name, 起跑=y, 至2016年底IRR=round(irr([CAPITAL], [d[s]], q16.iloc[-1] / q16.iloc[0] * CAPITAL, d[e16]), 2) if y < 2016 else np.nan,
                       至今IRR=round(irr([CAPITAL], [d[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, d[-1]), 2),
                       筆數至2016=int((pd.to_datetime(tr["進場"]) <= d[e16]).sum()), 筆數至今=len(tr),
                       回撤=round(100 * (eq / eq.cummax() - 1).min(), 1))
            hist.append(row)
            if y == 2007:
                full[name] = dict(期末倍數=round(float(eq.iloc[-1] / eq.iloc[0]), 2), IRR=row["至今IRR"], 筆數=len(tr), 回撤=row["回撤"],
                                  筆數至2016=row["筆數至2016"], 至2016年底IRR=row["至2016年底IRR"])
            tr.to_csv(RESULTS / f"turnover_long_trades_{name[:3].strip()}_{y}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：2007 起 {full[name]}", flush=True)
    hist = pd.DataFrame(hist)
    hist.to_csv(RESULTS / "turnover_long_hist.csv", index=False, encoding="utf-8-sig")
    base = hist[hist["版本"] == "正式版"].set_index("起跑")
    lines = ["# 周轉研究 20 年驗證（turnover_long.py，2007～2026，正式版股票池 47 檔）", "",
             "| 版本 | 2007 起 期末倍數 | IRR | 筆數 | 回撤 | 2007-16 每年起跑·至 2016 底 IRR 平均 | vs 正式版 好/平/差 | 至今 IRR 平均 | vs 正式版 好/平/差 | 筆數至 2016 平均 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        h = hist[hist["版本"] == name].set_index("起跑"); f = full[name]
        d16 = (h["至2016年底IRR"] - base["至2016年底IRR"]).dropna(); dn = h["至今IRR"] - base["至今IRR"]
        pair = lambda x: f"{int((x > 0.5).sum())}/{int((x.abs() <= 0.5).sum())}/{int((x < -0.5).sum())}" if name != "正式版" else "—"
        lines.append(f"| {name} | {f['期末倍數']} | {f['IRR']:.1f} | {f['筆數']} | {f['回撤']} | {h['至2016年底IRR'].mean():.2f} | {pair(d16)} | {h['至今IRR'].mean():.2f} | {pair(dn)} | {h['筆數至2016'].mean():.0f} |")
    (RESULTS / "turnover_long_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True, "display.max_rows", 200):
        print(hist.pivot(index="起跑", columns="版本", values="至2016年底IRR").round(1).to_string())


if __name__ == "__main__":
    main()
