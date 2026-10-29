"""含股利（results/）vs 不含股利（results_raw/）的總表比較，輸出 results_raw/dividend_comparison.md。

先執行 ./run_all.sh 與 PRICE_MODE=raw ./run_all.sh。
"""
import pandas as pd

from backtest import ROOT

STUDIES = {
    "單一指標（樣本內 7 年）": "2382_in_sample_summary.csv",
    "上下引線＋價量": "2382_wick_backtest.csv",
    "爆量上影線買進驗證": "2382_validate_upper_wick.csv",
    "MACD 看方向＋KD 抓買點": "2382_macd_kd.csv",
    "KD 看方向＋MACD 抓買點": "2382_kd_macd.csv",
    "KD＋布林": "2382_kd_bollinger.csv",
    "布林KD位置＋價量引線觸發": "2382_zone_pv.csv",
    "KD 方向＋價量引線觸發": "2382_kd_pv.csv",
    "訊號反向": "2382_reverse.csv",
    "勝率排名": "2382_win_rate_ranking.csv",
    "殖利率＋賣一半": "2382_partial_exit_summary.csv",
    "殖利率＋達標後技術出場": "2382_trail_exit_summary.csv",
    "殖利率＋個股均線濾網": "2382_ma60_filter.csv",
    "殖利率＋大盤濾網": "2382_market_filter.csv",
    "殖利率＋爆量上下影線": "2382_wick_filter.csv",
    "三個候選版本": "2382_versions_summary.csv",
}
METRICS = ["交易次數", "筆數", "勝率%", "全期間勝率%", "樣本外勝率%", "年化%", "最大回撤%"]


def read(path):
    df = pd.read_csv(path)
    first_num = next(i for i, c in enumerate(df.columns)
                     if pd.api.types.is_numeric_dtype(df[c]) and not df.columns[i].startswith("Unnamed"))
    idx = list(df.columns[:first_num])
    df[idx] = df[idx].fillna("")
    return df.set_index(idx)


def main():
    lines = ["# 含股利 vs 不含股利\n", "數字為「含股利 → 不含股利」。\n"]
    for title, fname in STUDIES.items():
        a, b = read(ROOT / "results" / fname), read(ROOT / "results_raw" / fname)
        cols = [c for c in METRICS if c in a.columns]
        m = a[cols].join(b[cols], lsuffix="_含息", rsuffix="_不含息", how="outer")
        out = pd.DataFrame(index=m.index)
        for c in cols:
            out[c] = [f"{x:.1f} → {y:.1f}" if pd.notna(x) and pd.notna(y) else f"{x} → {y}"
                      for x, y in zip(m[f"{c}_含息"], m[f"{c}_不含息"])]
        out.index = [" / ".join(str(v) for v in (i if isinstance(i, tuple) else (i,)) if v != "") for i in out.index]
        lines += [f"\n## {title}\n", out.to_markdown(), "\n"]
    path = ROOT / "results_raw" / "dividend_comparison.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
