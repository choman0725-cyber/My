"""樣本外驗證：爆量長上影線買進（只做多）。

進場：長上影線 + 成交量 > 1.5 倍 20 日均量 → 隔天開盤買進。
出場（三種，事先定好）：
  X1 固定持有 20 個交易日
  X2 收盤跌破 MA20
  X3 出現「長下影線 + 爆量 + 低檔」
樣本內 = 前 7 年；樣本外 = 之後到最新一天（先前所有研究都沒用到）。

用法：python validate.py [代號] [樣本內年數]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, buy_and_hold, load, run, summarize, RESULTS
from indicators import sma, wick_conditions


def hold_n_days(buy, n=20):
    """持有 n 個交易日：買進訊號後第 n 天發出賣出訊號（隔天開盤賣）。"""
    return buy.shift(n - 1, fill_value=False)


def exits(df, buy):
    c = wick_conditions(df)
    return {
        "X1 固定持有 20 日": hold_n_days(buy),
        "X2 跌破 MA20": df["close"] < sma(df["close"], 20),
        "X3 爆量低檔長下影線": c["long_lower"] & c["vol_up"] & c["low_zone"],
    }


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    c = wick_conditions(df)
    buy = (c["long_upper"] & c["vol_up"]).fillna(False)

    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"樣本內": (start, split), "樣本外": (split + pd.Timedelta(days=1), df.index[-1])}

    rows, all_trades = {}, []
    for pname, (s, e) in periods.items():
        rows[(pname, "買進持有（基準）")] = buy_and_hold(df, s, e)
        for xname, sell in exits(df, buy).items():
            trades, equity = run(df, buy, sell, s, e)
            rows[(pname, xname)] = summarize(trades, equity)
            all_trades.append(trades.assign(period=pname, exit_rule=xname))
        print(f"{pname}：{s:%Y-%m-%d} ~ {e:%Y-%m-%d}")

    table = pd.DataFrame(rows).T
    out = RESULTS
    out.mkdir(exist_ok=True)
    table.round(2).to_csv(out / f"{stock_id}_validate_upper_wick.csv", encoding="utf-8-sig")
    pd.concat(all_trades).to_csv(out / f"{stock_id}_validate_upper_wick_trades.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
