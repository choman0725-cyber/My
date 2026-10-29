"""用大盤（加權指數）或費城半導體指數當濾網，疊在殖利率 5% ＋ 技術買點策略上（只做多）。

完整進場條件：EPS 法殖利率 >= 5% ＆ 技術買點 ＆ 指數濾網
加碼與出場不變：下跌 10/20/30% 且爆量下影線/長紅各加碼 20%，獲利達標全賣，不停損。
指數濾網（只用前一交易日已收盤的指數，避免台美時差偷看）：
  指數>MA60、指數>MA240、MA60上揚、
  MA20上或MA60下（只擋指數跌破月線但仍在季線上）、
  MA60上或MA240下（只擋指數跌破季線但仍在年線上）
用法：python market_filter_study.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from indicators import sma
from trail_exit_study import run, summary
from yield_entry_study import entries
from yield_study import forward_dividend_eps


def index_filters(df, name):
    idx = pd.read_csv(ROOT / "data" / f"{name}.csv", parse_dates=["date"]).set_index("date")["close"]
    ma20, ma60, ma240 = sma(idx, 20), sma(idx, 60), sma(idx, 240)
    raw = {
        "指數>MA60": idx > ma60,
        "指數>MA240": idx > ma240,
        "MA60上揚": ma60 > ma60.shift(20),
        "MA20上或MA60下": (idx > ma20) | (idx < ma60),
        "MA60上或MA240下": (idx > ma60) | (idx < ma240),
    }
    # 對齊到個股交易日：只用嚴格早於當天的最近一個指數收盤
    out = {}
    for k, v in raw.items():
        v = v.astype(float).shift(1)
        out[f"{name} {k}"] = v.reindex(df.index.union(v.index)).ffill().reindex(df.index).fillna(0).astype(bool)
    return out


def main(stock_id="2382", indices=("TAIEX", "SOX")):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    cheap = 100 * dps / raw_close >= 5
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    sigs, add = entries(df)

    filters = {"無濾網": pd.Series(True, index=df.index)}
    for name in indices:
        if (ROOT / "data" / f"{name}.csv").exists():
            filters.update(index_filters(df, name))

    rows, details = {}, {}
    for ename in ("任一", "價量引線", "混合（布林KD位置＋價量引線時機）"):
        for target in (0.15, 0.20):
            for fname, f in filters.items():
                tr, eq = run(df, sigs[ename] & cheap & f, add, start, df.index[-1], target)
                key = (ename.split("（")[0], f"{target:.0%}", fname)
                rows[key] = summary(tr, eq) | {"最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max()}
                details[key] = tr
    table = pd.DataFrame(rows).T.drop(columns=["最好%"])
    table.index.names = ["買點", "停利", "濾網"]
    table.round(2).to_csv(ROOT / "results" / f"{stock_id}_market_filter.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())
    return table, details


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
