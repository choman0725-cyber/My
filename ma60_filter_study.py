"""在殖利率 5% 策略上加「股價在 60 日均線之上才買」的濾網，比較有無差異（只做多）。

濾網：無 / 收盤 > MA60 / MA60 上揚（MA60 > 20 日前的 MA60）/ 兩者皆是 /
      MA60 之上或 MA240 之下（只擋「跌破季線但仍在年線之上」的區間）/
      MA20 之上或 MA60 之下（只擋「跌破月線但仍在季線之上」的區間）
加碼不受濾網影響（已持有部位照原規則加碼）。
用法：python ma60_filter_study.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from indicators import sma
from trail_exit_study import run, summary
from yield_entry_study import entries
from yield_study import forward_dividend_eps


def main(stock_id="2382"):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    cheap = 100 * dps / raw_close >= 5
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    sigs, add = entries(df)
    ma20, ma60, ma240 = sma(df["close"], 20), sma(df["close"], 60), sma(df["close"], 240)
    filters = {"無濾網": pd.Series(True, index=df.index), "股價>MA60": df["close"] > ma60,
               "MA60上揚": ma60 > ma60.shift(20), "股價>MA60且上揚": (df["close"] > ma60) & (ma60 > ma60.shift(20)),
               "MA60上或MA240下": (df["close"] > ma60) | (df["close"] < ma240),
               "MA20上或MA60下": (df["close"] > ma20) | (df["close"] < ma60)}

    rows, details = {}, {}
    for ename in ("任一", "混合（布林KD位置＋價量引線時機）", "共振（目前版本）", "價量引線"):
        for target in (0.15, 0.20):
            for fname, f in filters.items():
                tr, eq = run(df, sigs[ename] & cheap & f, add, start, df.index[-1], target)
                key = (ename.split("（")[0], f"{target:.0%}", fname)
                rows[key] = summary(tr, eq) | {"最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max()}
                details[key] = tr
    table = pd.DataFrame(rows).T.drop(columns=["最好%"])
    table.index.names = ["買點", "停利", "濾網"]
    table.round(2).to_csv(ROOT / "results" / f"{stock_id}_ma60_filter.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 60, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        for key in (("任一", "20%", "MA20上或MA60下"), ("混合", "20%", "MA20上或MA60下")):
            print(f"【{key}】")
            print(details[key].drop(columns=["達標日"]).round(1).to_string(), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
