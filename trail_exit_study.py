"""獲利達標後不賣，改由技術線型決定賣點（只做多）。

殖利率 5%（EPS 法）＋技術買點；下跌 10/20/30% 且爆量下影線/長紅時各加碼 20%。
獲利（相對平均成本）達到門檻（15/20/30%）後啟動技術出場：
  價量引線：爆量長上影線、爆量長黑、或價創 20 日新高但量縮
  布林KD：高檔區（近 5 日觸上軌且 K>70）KD 死叉，或收盤跌破布林中軌
  混合：高檔區內出現價量引線出場訊號，或收盤跌破布林中軌
  啟動後若收盤跌回平均成本以下 → 保本全賣
比較基準：達到門檻就直接全賣。
用法：python trail_exit_study.py [代號]
"""
import sys

import numpy as np
import pandas as pd

from backtest import BUY_COST, ROOT, SELL_COST, WARMUP, load, RESULTS
from indicators import bollinger, cross_down, kd, pv_triggers, setup_zones
from yield_entry_study import entries
from yield_study import ADD, ADD_STEPS, FIRST, MAX_ADDS, forward_dividend_eps


def run(df, buy, add_trigger, start, end, target, tech_exit=None, add_mode="same_day", open_check=False,
        scheme=None, fill="next_open"):
    """add_mode：same_day＝跌到門檻當天須同時出現加碼訊號；
                 armed＝收盤曾跌到門檻即觸發，之後任何一天出現加碼訊號就加碼（股價回升也照加）；
                 armed_below_first＝同 armed，但股價已漲回首次買價以上就不加。
                 （「反彈回門檻之上就不加」等同 same_day：訊號當天收盤仍須在門檻之下。）
    open_check：隔天開盤價若已高於這次加碼的門檻價（首買價 × (1+門檻)），這次不加，資格保留。
    scheme：(首買比例, 每次加碼比例或各次比例, 加碼門檻) 覆寫模組預設。
    fill：next_open＝訊號隔天開盤成交；close＝訊號當天收盤價成交（盤後定價交易，假設都成交），
          交易日期仍記在隔天。"""
    FIRST, ADD, ADD_STEPS = scheme if scheme else (globals()["FIRST"], globals()["ADD"], globals()["ADD_STEPS"])
    MAX_ADDS = len(ADD_STEPS)
    if fill == "close":
        df = df.copy()
        df["open"] = df["close"].shift(1).fillna(df["open"])
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    o, c, lo, hi = df["open"].values, df["close"].values, df["low"].values, df["high"].values
    buy, add_trigger = buy.fillna(False).values, add_trigger.fillna(False).values
    tech = tech_exit.fillna(False).values if tech_exit is not None else None
    cash, pos, trades, equity = 1.0, None, [], []
    for n, i in enumerate(idx):
        if n > 0:
            p = idx[n - 1]
            if pos is None:
                if buy[p]:
                    base = cash
                    invest = base * FIRST
                    pos = {"start": i, "first": o[i], "shares": invest * (1 - BUY_COST) / o[i], "cost": invest,
                           "base": base, "adds": 0, "low": o[i], "peak": 0.0, "armed": None, "hit": 0}
                    cash -= invest
            else:
                gain = c[p] / (pos["cost"] / pos["shares"]) - 1
                reason = None
                if pos["armed"] is None and gain >= target:
                    if tech is None:
                        reason = "達標"
                    else:
                        pos["armed"] = df.index[p]
                elif pos["armed"] is not None:
                    reason = "保本" if gain < 0 else "技術出場" if tech[p] else None
                if reason:
                    proceeds = pos["shares"] * o[i] * (1 - SELL_COST)
                    trades.append({"進場": df.index[pos["start"]], "達標日": pos["armed"], "出場": df.index[i],
                                   "原因": reason, "加碼": pos["adds"], "報酬%": 100 * (proceeds / pos["cost"] - 1),
                                   "持有中最高獲利%": 100 * pos["peak"], "最深套牢%": 100 * (pos["low"] / pos["first"] - 1),
                                   "持有日": i - pos["start"]})
                    cash += proceeds
                    pos = None
                elif pos["armed"] is None and add_trigger[p] and (
                        (add_mode == "same_day" and pos["adds"] < MAX_ADDS
                         and c[p] / pos["first"] - 1 <= ADD_STEPS[pos["adds"]])
                        or (add_mode == "armed" and pos["adds"] < pos["hit"])
                        or (add_mode == "armed_below_first" and pos["adds"] < pos["hit"] and c[p] < pos["first"])) \
                        and not (open_check and o[i] > pos["first"] * (1 + ADD_STEPS[pos["adds"]])):
                    amount = ADD[pos["adds"]] if isinstance(ADD, (tuple, list)) else ADD
                    invest = min(cash, pos["base"] * amount)
                    pos["shares"] += invest * (1 - BUY_COST) / o[i]
                    pos["cost"] += invest
                    pos["adds"] += 1
                    cash -= invest
        if pos is not None:
            while pos["hit"] < MAX_ADDS and c[i] / pos["first"] - 1 <= ADD_STEPS[pos["hit"]]:
                pos["hit"] += 1
            pos["low"] = min(pos["low"], lo[i])
            pos["peak"] = max(pos["peak"], hi[i] / (pos["cost"] / pos["shares"]) - 1)
        equity.append(cash + (pos["shares"] * c[i] if pos else 0.0))
    if pos is not None:
        i = idx[-1]
        trades.append({"進場": df.index[pos["start"]], "達標日": pos["armed"], "出場": None, "原因": "持有中",
                       "加碼": pos["adds"], "報酬%": 100 * (pos["shares"] * c[i] * (1 - SELL_COST) / pos["cost"] - 1),
                       "持有中最高獲利%": 100 * pos["peak"], "最深套牢%": 100 * (pos["low"] / pos["first"] - 1),
                       "持有日": i - pos["start"]})
    return pd.DataFrame(trades), pd.Series(equity, index=df.index[idx])


