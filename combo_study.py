"""組合策略回測：同時跑樣本內（前 N 年）與樣本外（之後到最新），只做多。

用法：python combo_study.py [代號] [樣本內年數]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, buy_and_hold, load, run, summarize, RESULTS
from indicators import MACD_KD_STRATEGIES


def main(stock_id="2382", in_sample_years=7, strategies=MACD_KD_STRATEGIES, tag="macd_kd"):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"樣本內": (start, split), "樣本外": (split + pd.Timedelta(days=1), df.index[-1])}

    signals = {name: fn(df) for name, fn in strategies.items()}
    rows, all_trades = {}, []
    for pname, (s, e) in periods.items():
        print(f"{pname}：{s:%Y-%m-%d} ~ {e:%Y-%m-%d}")
        rows[(pname, "買進持有（基準）")] = buy_and_hold(df, s, e)
        for name, (buy, sell) in signals.items():
            trades, equity = run(df, buy, sell, s, e)
            rows[(pname, name)] = summarize(trades, equity)
            all_trades.append(trades.assign(period=pname, strategy=name))

    table = pd.DataFrame(rows).T
    out = RESULTS
    out.mkdir(exist_ok=True)
    table.round(2).to_csv(out / f"{stock_id}_{tag}.csv", encoding="utf-8-sig")
    pd.concat(all_trades).to_csv(out / f"{stock_id}_{tag}_trades.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
