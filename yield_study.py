"""殖利率法 × 技術進場 × 分批加碼（只做多）。

預估殖利率 = 預估現金股利 / 當日收盤價（未調整價）
  預估現金股利：
    - 今年已有 3 個月以上營收（4/10 之後）：去年度股利 × 今年累計營收 / 去年同期累計營收
    - 1/1～4/9：若去年度股利已公告就用實際值；否則用去年度股利前一年 × 去年全年營收成長
進場：預估殖利率 >= 5%，且出現技術買進訊號（final_strategy.signals）
資金：首次 40%，之後每次加碼 20%（= 首次的 50%），最多加碼 3 次
加碼：收盤較首次進場價下跌 10% / 20% / 30%，且當天出現爆量長下影線或爆量長紅
出場：收盤價較平均成本獲利 >= 15% 全部賣出；不停損
所有動作皆收盤判斷、隔天開盤執行。

用法：python yield_study.py [代號] [殖利率門檻]
"""
import sys

import numpy as np
import pandas as pd

from backtest import BUY_COST, ROOT, SELL_COST, WARMUP, load
from final_strategy import signals
from indicators import pv_triggers

FIRST, ADD, MAX_ADDS = 0.4, 0.2, 3
ADD_STEPS = (-0.10, -0.20, -0.30)
TAKE_PROFIT = 0.15


def run_multi(df, buy, add_trigger, start, end):
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    o, c, lo = df["open"].values, df["close"].values, df["low"].values
    buy, add_trigger = buy.fillna(False).values, add_trigger.fillna(False).values
    cash, pos, trades, equity = 1.0, None, [], []
    for n, i in enumerate(idx):
        if n > 0:
            p = idx[n - 1]
            if pos is None and buy[p]:
                base = cash
                invest = base * FIRST
                pos = {"start": i, "first": o[i], "shares": invest * (1 - BUY_COST) / o[i], "cost": invest,
                       "base": base, "adds": [], "low": o[i]}
                cash -= invest
            elif pos is not None:
                if c[p] / (pos["cost"] / pos["shares"]) - 1 >= TAKE_PROFIT:
                    proceeds = pos["shares"] * o[i] * (1 - SELL_COST)
                    trades.append({"進場": df.index[pos["start"]], "出場": df.index[i], "加碼次數": len(pos["adds"]),
                                   "加碼日": ",".join(f"{d:%Y-%m-%d}" for d in pos["adds"]),
                                   "資金使用%": 100 * pos["cost"] / pos["base"], "報酬%": 100 * (proceeds / pos["cost"] - 1),
                                   "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": i - pos["start"]})
                    cash += proceeds
                    pos = None
                elif (len(pos["adds"]) < MAX_ADDS and add_trigger[p]
                      and c[p] / pos["first"] - 1 <= ADD_STEPS[len(pos["adds"])]):
                    invest = min(cash, pos["base"] * ADD)
                    pos["shares"] += invest * (1 - BUY_COST) / o[i]
                    pos["cost"] += invest
                    pos["adds"].append(df.index[i])
                    cash -= invest
        if pos is not None:
            pos["low"] = min(pos["low"], lo[i])
        equity.append(cash + (pos["shares"] * c[i] if pos else 0.0))
    if pos is not None:
        trades.append({"進場": df.index[pos["start"]], "出場": None, "加碼次數": len(pos["adds"]),
                       "加碼日": ",".join(f"{d:%Y-%m-%d}" for d in pos["adds"]),
                       "資金使用%": 100 * pos["cost"] / pos["base"],
                       "報酬%": 100 * (pos["shares"] * c[idx[-1]] * (1 - SELL_COST) / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": idx[-1] - pos["start"]})
    return pd.DataFrame(trades), pd.Series(equity, index=df.index[idx])


def summary(trades, equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    closed = trades[trades["出場"].notna()] if len(trades) else trades
    return {"筆數": len(trades), "已結案": len(closed),
            "勝率%": 100 * (closed["報酬%"] > 0).mean() if len(closed) else np.nan,
            "加碼總次數": int(trades["加碼次數"].sum()) if len(trades) else 0,
            "每筆平均%": closed["報酬%"].mean() if len(closed) else np.nan,
            "最深套牢%": trades["最深套牢%"].min() if len(trades) else np.nan,
            "最長持有日": trades["持有日"].max() if len(trades) else np.nan,
            "年化%": 100 * (equity.iloc[-1] ** (1 / years) - 1),
            "最大回撤%": 100 * (equity / equity.cummax() - 1).min()}


if __name__ == "__main__":
    df = load("2382")
    buy, _ = signals(df)
    t = pv_triggers(df)
    tr, eq = run_multi(df, buy, t["wick_buy"] | t["pv_buy"], df.index[120], df.index[-1])
    print(summary(tr, eq)); print(tr.round(1).to_string())