def summary(trades, equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    closed = trades[trades["出場"].notna()]
    return {"筆數": len(trades), "已結案": len(closed), "勝率%": 100 * (closed["報酬%"] > 0).mean(),
            "每筆平均%": closed["報酬%"].mean(), "最好%": closed["報酬%"].max(), "最差%": closed["報酬%"].min(),
            "平均持有日": closed["持有日"].mean(), "年化%": 100 * (equity.iloc[-1] ** (1 / years) - 1),
            "最大回撤%": 100 * (equity / equity.cummax() - 1).min()}


def main(stock_id="2382"):
    df = load(stock_id)
    raw_close = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")["close"]
    dps, _ = forward_dividend_eps(df, stock_id)
    cheap = 100 * dps / raw_close >= 5
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    sigs, add = entries(df)

    t = pv_triggers(df)
    _, mid, _ = bollinger(df)
    k, d = kd(df)
    _, high_zone, *_ = setup_zones(df)
    pv_sell = t["wick_sell"] | t["pv_sell"]
    below_mid = df["close"] < mid
    exits = {"達標直接賣": None, "價量引線": pv_sell,
             "布林KD": (high_zone & cross_down(k, d)) | below_mid, "混合": (high_zone & pv_sell) | below_mid}

    rows, details = {}, {}
    for ename in ("混合（布林KD位置＋價量引線時機）", "任一"):
        for target in (0.15, 0.20, 0.30):
            for xname, ex in exits.items():
                tr, eq = run(df, sigs[ename] & cheap, add, start, df.index[-1], target, ex)
                key = (ename.split("（")[0], f"{target:.0%}", xname)
                rows[key] = summary(tr, eq)
                details[key] = tr
    table = pd.DataFrame(rows).T
    table.index.names = ["買點", "門檻", "出場"]
    table.round(2).to_csv(RESULTS / f"{stock_id}_trail_exit_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 50, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        best = table["年化%"].idxmax()
        print(f"【年化最高：{best}】")
        print(details[best].round(1).to_string())
        details[best].to_csv(RESULTS / f"{stock_id}_trail_exit_best_trades.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
