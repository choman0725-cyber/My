"""全成分股中位數 ± k×σ 的細網格：買進 k_b ∈ [-0.10, 0.40]、續抱 k_h ∈ [0, 0.50]，步長 0.05（121 組）。
挑選條件：穩定度不能比正式版差（標準差平均 <= 正式版、三段最差 10% >= 正式版），再看三段平均最高。"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
import market_median_study as mm
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

BUY_K = [round(x, 2) for x in np.arange(-0.10, 0.401, 0.05)]
HOLD_K = [round(x, 2) for x in np.arange(0.0, 0.501, 0.05)]

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply, po.to_kw = mm.apply2, mm.to_kw2
    names = ["正式版（固定 5% / 4.75%）"]; po.CONFIGS[names[0]] = {**dr.FINAL}
    for bk in BUY_K:
        for hk in HOLD_K:
            n = f"買 中位數{bk:+.2f}σ／續抱 中位數-{hk:.2f}σ"
            po.CONFIGS[n] = {**dr.FINAL, "mkt": ("all", bk, hk, None)}; names.append(n)
    print(f"{len(names)} 組", flush=True)
    m = po.evaluate(names, "sigmagrid")
    base = m.loc[names[0]]
    rows = []
    for n in names[1:]:
        r = m.loc[n]; bk, hk = po.CONFIGS[n]["mkt"][1], po.CONFIGS[n]["mkt"][2]
        rows.append(dict(買k=bk, 續抱k=hk, **r.to_dict(), 穩定度不輸=(r["標準差平均"] <= base["標準差平均"] + 1e-9) and (r["最差10最小"] >= base["最差10最小"] - 1e-9)))
    T = pd.DataFrame(rows); T.round(2).to_csv(RESULTS / "market_sigma_grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print(f"\n正式版：三段平均 {base['三段平均']:.1f}、最差10 {base['最差10最小']:.1f}、標準差平均 {base['標準差平均']:.2f}")
    for col in ("三段平均", "最差10最小", "標準差平均", "超過2年比例"):
        print(f"\n【{col}】列＝買 k，欄＝續抱 k"); print(T.pivot(index="買k", columns="續抱k", values=col).round(1).to_string())
    ok = T[T["穩定度不輸"]].sort_values("三段平均", ascending=False)
    print(f"\n【穩定度不輸正式版的組合：{len(ok)} 組，依三段平均排序】")
    print(ok[["買k", "續抱k"] + po.SHOW + ["超過2年比例"]].head(15).round(1).to_string(index=False))
    # 放寬一點：標準差 <= 正式版 + 0.3
    ok2 = T[(T["標準差平均"] <= base["標準差平均"] + 0.3) & (T["最差10最小"] >= base["最差10最小"] - 0.5)].sort_values("三段平均", ascending=False)
    print(f"\n【略放寬（標準差 +0.3、最差10 -0.5 以內）：{len(ok2)} 組】")
    print(ok2[["買k", "續抱k"] + po.SHOW + ["超過2年比例"]].head(15).round(1).to_string(index=False))
    picks = list(ok.head(3).index) + [i for i in ok2.head(3).index if i not in ok.head(3).index]
    out = []
    for i in picks:
        bk, hk = T.loc[i, "買k"], T.loc[i, "續抱k"]; n = f"買 中位數{bk:+.2f}σ／續抱 中位數-{hk:.2f}σ"
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n]); tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw); cl = tr[tr["出場"].notna()]
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1), 平均持有日=int(cl["持有日"].mean())))
    print("\n【500 萬 2017 起不追加】"); print(pd.DataFrame(out).to_string(index=False))

if __name__ == "__main__":
    main()
