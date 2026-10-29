"""最佳逆勢策略的參數鄰域檢查：參數小幅變動時，結果是否仍穩定（不拿來挑參數）。

基準：多指標共振（標準門檻、2 個指標、近 3 日）＋年線之上＋停利 10%。
用法：python robustness.py [代號] [樣本內年數]
"""
import itertools
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from indicators import sma
from meanrev_study import resonance, run_trades, stats


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"IS": (start, split), "OOS": (split + pd.Timedelta(days=1), df.index[-1]), "全": (start, df.index[-1])}

    rows = []
    for level, need, window, ma, tp in itertools.product(
            ("嚴格", "標準", "寬鬆"), (2, 3), (3, 5), (200, 240), (0.08, 0.10, 0.12)):
        buy, sell = resonance(df, level, need, window)
        f = df["close"] > sma(df["close"], ma)
        row = {"門檻": level, "需幾個": need, "近幾日": window, "長均線": ma, "停利": tp}
        for p, (s, e) in periods.items():
            st = stats(*run_trades(df, buy & f, sell, s, e, tp=tp))
            row.update({f"{p}次數": st["次數"], f"{p}勝率%": st["勝率%"], f"{p}年化%": st["年化%"]})
        rows.append(row)
    t = pd.DataFrame(rows)
    t.round(2).to_csv(ROOT / "results" / f"{stock_id}_meanrev_robustness.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(t.round(1).to_string(index=False))
        print("\n各參數平均：")
        for col in ("門檻", "需幾個", "近幾日", "長均線", "停利"):
            print(t.groupby(col)[["全次數", "IS勝率%", "OOS勝率%", "全勝率%", "全年化%"]].mean().round(1), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
