"""把所有測過的策略只看「每筆交易勝率」排名（樣本內、樣本外、全期間）。

用法：python win_rate_ranking.py [代號] [樣本內年數]
"""
import sys

import pandas as pd

import indicators as ind
from backtest import ROOT, WARMUP, load, run, RESULTS

GROUPS = ["STRATEGIES", "WICK_STRATEGIES", "MACD_KD_STRATEGIES", "KD_MACD_STRATEGIES",
          "KD_BOLLINGER_STRATEGIES", "ZONE_PV_STRATEGIES", "KD_PV_STRATEGIES"]


def all_strategies():
    seen, out = set(), {}
    for g in GROUPS:
        for name, fn in getattr(ind, g).items():
            if fn not in seen:
                seen.add(fn)
                out[name] = fn
    return out


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"樣本內": (start, split), "樣本外": (split + pd.Timedelta(days=1), df.index[-1]),
               "全期間": (start, df.index[-1])}

    rows = []
    for name, fn in all_strategies().items():
        buy, sell = fn(df)
        row = {"策略": name}
        for p, (s, e) in periods.items():
            r = run(df, buy, sell, s, e)[0]["return"]
            row[f"{p}次數"] = len(r)
            row[f"{p}勝率%"] = 100 * (r > 0).mean() if len(r) else float("nan")
        rows.append(row)

    table = pd.DataFrame(rows).set_index("策略").sort_values("全期間勝率%", ascending=False)
    out = RESULTS
    out.mkdir(exist_ok=True)
    table.round(1).to_csv(out / f"{stock_id}_win_rate_ranking.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(table.round(0).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
