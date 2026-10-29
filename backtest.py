"""單一指標波段回測（只做多）。

規則：
- 收盤出現買進訊號 → 隔天開盤買進；出現賣出訊號 → 隔天開盤賣出。
- 同時只持有一筆、全額進出；期間結束仍持有則以最後收盤價結算。
- 價格預設使用除權息調整後的 OHLC（含現金股利）；
  環境變數 PRICE_MODE=raw 時改用原始股價（不含股利），結果寫到 results_raw/。
- 成本：買 0.1425%，賣 0.1425% + 證交稅 0.3%。

用法：python backtest.py [代號] [樣本內年數]
    python backtest.py 2382 7
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from indicators import STRATEGIES

ROOT = Path(__file__).parent
RAW_PRICES = os.environ.get("PRICE_MODE") == "raw"
RESULTS = ROOT / ("results_raw" if RAW_PRICES else "results")
BUY_COST = 0.001425
SELL_COST = 0.001425 + 0.003
WARMUP = 120  # 指標暖身天數，取樣本內起點前的資料計算指標


def load(stock_id):
    df = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")
    if RAW_PRICES:
        return df.drop(columns="adj_close")
    factor = df["adj_close"] / df["close"]
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] * factor
    return df.drop(columns="adj_close")


def run(df, buy, sell, start, end):
    """回傳交易明細與每日資產曲線（只在 start~end 期間交易）。"""
    period = (df.index >= start) & (df.index <= end)
    idx = np.flatnonzero(period)
    opens, closes = df["open"].values, df["close"].values
    buy, sell = buy.fillna(False).values, sell.fillna(False).values

    trades, equity = [], []
    cash, shares, entry = 1.0, 0.0, None
    for n, i in enumerate(idx):
        # 前一天的訊號在今天開盤執行
        if n > 0:
            prev = idx[n - 1]
            if shares == 0 and buy[prev]:
                shares = cash * (1 - BUY_COST) / opens[i]
                entry = (df.index[i], opens[i], cash)
                cash = 0.0
            elif shares > 0 and sell[prev]:
                cash = shares * opens[i] * (1 - SELL_COST)
                trades.append((*entry, df.index[i], opens[i], cash))
                shares = 0.0
        equity.append(cash + shares * closes[i])

    if shares > 0:  # 期末強制結算
        i = idx[-1]
        cash = shares * closes[i] * (1 - SELL_COST)
        trades.append((*entry, df.index[i], closes[i], cash))
        equity[-1] = cash

    trades = pd.DataFrame(trades, columns=["entry_date", "entry_price", "entry_value", "exit_date", "exit_price", "exit_value"])
    trades["return"] = trades["exit_value"] / trades["entry_value"] - 1
    trades["days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
    return trades, pd.Series(equity, index=df.index[idx])


def summarize(trades, equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    r = trades["return"]
    wins, losses = r[r > 0], r[r <= 0]
    peak = equity.cummax()
    held = sum(((equity.index >= a) & (equity.index < b)).sum() for a, b in zip(trades["entry_date"], trades["exit_date"]))
    return {
        "交易次數": len(r),
        "勝率%": 100 * len(wins) / len(r) if len(r) else np.nan,
        "平均獲利%": 100 * wins.mean() if len(wins) else 0.0,
        "平均虧損%": 100 * losses.mean() if len(losses) else 0.0,
        "賺賠比": wins.mean() / -losses.mean() if len(wins) and len(losses) else np.nan,
        "每筆期望值%": 100 * r.mean() if len(r) else np.nan,
        "總報酬%": 100 * (equity.iloc[-1] - 1),
        "年化%": 100 * (equity.iloc[-1] ** (1 / years) - 1),
        "最大回撤%": 100 * (equity / peak - 1).min(),
        "持股時間%": 100 * held / len(equity),
        "平均持有天數": trades["days"].mean() if len(r) else np.nan,
    }


def buy_and_hold(df, start, end):
    p = df.loc[start:end]
    equity = p["close"] / p["open"].iloc[0] * (1 - BUY_COST)
    equity.iloc[-1] *= 1 - SELL_COST
    trades = pd.DataFrame({"entry_date": [p.index[0]], "exit_date": [p.index[-1]], "return": [equity.iloc[-1] - 1]})
    trades["days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
    return summarize(trades, equity)


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))  # 留暖身期
    end = df.index[0] + pd.DateOffset(years=in_sample_years)
    print(f"{stock_id} 樣本內回測：{start:%Y-%m-%d} ~ {end:%Y-%m-%d}（{end:%Y-%m-%d} 之後保留為樣本外，未使用）\n")

    rows, all_trades = {"買進持有（基準）": buy_and_hold(df, start, end)}, []
    for name, fn in STRATEGIES.items():
        buy, sell = fn(df)
        trades, equity = run(df, buy, sell, start, end)
        rows[name] = summarize(trades, equity)
        all_trades.append(trades.assign(strategy=name))

    table = pd.DataFrame(rows).T
    order = ["買進持有（基準）"] + table.drop("買進持有（基準）").sort_values("年化%", ascending=False).index.tolist()
    table = table.loc[order]

    out = RESULTS
    out.mkdir(exist_ok=True)
    table.round(2).to_csv(out / f"{stock_id}_in_sample_summary.csv", encoding="utf-8-sig")
    pd.concat(all_trades).to_csv(out / f"{stock_id}_in_sample_trades.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
