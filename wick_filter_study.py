"""爆量上影線不買、爆量下影線買：疊在殖利率 5%（EPS 法）＋技術買點策略上（只做多）。

爆量 = 成交量 > 1.5 倍 20 日均量；長影線 = 影線占 K 棒全長 >= 50% 且 K 棒全長 >= 0.8 ATR。
進場變化：
  任一：原本四種買點任一（已含爆量下影線、爆量長紅）
  只用爆量下影線：買點只剩爆量長下影線
不買條件：當天 / 近 5 日內出現爆量長上影線
大盤濾網：無 / 加權指數季線上或年線下
加碼與出場不變。
用法：python wick_filter_study.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from indicators import pv_triggers
from market_filter_study import index_filters
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
    t = pv_triggers(df)
    upper = t["wick_sell"].fillna(False)
    all_true = pd.Series(True, index=df.index)

    buys = {"任一": sigs["任一"], "只用爆量下影線": t["wick_buy"]}
    blocks = {"不擋": all_true, "當天爆量上影線不買": ~upper,
              "近5日爆量上影線不買": ~upper.astype(int).rolling(5).max().astype(bool)}
    markets = {"無大盤濾網": all_true, "大盤季線上或年線下": index_filters(df, "TAIEX")["TAIEX MA60上或MA240下"]}

    rows = {}
    for bname, b in buys.items():
        for target in (0.15, 0.20):
            for mname, m in markets.items():
                for kname, k in blocks.items():
                    tr, eq = run(df, b & cheap & m & k, add, start, df.index[-1], target)
                    key = (bname, f"{target:.0%}", mname, kname)
                    rows[key] = ({"筆數": 0} if tr.empty else summary(tr, eq) | {
                        "最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max(),
                        "持有中%": tr.loc[tr["出場"].isna(), "報酬%"].sum() if tr["出場"].isna().any() else None})
    table = pd.DataFrame(rows).T.drop(columns=["最好%"], errors="ignore")
    table.index.names = ["買點", "停利", "大盤", "上影線"]
    table.round(2).to_csv(ROOT / "results" / f"{stock_id}_wick_filter.csv", encoding="utf-8-sig")
    cols = ["筆數", "已結案", "勝率%", "每筆平均%", "年化%", "最大回撤%", "最深套牢%", "最長持有日", "持有中%"]
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(table[cols].round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
