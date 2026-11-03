"""Bootstrap（2026-11-03 使用者同意的測試方法補強第 3 項）：回答「IRR 的抽樣誤差有多大、紅線 σ 0.15 有沒有意義」。
三個角度，都用正式版（六種買點）、500 萬 2016-12-28 起跑到回測截止日：
  ① 交易 bootstrap：62 筆交易重抽（放回），每筆對整體權益的貢獻 ＝ 1 ＋ 報酬 × 權重，權重＝投入 ÷ 進場當天權益；
     連乘會高估（部位重疊、閒置現金），先把對數貢獻等比例縮到「實際交易連乘＝實際倍數」再重抽 5,000 次 → IRR 90% 區間，看的是寬度。
  ② 月報酬區塊 bootstrap：權益曲線切成月報酬，6 個月一塊重抽拼回同長度，5,000 次 → IRR 90% 區間（保留月內／半年內相關性）。
  ③ 20 情境 σ 的誤差：`param_opt.evaluate()` 的前 7 年 20 個 IRR 重抽 20 個算標準差，10,000 次 → σ 本身的 90% 區間；
     與紅線 0.15 比：σ 的抽樣誤差若遠大於 0.15，σ 升 0.1～0.2 就分不出是規則還是運氣。
用法：python bootstrap_study.py　輸出：results/bootstrap_summary.md、bootstrap_trades.csv、bootstrap_months.csv、bootstrap_sigma.csv"""
import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

N = 5000
SEED = 20261103


def q(x, ps_=(.05, .5, .95)):
    return [float(np.quantile(x, p)) for p in ps_]


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.CONFIGS["正式版"] = rr.BASE; po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=1, **kw)
    years = (dates[-1] - dates[1]).days / 365.25
    mult = float(eq.iloc[-1]); base_irr = irr([CAPITAL], [dates[1]], mult * CAPITAL, dates[-1])
    rng = np.random.default_rng(SEED)

    # ① 交易 bootstrap
    t = tr.dropna(subset=["報酬%"]).copy()
    ent = pd.to_datetime(t["進場"])
    v_entry = eq.reindex(ent, method="ffill").values
    w = t["投入"].values / v_entry
    g = 1 + w * t["報酬%"].values / 100          # 每筆對權益的乘數
    calib = float(np.prod(g))                      # 用實際 62 筆算回來的倍數，對照真實倍數看近似誤差
    # 連乘會高估（部位重疊、閒置現金、加碼後權重變動），所以把每筆的對數貢獻等比例縮到「實際 62 筆連乘＝實際倍數」再重抽：
    # 分布的中心就落在實際值，寬度才是這個角度要看的東西
    lg = np.log(g) * (np.log(mult) / np.log(calib))
    idx = rng.integers(0, len(g), size=(N, len(g)))
    mults = np.exp(lg[idx].sum(axis=1))
    irrs_t = (mults ** (1 / years) - 1) * 100
    pd.DataFrame({"倍數": mults, "IRR": irrs_t}).to_csv(RESULTS / "bootstrap_trades.csv", index=False, encoding="utf-8-sig")

    # ② 月報酬區塊 bootstrap
    m = eq.resample("ME").last().pct_change().dropna().values
    B = 6; nb = int(np.ceil(len(m) / B))
    starts = rng.integers(0, len(m) - B + 1, size=(N, nb))
    blocks = np.stack([m[s:s + B] for s in starts.ravel()]).reshape(N, nb * B)[:, :len(m)]
    mults_m = np.prod(1 + blocks, axis=1)
    irrs_m = (mults_m ** (1 / years) - 1) * 100
    pd.DataFrame({"倍數": mults_m, "IRR": irrs_m}).to_csv(RESULTS / "bootstrap_months.csv", index=False, encoding="utf-8-sig")

    # ③ 20 情境 σ 的抽樣誤差
    po.evaluate(["正式版"], "bs")
    runs = pd.read_csv(RESULTS / "param_opt_bs_is_runs.csv")
    irr20 = runs.loc[runs["版本"] == "正式版", "IRR"].values
    idx20 = rng.integers(0, len(irr20), size=(10000, len(irr20)))
    sig = irr20[idx20].std(axis=1, ddof=1)
    med20 = np.median(irr20[idx20], axis=1)
    pd.DataFrame({"σ": sig, "中位": med20}).to_csv(RESULTS / "bootstrap_sigma.csv", index=False, encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_bs_*"):
        f.unlink()

    qt, qm, qs, qmed = q(irrs_t), q(irrs_m), q(sig), q(med20)
    lines = ["# Bootstrap（bootstrap_study.py）", "",
             f"正式版 500 萬 2016-12-28 起：期末 {mult * CAPITAL / 1e4:,.0f} 萬（{mult:.2f} 倍）、IRR {base_irr:.2f}%、{len(t)} 筆交易、{years:.1f} 年", "",
             "| 角度 | 5% | 中位 | 95% | 實際 |", "|---|---|---|---|---|",
             f"| ① 交易重抽 IRR | {qt[0]:.1f} | {qt[1]:.1f} | {qt[2]:.1f} | {base_irr:.1f} |",
             f"| ① 交易重抽 期末萬 | {q(mults)[0] * CAPITAL / 1e4:,.0f} | {q(mults)[1] * CAPITAL / 1e4:,.0f} | {q(mults)[2] * CAPITAL / 1e4:,.0f} | {mult * CAPITAL / 1e4:,.0f} |",
             f"| ② 月報酬 6 月區塊重抽 IRR | {qm[0]:.1f} | {qm[1]:.1f} | {qm[2]:.1f} | {base_irr:.1f} |",
             f"| ② 月報酬重抽 期末萬 | {q(mults_m)[0] * CAPITAL / 1e4:,.0f} | {q(mults_m)[1] * CAPITAL / 1e4:,.0f} | {q(mults_m)[2] * CAPITAL / 1e4:,.0f} | {mult * CAPITAL / 1e4:,.0f} |",
             f"| ③ 前 7 年 20 情境 σ | {qs[0]:.2f} | {qs[1]:.2f} | {qs[2]:.2f} | {irr20.std(ddof=1):.2f} |",
             f"| ③ 前 7 年 20 情境中位 | {qmed[0]:.2f} | {qmed[1]:.2f} | {qmed[2]:.2f} | {np.median(irr20):.2f} |", "",
             f"①未校準前：實際 {len(t)} 筆交易「1＋報酬×權重」連乘＝{calib:.2f} 倍，真實 {mult:.2f} 倍（部位重疊、閒置現金、加碼權重造成的高估），已等比例縮放後重抽，所以只看寬度。",
             f"③σ 的 90% 區間寬度 {qs[2] - qs[0]:.2f}；紅線 0.15 相當於區間寬度的 {0.15 / (qs[2] - qs[0]):.0%}。",
             f"單一路徑 IRR 的 90% 區間寬度：交易重抽 {qt[2] - qt[0]:.1f} 個百分點、月報酬重抽 {qm[2] - qm[0]:.1f} 個百分點。"]
    (RESULTS / "bootstrap_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
