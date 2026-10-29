"""逆勢策略＋虧損加碼＋基本面停損（只做多）。

資金配置：首次進場用 2/3 資金（1 單位），加碼用剩下 1/3（再加 0.5 單位 = 加碼 50%）。
進場：final_strategy.signals（多指標共振超賣 ＋ KD 金叉 ＋ 年線之上）
加碼（每筆最多一次）：收盤較首次進場價下跌 >= 10%，且當天出現
        爆量長下影線 或 爆量長紅（爆量 = 成交量 > 1.5 倍 20 日均量）
出場：收盤價較平均成本獲利 >= 15% 全部賣出；
      基本面停損：最近兩個已公布季度的季營收年增率都 < 0 → 全部賣出
      （月營收以次月 10 日公布計，季資料於該季最後一個月營收公布後才可用）
所有動作皆為收盤判斷、隔天開盤執行。

用法：python scale_in_study.py [代號]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import BUY_COST, ROOT, SELL_COST, WARMUP, load
from final_strategy import signals
from indicators import pv_triggers

FIRST, ADD = 2 / 3, 1 / 3
TAKE_PROFIT, ADD_DROP = 0.15, -0.10


def revenue_stop(df, stock_id):
    """回傳每日是否觸發基本面停損（無營收資料時回傳 None）。"""
    path = ROOT / "data" / f"{stock_id}_revenue.csv"
    if not path.exists():
        return None
    rev = pd.read_csv(path)
    rev["q"] = (rev["revenue_month"] - 1) // 3 + 1
    q = rev.groupby(["revenue_year", "q"]).agg(revenue=("revenue", "sum"), months=("revenue", "size")).reset_index()
    q = q[q["months"] == 3].sort_values(["revenue_year", "q"])
    q["yoy"] = q["revenue"] / q.groupby("q")["revenue"].shift(1) - 1
    q = q[q["revenue_year"] == q["revenue_year"].shift(4) + 1]  # 確認是連續季度
    q["bad"] = (q["yoy"] < 0) & (q["yoy"].shift(1) < 0)
    # 季末月份營收於次月 10 日公布
    q["available"] = pd.to_datetime(dict(year=q["revenue_year"], month=q["q"] * 3, day=1)) + pd.DateOffset(months=1, days=9)
    flag = q.set_index("available")["bad"]
    return flag.reindex(df.index.union(flag.index)).ffill().reindex(df.index).fillna(False).astype(bool)


def run(df, buy, add_trigger, fundamental_stop, start, end):
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    o, c, lo = df["open"].values, df["close"].values, df["low"].values
    buy, add_trigger = buy.fillna(False).values, add_trigger.fillna(False).values
    stop = fundamental_stop.values if fundamental_stop is not None else np.zeros(len(df), bool)

    cash, pos, trades, equity = 1.0, None, [], []
    for n, i in enumerate(idx):
        if n > 0:
            p = idx[n - 1]
            if pos is None and buy[p] and not stop[p]:
                invest = cash * FIRST
                pos = {"start": i, "first_price": o[i], "shares": invest * (1 - BUY_COST) / o[i],
                       "cost": invest, "added": None, "low": o[i]}
                cash -= invest
            elif pos is not None:
                avg = pos["cost"] / pos["shares"]
                reason = "停利" if c[p] / avg - 1 >= TAKE_PROFIT else "基本面停損" if stop[p] else None
                if reason:
                    proceeds = pos["shares"] * o[i] * (1 - SELL_COST)
                    trades.append({"進場": df.index[pos["start"]], "出場": df.index[i], "原因": reason,
                                   "加碼日": pos["added"], "投入": pos["cost"], "報酬%": 100 * (proceeds / pos["cost"] - 1),
                                   "最深套牢%": 100 * (pos["low"] / pos["first_price"] - 1), "持有日": i - pos["start"]})
                    cash += proceeds
                    pos = None
                elif pos["added"] is None and c[p] / pos["first_price"] - 1 <= ADD_DROP and add_trigger[p]:
                    invest = cash  # 剩下的 1/3
                    pos["shares"] += invest * (1 - BUY_COST) / o[i]
                    pos["cost"] += invest
                    pos["added"] = df.index[i]
                    cash = 0.0
        if pos is not None:
            pos["low"] = min(pos["low"], lo[i])
        equity.append(cash + (pos["shares"] * c[i] if pos else 0.0))

    if pos is not None:
        trades.append({"進場": df.index[pos["start"]], "出場": None, "原因": "持有中", "加碼日": pos["added"],
                       "投入": pos["cost"], "報酬%": 100 * (pos["shares"] * c[idx[-1]] * (1 - SELL_COST) / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first_price"] - 1), "持有日": idx[-1] - pos["start"]})
    return pd.DataFrame(trades), pd.Series(equity, index=df.index[idx])


def summary(trades, equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    closed = trades[trades["原因"] != "持有中"]
    return {"筆數": len(trades), "已結案": len(closed), "勝率%": 100 * (closed["報酬%"] > 0).mean(),
            "加碼次數": int(trades["加碼日"].notna().sum()), "基本面停損": int((trades["原因"] == "基本面停損").sum()),
            "每筆平均%": closed["報酬%"].mean(), "最長持有日": trades["持有日"].max(),
            "年化%": 100 * (equity.iloc[-1] ** (1 / years) - 1), "最大回撤%": 100 * (equity / equity.cummax() - 1).min()}


def main(stock_id="2382"):
    df = load(stock_id)
    buy, _ = signals(df)
    t = pv_triggers(df)
    add_trigger = t["wick_buy"] | t["pv_buy"]
    fstop = revenue_stop(df, stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    never = pd.Series(False, index=df.index)

    rows, detail = {}, None
    for name, add, stop in [("不加碼、不停損", never, None), ("加碼、不停損", add_trigger, None),
                            ("不加碼、基本面停損", never, fstop), ("加碼＋基本面停損", add_trigger, fstop)]:
        if stop is None and "基本面" in name:
            continue
        trades, equity = run(df, buy, add, stop, start, df.index[-1])
        rows[name] = summary(trades, equity)
        trades.to_csv(ROOT / "results" / f"{stock_id}_scale_in_{name}.csv", index=False, encoding="utf-8-sig")
        detail = trades
    if fstop is None:
        print("（尚無營收資料 data/%s_revenue.csv，略過基本面停損）" % stock_id)
    else:
        print("基本面停損觸發的期間：", fstop.astype(int).diff().pipe(lambda s: s[s != 0]).to_dict())
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(pd.DataFrame(rows).T.round(1).to_string())
        print()
        print(detail.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
