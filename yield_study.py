"""殖利率法 × 技術進場 × 分批加碼（只做多）。

預估殖利率 = 下一次會領到的現金股利 / 當日收盤價（未調整價）
  下一次會領到的股利 = 除息日還沒到的最早一個年度：
    - 該年度股利已公告（AnnouncementDate <= 當日）→ 直接用公告值
    - 尚未公告 → 前一年度股利 × 該年度已公布月營收累計 / 前一年度同期累計
  月營收以次月 10 日視為公布日，避免偷看未來。
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


def dividend_table(stock_id):
    div = pd.read_csv(ROOT / "data" / f"{stock_id}_dividend.csv")
    res = pd.read_csv(ROOT / "data" / f"{stock_id}_dividend_result.csv", parse_dates=["date"])
    div["fy"] = div["year"].str.extract(r"(\d+)")[0].astype(int) + 1911
    div["cash"] = div["CashEarningsDistribution"] + div["CashStatutorySurplus"]
    div["announced"] = pd.to_datetime(div["AnnouncementDate"])
    div["ex_date"] = pd.to_datetime(div["CashExDividendTradingDate"])
    table = div[["fy", "cash", "announced", "ex_date"]]
    # 股利政策缺漏的年度，用除權息結果補（公告日不明，保守視為除息日當天才知道）
    res["fy"] = res["date"].dt.year - 1
    missing = res[~res["fy"].isin(table["fy"])]
    extra = pd.DataFrame({"fy": missing["fy"], "cash": missing["stock_and_cache_dividend"],
                          "announced": missing["date"], "ex_date": missing["date"]})
    return pd.concat([table, extra]).sort_values("fy").set_index("fy")


def forward_dividend(df, stock_id):
    div = dividend_table(stock_id)
    rev = pd.read_csv(ROOT / "data" / f"{stock_id}_revenue.csv")
    rev["published"] = pd.to_datetime(dict(year=rev["revenue_year"], month=rev["revenue_month"], day=1)) \
        + pd.DateOffset(months=1, days=9)
    out = pd.Series(np.nan, index=df.index)
    source = pd.Series("", index=df.index)
    for t in df.index:
        pending = div[div["ex_date"] > t]
        fy = pending.index.min() if len(pending) else div.index.max() + 1
        if fy in div.index and div.loc[fy, "announced"] <= t:
            out[t], source[t] = div.loc[fy, "cash"], "已公告"
            continue
        if fy - 1 not in div.index:
            continue
        known = rev[(rev["published"] <= t) & (rev["revenue_year"] == fy)]
        if known.empty:
            continue
        months = known["revenue_month"]
        prev = rev[(rev["revenue_year"] == fy - 1) & rev["revenue_month"].isin(months)]
        out[t] = div.loc[fy - 1, "cash"] * known["revenue"].sum() / prev["revenue"].sum()
        source[t] = f"推估({len(months)}個月)"
    return out, source


# 季報法定公布期限（季末後）：Q1 5/15、Q2 8/14、Q3 11/14、Q4（年報）隔年 3/31
REPORT_DEADLINE = {3: (5, 15), 6: (8, 14), 9: (11, 14), 12: (3, 31)}


def quarterly_eps(stock_id):
    fin = pd.read_csv(ROOT / "data" / f"{stock_id}_financials.csv", parse_dates=["date"])
    eps = fin[fin["type"] == "EPS"][["date", "value"]].rename(columns={"date": "quarter_end", "value": "eps"})
    eps = eps.sort_values("quarter_end").reset_index(drop=True)

    def published(q):
        m, d = REPORT_DEADLINE[q.month]
        return pd.Timestamp(q.year + (q.month == 12), m, d)
    eps["published"] = eps["quarter_end"].map(published)
    eps["fy"] = eps["quarter_end"].dt.year
    return eps


def forward_dividend_eps(df, stock_id, payout_years=3):
    """預估股利 = 最近四季 EPS（已公布者）× 近 N 年平均配息率；已公告就用公告值。"""
    div = dividend_table(stock_id)
    eps = quarterly_eps(stock_id)
    annual_eps = eps.groupby("fy")["eps"].agg(["sum", "size"])
    annual_eps = annual_eps[annual_eps["size"] == 4]["sum"]
    payout = (div["cash"] / annual_eps).dropna()
    out = pd.Series(np.nan, index=df.index)
    source = pd.Series("", index=df.index)
    for t in df.index:
        pending = div[div["ex_date"] > t]
        fy = pending.index.min() if len(pending) else div.index.max() + 1
        if fy in div.index and div.loc[fy, "announced"] <= t:
            out[t], source[t] = div.loc[fy, "cash"], "已公告"
            continue
        known = eps[eps["published"] <= t]
        if len(known) < 4:
            continue
        ttm = known["eps"].iloc[-4:].sum()
        # 配息率只用當時已知（已公告）的年度
        known_payout = payout[[y for y in payout.index if div.loc[y, "announced"] <= t]].iloc[-payout_years:]
        if known_payout.empty:
            continue
        out[t] = ttm * known_payout.mean()
        source[t] = f"EPS推估(TTM={ttm:.2f},配息率={known_payout.mean():.0%})"
    return out, source


def main(stock_id="2382"):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, source = forward_dividend(df, stock_id)
    yld = 100 * dps / raw_close
    buy, _ = signals(df)
    t = pv_triggers(df)
    add = t["wick_buy"] | t["pv_buy"]
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))

    pd.DataFrame({"收盤": raw_close, "預估股利": dps.round(2), "來源": source, "預估殖利率%": yld.round(2)}) \
        .to_csv(ROOT / "results" / f"{stock_id}_forward_yield.csv", encoding="utf-8-sig")
    yearly = yld[start:].groupby(yld[start:].index.year).agg(["min", "median", "max"]).round(1)
    yearly["殖利率>=5%天數"] = (yld[start:] >= 5).groupby(yld[start:].index.year).sum()

    rows, details = {}, {}
    for th in (None, 3, 4, 5):
        b = buy if th is None else buy & (yld >= th)
        name = "不看殖利率" if th is None else f"殖利率>={th}%"
        tr, eq = run_multi(df, b, add, start, df.index[-1])
        rows[name] = summary(tr, eq)
        details[name] = tr
        tr.to_csv(ROOT / "results" / f"{stock_id}_yield_{th or 'none'}_trades.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print("【每年預估殖利率%】\n", yearly.to_string(), "\n")
        print(pd.DataFrame(rows).T.round(1).to_string(), "\n")
        for name in ("殖利率>=5%", "殖利率>=4%"):
            print(f"【{name} 交易明細】")
            print(details[name].to_string(), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
