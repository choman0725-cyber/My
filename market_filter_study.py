"""用大盤（加權指數）或費城半導體指數當濾網，疊在殖利率 5% ＋ 技術買點策略上（只做多）。

完整進場條件：EPS 法殖利率 >= 5% ＆ 技術買點 ＆ 指數濾網
加碼與出場不變：下跌 10/20/30% 且爆量下影線/長紅各加碼 20%，獲利達標全賣，不停損。
指數濾網（加權指數用當天收盤；費半只用台股當天之前已收盤的美股交易日，避免時差偷看）：
  指數>MA60、指數>MA240、MA60上揚、
  MA20上或MA60下（只擋指數跌破月線但仍在季線上）、
  MA60上或MA240下（只擋指數跌破季線但仍在年線上）、
  MA20上或MA240下（只擋指數跌破月線但仍在年線上）、
  MA20上且MA240下 / MA60上且MA240下（只在空頭中反彈站上月線/季線時買）、
  非空頭排列或MA240下（空頭排列 MA5<MA20<MA60 時不買，但跌破年線照買）
用法：python market_filter_study.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load, RESULTS
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
        "MA20上或MA240下": (idx > ma20) | (idx < ma240),
        "MA20上且MA240下": (idx > ma20) & (idx < ma240),
        "MA60上且MA240下": (idx > ma60) & (idx < ma240),
        "非空頭排列或MA240下": ~((sma(idx, 5) < ma20) & (ma20 < ma60)) | (idx < ma240),
    }
    # 對齊到個股交易日：台股指數用當天；美股指數只用日期早於當天的最近一筆
    lag = pd.Timedelta(days=0 if name == "TAIEX" else 1)
    out = {}
    for k, v in raw.items():
        v = v.astype(float)
        v.index = v.index + lag
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
    c = df["close"]
    ma5, ma20, ma60, ma240 = (sma(c, n) for n in (5, 20, 60, 240))
    filters["個股 非空頭排列或MA240下"] = ~((ma5 < ma20) & (ma20 < ma60)) | (c < ma240)
    for name in indices:
        if (ROOT / "data" / f"{name}.csv").exists():
            filters.update(index_filters(df, name))

    rows, details = {}, {}
    for ename in ("任一", "價量引線", "混合（布林KD位置＋價量引線時機）"):
        for target in (0.15, 0.20):
            for fname, f in filters.items():
                tr, eq = run(df, sigs[ename] & cheap & f, add, start, df.index[-1], target)
                key = (ename.split("（")[0], f"{target:.0%}", fname)
                if tr.empty:
                    rows[key] = {"筆數": 0}
                    continue
                rows[key] = summary(tr, eq) | {"最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max()}
                details[key] = tr
    table = pd.DataFrame(rows).T.drop(columns=["最好%"]).fillna({"已結案": 0})
    table.index.names = ["買點", "停利", "濾網"]
    table.round(2).to_csv(RESULTS / f"{stock_id}_market_filter.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())
    return table, details


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
