"""逆勢（超賣進場）策略深化研究，只做多。

組合 = 進場訊號 × 長期趨勢濾網 × 出場方式 × 風控，全部事先定好。
挑選只用樣本內（前 N 年）：年交易 1.5~4 次中勝率最高者；樣本外只用來驗證。

出場規則（收盤判斷、隔天開盤執行）：
  訊號：該指標的超買訊號
  停利 10% / 15%：收盤獲利達標，或先出現超買訊號
風控：
  無 / 停損 -15%（收盤虧損達 15%）/ 時間停損 120 個交易日

用法：python meanrev_study.py [代號] [樣本內年數]
"""
import itertools
import sys

import numpy as np
import pandas as pd

from backtest import BUY_COST, ROOT, SELL_COST, WARMUP, load
from indicators import cci_line, cross_down, cross_up, kd, rsi, sma, williams_r


def _recent(cond, n=3):
    return cond.fillna(False).astype(int).rolling(n).max().astype(bool)


LEVELS = {  # 超賣門檻（KD, RSI, 威廉, CCI）；超買為對稱值
    "嚴格": (15, 25, -85, -150),
    "標準": (20, 30, -80, -100),
    "寬鬆": (25, 35, -75, -75),
}


def resonance(df, level="標準", need=2, window=3):
    """多指標共振：近 window 日內有 need 個以上指標超賣，且當天 KD 金叉 → 買；超買對稱 → 賣。"""
    kl, rl, wl, cl = LEVELS[level]
    k, d = kd(df)
    r, wr, cc = rsi(df["close"]), williams_r(df), cci_line(df)
    n_os = sum(_recent(x, window).astype(int) for x in (k < kl, r < rl, wr < wl, cc < cl))
    n_ob = sum(_recent(x, window).astype(int) for x in (k > 100 - kl, r > 100 - rl, wr > -100 - wl, cc > -cl))
    return (n_os >= need) & cross_up(k, d), (n_ob >= need) & cross_down(k, d)


def entry_exit_signals(df):
    c = df["close"]
    k, d = kd(df)
    r = rsi(c)
    wr = williams_r(df)
    cc = cci_line(df)
    s = lambda v: pd.Series(v, index=df.index)
    return {
        "KD<20 金叉": (cross_up(k, d) & (k < 20), cross_down(k, d) & (k > 80)),
        "RSI 回升 30": (cross_up(r, s(30)), cross_down(r, s(70))),
        "威廉 回升 -80": (cross_up(wr, s(-80)), cross_down(wr, s(-20))),
        "CCI 回升 -100": (cross_up(cc, s(-100)), cross_down(cc, s(100))),
        "多指標共振": resonance(df),
    }


def trend_filters(df):
    c = df["close"]
    ma120, ma240 = sma(c, 120), sma(c, 240)
    return {
        "無濾網": pd.Series(True, index=df.index),
        "年線之上": c > ma240,
        "半年線上揚": ma120 > ma120.shift(20),
    }


EXITS = {"超買訊號": None, "停利10%": 0.10, "停利15%": 0.15}
RISKS = {"無停損": {}, "停損-15%": {"stop": -0.15}, "持有上限120日": {"max_days": 120}}


