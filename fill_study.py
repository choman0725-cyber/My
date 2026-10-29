"""成交時機比較：訊號隔天開盤成交 vs 訊號當天收盤價成交（盤後定價交易，假設都成交），
買與賣分開組合，共四種。

使用推薦加碼方式：首買 50%，跌 15% / 30% 觸發後加碼 30% / 20%，收盤仍低於首買價才加。
版本 A/B/C 同 compare_versions.py。用法：python fill_study.py [代號]
"""
import sys

import pandas as pd

from backtest import RESULTS, WARMUP, load
from compare_versions import versions
from strategy_a import ADD_MODE, SCHEME
from trail_exit_study import run, summary


def main(stock_id="2382"):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    vs, add = versions(df, stock_id)
    rows = {}
    for vname, (buy, target) in vs.items():
        for fname, fill in (("買賣都隔天開盤", "next_open"), ("買賣都當天收盤", "close"),
                            ("買隔天開盤·賣當天收盤", ("next_open", "close")),
                            ("買當天收盤·賣隔天開盤", ("close", "next_open"))):
            tr, eq = run(df, buy, add, start, df.index[-1], target, add_mode=ADD_MODE, scheme=SCHEME, fill=fill)
            rows[(vname, fname)] = summary(tr, eq) | {"加碼次數": int(tr["加碼"].sum()),
                                                      "最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max()}
            tag = "_".join(fill) if isinstance(fill, tuple) else fill
            tr.to_csv(RESULTS / f"{stock_id}_fill_{vname[0]}_{tag}.csv", index=False, encoding="utf-8-sig")
    table = pd.DataFrame(rows).T.drop(columns=["最好%"])
    table.round(2).to_csv(RESULTS / f"{stock_id}_fill_study.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
