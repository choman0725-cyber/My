"""殖利率 5%（EPS 法）下，比較不同的技術買點（只做多）。

加碼與出場不變：下跌 10/20/30% 且爆量下影線/長紅時各加碼 20%，獲利 15% 全賣，不停損。
買點：
  共振（目前版本）：4 指標至少 3 個超賣 ＋ KD 金叉 ＋ 年線之上
  價量引線：爆量長下影線 或 爆量長紅
  布林KD：近 3 日曾觸布林下軌 ＋ KD<30 金叉
  混合：低檔區（近 5 日觸下軌且 K<30）＋ 爆量長下影線或爆量長紅
  任一：上面任一種出現就買
用法：python yield_entry_study.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from final_strategy import signals
from indicators import bollinger, cross_up, kd, pv_triggers, setup_zones
from yield_study import forward_dividend_eps, run_multi, summary


def entries(df):
    t = pv_triggers(df)
    pv_buy = t["wick_buy"] | t["pv_buy"]
    lower, _, _ = bollinger(df)
    k, d = kd(df)
    touched = (df["low"] <= lower).astype(int).rolling(3).max().astype(bool)
    low_zone, *_ = setup_zones(df)
    e = {
        "共振（目前版本）": signals(df)[0],
        "價量引線": pv_buy,
        "布林KD": touched & cross_up(k, d) & (k < 30),
        "混合（布林KD位置＋價量引線時機）": low_zone & pv_buy,
    }
    e["任一"] = pd.concat(e.values(), axis=1).fillna(False).any(axis=1)
    return e, pv_buy


def main(stock_id="2382", threshold=5):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    cheap = 100 * dps / raw_close >= threshold
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    sigs, add = entries(df)

    rows, details = {}, {}
    for name, sig in sigs.items():
        tr, eq = run_multi(df, sig & cheap, add, start, df.index[-1])
        rows[name] = summary(tr, eq)
        details[name] = tr
        tr.to_csv(ROOT / "results" / f"{stock_id}_yield_entry_{name.split('（')[0]}.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(pd.DataFrame(rows).T.round(1).to_string(), "\n")
        for name in list(sigs)[1:]:
            print(f"【{name}】")
            print(details[name].round(1).to_string(), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