def run_trades(df, buy, sell, start, end, tp=None, stop=None, max_days=None):
    period = np.flatnonzero((df.index >= start) & (df.index <= end))
    o, c, lo = df["open"].values, df["close"].values, df["low"].values
    buy, sell = buy.fillna(False).values, sell.fillna(False).values
    trades, equity, cash, pos = [], [], 1.0, None
    for n, i in enumerate(period):
        if n > 0:
            p = period[n - 1]
            if pos is None and buy[p]:
                pos = {"i": i, "price": o[i], "shares": cash * (1 - BUY_COST) / o[i], "value": cash, "low": o[i]}
                cash = 0.0
            elif pos is not None:
                gain = c[p] / pos["price"] - 1
                held = p - pos["i"] + 1
                exit_now = (sell[p] or (tp is not None and gain >= tp) or (stop is not None and gain <= stop)
                            or (max_days is not None and held >= max_days))
                if exit_now:
                    cash = pos["shares"] * o[i] * (1 - SELL_COST)
                    trades.append((df.index[pos["i"]], df.index[i], cash / pos["value"] - 1, pos["low"] / pos["price"] - 1, i - pos["i"]))
                    pos = None
        if pos is not None:
            pos["low"] = min(pos["low"], lo[i])
        equity.append(cash if pos is None else pos["shares"] * c[i])
    open_trade = pos is not None
    if open_trade:
        i = period[-1]
        cash = pos["shares"] * c[i] * (1 - SELL_COST)
        trades.append((df.index[pos["i"]], df.index[i], cash / pos["value"] - 1, pos["low"] / pos["price"] - 1, i - pos["i"]))
        equity[-1] = cash
    t = pd.DataFrame(trades, columns=["entry", "exit", "return", "mae", "bars"])
    return t, pd.Series(equity, index=df.index[period]), open_trade


def stats(t, eq, open_trade):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    r = t["return"]
    closed = r.iloc[:-1] if open_trade else r
    return {
        "次數": len(r),
        "年均次數": len(r) / years,
        "勝率%": 100 * (r > 0).mean() if len(r) else np.nan,
        "已結案勝率%": 100 * (closed > 0).mean() if len(closed) else np.nan,
        "每筆平均%": 100 * r.mean() if len(r) else np.nan,
        "最差一筆%": 100 * r.min() if len(r) else np.nan,
        "最深套牢%": 100 * t["mae"].min() if len(r) else np.nan,
        "最長持有日": t["bars"].max() if len(r) else np.nan,
        "年化%": 100 * (eq.iloc[-1] ** (1 / years) - 1),
        "最大回撤%": 100 * (eq / eq.cummax() - 1).min(),
        "期末未平倉": open_trade,
    }


def main(stock_id="2382", in_sample_years=7):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"IS": (start, split), "OOS": (split + pd.Timedelta(days=1), df.index[-1])}

    sigs, filters = entry_exit_signals(df), trend_filters(df)
    rows = []
    for (en, (buy, sell)), (fn, f), (xn, tp), (rn, risk) in itertools.product(
            sigs.items(), filters.items(), EXITS.items(), RISKS.items()):
        row = {"進場": en, "濾網": fn, "出場": xn, "風控": rn}
        for p, (s, e) in periods.items():
            for key, val in stats(*run_trades(df, buy & f, sell, s, e, tp=tp, **risk)).items():
                row[f"{p}_{key}"] = val
        rows.append(row)
    table = pd.DataFrame(rows)

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    table.round(2).to_csv(out / f"{stock_id}_meanrev_grid.csv", index=False, encoding="utf-8-sig")

    eligible = table[(table["IS_年均次數"] >= 1.5) & (table["IS_年均次數"] <= 4)]
    top = eligible.sort_values(["IS_勝率%", "IS_每筆平均%"], ascending=False).head(10)
    cols = ["進場", "濾網", "出場", "風控", "IS_次數", "IS_勝率%", "IS_每筆平均%", "IS_最深套牢%", "IS_年化%",
            "OOS_次數", "OOS_勝率%", "OOS_已結案勝率%", "OOS_每筆平均%", "OOS_最深套牢%", "OOS_年化%", "OOS_最大回撤%"]
    with pd.option_context("display.width", 300, "display.max_columns", 30, "display.unicode.east_asian_width", True):
        print(f"共 {len(table)} 組，樣本內年均 1.5~4 次的有 {len(eligible)} 組\n")
        print("【樣本內勝率前 10 名，及其樣本外表現】")
        print(top[cols].round(1).to_string(index=False))
        print("\n【符合頻率的組合，樣本外勝率分布】")
        print(eligible["OOS_勝率%"].describe().round(1).to_string())
    return table


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
