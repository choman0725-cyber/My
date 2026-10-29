"""反向操作：把原策略的買賣訊號對調（原本賣出訊號時買進、原本買進訊號時賣出），只做多。

同時列出原策略與反向策略在樣本內、樣本外的表現。
用法：python reverse_study.py [代號] [樣本內年數]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, buy_and_hold, load, run, summarize, RESULTS
from indicators import MACD_KD_STRATEGIES, STRATEGIES, WICK_STRATEGIES

COLUMNS = ["交易次數", "勝率%", "賺賠比", "年化%", "最大回撤%", "持股時間%"]


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"樣本內": (start, split), "樣本外": (split + pd.Timedelta(days=1), df.index[-1])}
    strategies = {**STRATEGIES, **WICK_STRATEGIES}
    strategies.update({k: v for k, v in MACD_KD_STRATEGIES.items() if v not in strategies.values()})

    rows = {}
    for pname, (s, e) in periods.items():
        rows[("買進持有（基準）", pname, "")] = buy_and_hold(df, s, e)
    for name, fn in strategies.items():
        buy, sell = fn(df)
        for pname, (s, e) in periods.items():
            rows[(name, pname, "原本")] = summarize(*run(df, buy, sell, s, e))
            rows[(name, pname, "反向")] = summarize(*run(df, sell, buy, s, e))

    table = pd.DataFrame(rows).T[COLUMNS]
    table.index.names = ["策略", "期間", "方向"]
    out = RESULTS
    out.mkdir(exist_ok=True)
    table.round(2).to_csv(out / f"{stock_id}_reverse.csv", encoding="utf-8-sig")

    view = table["年化%"].unstack(["期間", "方向"]).round(1)
    win = table["勝率%"].unstack(["期間", "方向"]).round(0)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.unicode.east_asian_width", True):
        print("【年化報酬%】\n", view.to_string(), "\n\n【勝率%】\n", win.to_string(),
              "\n\n【交易次數】\n", table["交易次數"].unstack(["期間", "方向"]).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
