"""殖利率 5%（EPS 法）× 技術進場 × 分批出場（只做多）。

階段一（同 yield_study）：首次 40% 資金，下跌 10/20/30% 且爆量下影線/長紅時各加碼 20%。
階段二：收盤較平均成本獲利 >= 15% → 隔天開盤賣出一半。
階段三（剩下一半）：
  出場與順勢加碼各用三套判斷（爆量 = 成交量 > 1.5 倍 20 日均量）：
    價量＋引線：
      出場 = 爆量長上影線、爆量長黑、或價創 20 日新高但量縮
      加碼 = 爆量長紅 或 爆量長下影線
    布林＋KD：
      出場 = 高檔區（近 5 日觸上軌且 K>70）KD 死叉，或收盤跌破布林中軌
      加碼 = 收盤在中軌之上且 KD 金叉
    混合（布林＋KD 判斷位置，價量＋引線決定時機）：
      出場 = 高檔區內出現價量＋引線出場訊號，或收盤跌破布林中軌
      加碼 = 收盤在中軌之上且 K>D 時，出現價量＋引線加碼訊號
  保本：收盤跌回平均成本以下 → 全部賣出
  順勢加碼最多一次，把賣一半拿回的錢再買回去
所有動作皆收盤判斷、隔天開盤執行。

用法：python partial_exit_study.py [代號]
"""
import sys

import numpy as np
import pandas as pd

from backtest import BUY_COST, ROOT, SELL_COST, WARMUP, load
from final_strategy import signals
from indicators import bollinger, cross_down, cross_up, kd, pv_triggers, setup_zones
from yield_study import ADD, ADD_STEPS, FIRST, MAX_ADDS, TAKE_PROFIT, forward_dividend_eps


