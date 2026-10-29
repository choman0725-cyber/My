"""上下引線 × 價量關係研究。

1. 事件研究：每次出現訊號後 N 個交易日的漲跌，統計「方向猜對」的比例，並和
   同期間任意一天的基準機率比較（廣達長期上漲，任意一天買進本來就容易賺）。
2. 波段回測：下影線訊號買進、上影線訊號賣出（規則同 backtest.py）。

用法：python wick_study.py [代號] [樣本內年數]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, buy_and_hold, load, run, summarize, RESULTS
from indicators import WICK_STRATEGIES, wick_conditions

HORIZONS = (5, 10, 20)


def event_study(df, start, end):
    c = wick_conditions(df)
    # 隔天開盤進場，持有 N 天後收盤
    fwd = {n: df["close"].shift(-n) / df["open"].shift(-1) - 1 for n in HORIZONS}
    events = {
        "（基準）任意一天": pd.Series(True, index=df.index),
        "長下影線": c["long_lower"],
        "長下影線＋爆量": c["long_lower"] & c["vol_up"],
        "長下影線＋低檔": c["long_lower"] & c["low_zone"],
        "長下影線＋爆量＋低檔": c["long_lower"] & c["vol_up"] & c["low_zone"],
        "長上影線": c["long_upper"],
        "長上影線＋爆量": c["long_upper"] & c["vol_up"],
        "長上影線＋高檔": c["long_upper"] & c["high_zone"],
        "長上影線＋爆量＋高檔": c["long_upper"] & c["vol_up"] & c["high_zone"],
    }
    in_period = (df.index >= start) & (df.index <= end)
    rows = {}
    for name, mask in events.items():
        m = mask.fillna(False) & in_period
        row = {"次數": int(m.sum())}
        for n in HORIZONS:
            r = fwd[n][m].dropna()
            row[f"{n}日後上漲%"] = 100 * (r > 0).mean()
            row[f"{n}日平均報酬%"] = 100 * r.mean()
        rows[name] = row
    return pd.DataFrame(rows).T


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    end = df.index[0] + pd.DateOffset(years=in_sample_years)
    print(f"{stock_id} 樣本內：{start:%Y-%m-%d} ~ {end:%Y-%m-%d}\n")

    events = event_study(df, start, end)
    rows = {"買進持有（基準）": buy_and_hold(df, start, end)}
    for name, fn in WICK_STRATEGIES.items():
        buy, sell = fn(df)
        rows[name] = summarize(*run(df, buy, sell, start, end))
    backtests = pd.DataFrame(rows).T

    out = RESULTS
    out.mkdir(exist_ok=True)
    events.round(2).to_csv(out / f"{stock_id}_wick_events.csv", encoding="utf-8-sig")
    backtests.round(2).to_csv(out / f"{stock_id}_wick_backtest.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.unicode.east_asian_width", True):
        print("【事件研究】訊號隔天開盤進場，N 日後收盤的漲跌\n")
        print(events.round(1).to_string())
        print("\n【波段回測】\n")
        print(backtests.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
