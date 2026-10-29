"""最終版逆勢策略（只做多），並顯示最新一天的狀態。

進場（收盤判斷，隔天開盤買）：
  1. 近 3 個交易日內，KD(K<20)、RSI(<30)、威廉(<-80)、CCI(<-100) 至少 3 個曾超賣
  2. 當天 KD 黃金交叉
  3. 收盤在年線（240 日均線）之上
出場（收盤判斷，隔天開盤賣，先到先出）：
  - 收盤獲利 >= 10%
  - 多指標超買共振（至少 3 個超買）且 KD 死叉
  - 收盤虧損 <= -15%（停損）

用法：python final_strategy.py [代號]
"""
import sys

import pandas as pd

from backtest import WARMUP, load
from indicators import cci_line, kd, rsi, sma, williams_r
from meanrev_study import resonance, run_trades, stats

TAKE_PROFIT, STOP = 0.10, -0.15


def signals(df):
    buy, sell = resonance(df, "標準", need=3, window=3)
    return buy & (df["close"] > sma(df["close"], 240)), sell


def main(stock_id="2382"):
    df = load(stock_id)
    buy, sell = signals(df)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    trades, equity, open_trade = run_trades(df, buy, sell, start, df.index[-1], tp=TAKE_PROFIT, stop=STOP)
    s = stats(trades, equity, open_trade)
    print(f"{stock_id} 回測 {equity.index[0]:%Y-%m-%d} ~ {equity.index[-1]:%Y-%m-%d}：{s['次數']} 筆，"
          f"勝率 {s['勝率%']:.0f}%，每筆平均 {s['每筆平均%']:.1f}%，最大回撤 {s['最大回撤%']:.1f}%")

    k, d = kd(df)
    last = df.index[-1]
    print(f"\n最新 {last:%Y-%m-%d}：收盤 {df['close'].iloc[-1]:.1f}，年線 {sma(df['close'], 240).iloc[-1]:.1f}")
    print(f"  K {k.iloc[-1]:.0f} / D {d.iloc[-1]:.0f}，RSI {rsi(df['close']).iloc[-1]:.0f}，"
          f"威廉 {williams_r(df).iloc[-1]:.0f}，CCI {cci_line(df).iloc[-1]:.0f}")
    if buy.iloc[-1]:
        print("  → 今天出現買進訊號，明天開盤買進")
    elif open_trade:
        print(f"  → 持有中（{trades['entry'].iloc[-1]:%Y-%m-%d} 進場）")
    else:
        print("  → 沒有訊號，空手等待")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
