"""比較三個候選版本（皆為殖利率 5% EPS 法＋技術買點＋分批加碼，只做多）。

A 報酬最高：任一買點、停利 20%、無大盤濾網
B 平衡：    任一買點、停利 15%、大盤季線上或年線下
C 最穩：    混合買點、停利 20%、大盤季線上或年線下
用法：python compare_versions.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load, RESULTS
from market_filter_study import index_filters
from trail_exit_study import run, summary
from yield_entry_study import entries
from yield_study import forward_dividend_eps


def versions(df, stock_id):
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    cheap = 100 * dps / raw_close >= 5
    sigs, add = entries(df)
    market = index_filters(df, "TAIEX")["TAIEX MA60上或MA240下"]
    return {
        "A 報酬最高": (sigs["任一"] & cheap, 0.20),
        "B 平衡": (sigs["任一"] & cheap & market, 0.15),
        "C 最穩": (sigs["混合（布林KD位置＋價量引線時機）"] & cheap & market, 0.20),
    }, add


def main(stock_id="2382"):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    vs, add = versions(df, stock_id)
    rows, yearly, details = {}, {}, {}
    for name, (buy, target) in vs.items():
        tr, eq = run(df, buy, add, start, df.index[-1], target)
        s = summary(tr, eq)
        held = sum(((eq.index >= a) & (eq.index < (b if pd.notna(b) else eq.index[-1]))).sum()
                   for a, b in zip(tr["進場"], tr["出場"]))
        open_tr = tr[tr["出場"].isna()]
        rows[name] = {**s, "最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max(),
                      "加碼次數": int(tr["加碼"].sum()), "持股時間%": 100 * held / len(eq),
                      "目前持有": "無" if open_tr.empty else f"{open_tr['進場'].iloc[0]:%Y-%m-%d} 進場 {open_tr['報酬%'].iloc[0]:+.1f}%"}
        yearly[name] = eq.groupby(eq.index.year).last().pct_change().fillna(eq.groupby(eq.index.year).last().iloc[0] - 1) * 100
        details[name] = tr
        tr.to_csv(RESULTS / f"{stock_id}_version_{name[0]}_trades.csv", index=False, encoding="utf-8-sig")
    bh = df.loc[start:, "close"]
    bh_y = bh.groupby(bh.index.year).last()
    yearly["買進持有"] = bh_y.pct_change().fillna(bh_y.iloc[0] / bh.iloc[0] - 1) * 100
    years = (bh.index[-1] - bh.index[0]).days / 365.25
    rows["買進持有"] = {"年化%": 100 * ((bh.iloc[-1] / bh.iloc[0]) ** (1 / years) - 1),
                    "最大回撤%": 100 * (bh / bh.cummax() - 1).min()}

    table = pd.DataFrame(rows).T
    pd.DataFrame(yearly).round(1).to_csv(RESULTS / f"{stock_id}_versions_yearly.csv", encoding="utf-8-sig")
    table.to_csv(RESULTS / f"{stock_id}_versions_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(table.T.to_string(), "\n")
        print("【每年報酬%】\n", pd.DataFrame(yearly).round(1).to_string(), "\n")
        for name, tr in details.items():
            print(f"【{name}】")
            print(tr[["進場", "出場", "加碼", "報酬%", "最深套牢%", "持有日"]].round(1).to_string(), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