def run(df, buy, add_trigger, rest_exit, pyramid, start, end):
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    o, c, lo = df["open"].values, df["close"].values, df["low"].values
    buy, add_trigger = buy.fillna(False).values, add_trigger.fillna(False).values
    rest_exit = rest_exit.fillna(False).values
    pyramid = pyramid.fillna(False).values if pyramid is not None else np.zeros(len(df), bool)

    cash, pos, trades, equity = 1.0, None, [], []

    def close_trade(i, reason):
        nonlocal cash, pos
        proceeds = pos["shares"] * o[i] * (1 - SELL_COST)
        cash += proceeds
        pos["received"] += proceeds
        trades.append({"進場": df.index[pos["start"]], "賣一半": pos["half_date"], "出場": df.index[i], "出場原因": reason,
                       "下跌加碼": pos["adds"], "順勢加碼": pos["pyramid"],
                       "報酬%": 100 * (pos["received"] / pos["invested"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": i - pos["start"]})
        pos = None

    for n, i in enumerate(idx):
        if n > 0:
            p = idx[n - 1]
            if pos is None:
                if buy[p]:
                    base = cash
                    invest = base * FIRST
                    pos = {"start": i, "first": o[i], "shares": invest * (1 - BUY_COST) / o[i], "cost": invest,
                           "invested": invest, "received": 0.0, "base": base, "adds": 0, "low": o[i],
                           "half_date": None, "pyramid": False, "half_cash": 0.0}
                    cash -= invest
            elif pos["half_date"] is None:
                avg = pos["cost"] / pos["shares"]
                if c[p] / avg - 1 >= TAKE_PROFIT:
                    sell = pos["shares"] / 2
                    proceeds = sell * o[i] * (1 - SELL_COST)
                    pos["shares"] -= sell
                    pos["cost"] /= 2
                    pos["received"] += proceeds
                    pos["half_date"], pos["half_cash"] = df.index[i], proceeds
                    cash += proceeds
                elif (pos["adds"] < MAX_ADDS and add_trigger[p]
                      and c[p] / pos["first"] - 1 <= ADD_STEPS[pos["adds"]]):
                    invest = min(cash, pos["base"] * ADD)
                    pos["shares"] += invest * (1 - BUY_COST) / o[i]
                    pos["cost"] += invest
                    pos["invested"] += invest
                    pos["adds"] += 1
                    cash -= invest
            else:
                avg = pos["cost"] / pos["shares"]
                if c[p] < avg:
                    close_trade(i, "保本")
                elif rest_exit[p]:
                    close_trade(i, "技術出場")
                elif not pos["pyramid"] and pyramid[p]:
                    invest = min(cash, pos["half_cash"])
                    pos["shares"] += invest * (1 - BUY_COST) / o[i]
                    pos["cost"] += invest
                    pos["invested"] += invest
                    pos["pyramid"] = True
                    cash -= invest
        if pos is not None:
            pos["low"] = min(pos["low"], lo[i])
        equity.append(cash + (pos["shares"] * c[i] if pos else 0.0))

    if pos is not None:
        i = idx[-1]
        value = pos["shares"] * c[i] * (1 - SELL_COST)
        trades.append({"進場": df.index[pos["start"]], "賣一半": pos["half_date"], "出場": None, "出場原因": "持有中",
                       "下跌加碼": pos["adds"], "順勢加碼": pos["pyramid"],
                       "報酬%": 100 * ((pos["received"] + value) / pos["invested"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": i - pos["start"]})
    return pd.DataFrame(trades), pd.Series(equity, index=df.index[idx])


def summary(trades, equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    closed = trades[trades["出場"].notna()]
    return {"筆數": len(trades), "已結案": len(closed), "勝率%": 100 * (closed["報酬%"] > 0).mean(),
            "每筆平均%": closed["報酬%"].mean(), "最好一筆%": trades["報酬%"].max(), "最差一筆%": trades["報酬%"].min(),
            "順勢加碼次數": int(trades["順勢加碼"].sum()), "平均持有日": trades["持有日"].mean(),
            "年化%": 100 * (equity.iloc[-1] ** (1 / years) - 1), "最大回撤%": 100 * (equity / equity.cummax() - 1).min()}


def main(stock_id="2382"):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    buy = signals(df)[0] & (100 * dps / raw_close >= 5)
    t = pv_triggers(df)
    add = t["wick_buy"] | t["pv_buy"]
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))

    _, mid, _ = bollinger(df)
    k, d = kd(df)
    _, high_zone, *_ = setup_zones(df)
    pv_sell = t["wick_sell"] | t["pv_sell"]
    pv_buy = t["wick_buy"] | t["pv_buy"]
    below_mid = df["close"] < mid
    exits = {
        "價量引線": pv_sell,
        "布林KD": (high_zone & cross_down(k, d)) | below_mid,
        "混合": (high_zone & pv_sell) | below_mid,
    }
    adds = {
        "不加碼": None,
        "價量引線加碼": pv_buy,
        "布林KD加碼": (df["close"] > mid) & cross_up(k, d),
        "混合加碼": (df["close"] > mid) & (k > d) & pv_buy,
    }

    rows, details = {}, {}
    # 基準：獲利 15% 全部賣出
    from yield_study import run_multi, summary as base_summary
    tr, eq = run_multi(df, buy, add, start, df.index[-1])
    s = base_summary(tr, eq)
    rows[("基準", "獲利15%全賣")] = {"筆數": s["筆數"], "已結案": s["已結案"], "勝率%": s["勝率%"], "每筆平均%": s["每筆平均%"],
                                 "最好一筆%": tr["報酬%"].max(), "最差一筆%": tr["報酬%"].min(), "順勢加碼次數": 0,
                                 "平均持有日": tr["持有日"].mean(), "年化%": s["年化%"], "最大回撤%": s["最大回撤%"]}
    for ename, ex in exits.items():
        for aname, pyr in adds.items():
            tr, eq = run(df, buy, add, ex, pyr, start, df.index[-1])
            rows[(f"出場:{ename}", aname)] = summary(tr, eq)
            details[(ename, aname)] = tr
            tr.to_csv(ROOT / "results" / f"{stock_id}_partial_{ename}_{aname}.csv", index=False, encoding="utf-8-sig")
    table = pd.DataFrame(rows).T
    table.round(2).to_csv(ROOT / "results" / f"{stock_id}_partial_exit_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        for key in (("價量引線", "不加碼"), ("價量引線", "價量引線加碼"), ("混合", "混合加碼")):
            print(f"【出場:{key[0]}＋{key[1]} 交易明細】")
            print(details[key].round(1).to_string(), "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
