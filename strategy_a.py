"""最終策略：A 版（報酬最高），只做多。每天收盤後執行，顯示回測成績與明天該做什麼。

進場（全部成立，收盤判斷、隔天開盤買）：
  1. 預估殖利率 >= 5%（EPS 法：最近四季 EPS × 近 3 年平均配息率 / 收盤價；已公告股利則用公告值）
  2. 技術買點，下列任一出現：
     - 多指標共振：近 3 日 KD/RSI/威廉/CCI 至少 3 個超賣 ＋ KD 金叉 ＋ 年線之上
     - 價量引線：爆量長下影線 或 爆量長紅
     - 布林KD：近 3 日觸布林下軌 ＋ KD<30 金叉
     - 混合：低檔區（近 5 日觸下軌且 K<30）＋ 爆量長下影線或爆量長紅
資金：首次 50%；收盤曾跌到首次買價 -15% 後加碼 30%，曾跌到 -30% 後再加碼 20%。
      跌到門檻後，之後任何一天出現爆量長下影線或爆量長紅、且收盤仍低於首次買價，就加碼。
出場：收盤價較平均成本獲利 >= 20% → 隔天開盤全部賣出；不停損

用法：python strategy_a.py [代號]
"""
import sys

import pandas as pd

from backtest import ROOT, WARMUP, load
from indicators import pv_triggers
from trail_exit_study import run, summary
from yield_entry_study import entries
from yield_study import forward_dividend_eps

TARGET, MIN_YIELD = 0.20, 5.0
SCHEME = (0.50, (0.30, 0.20), (-0.15, -0.30))  # 首買比例、各次加碼比例、加碼門檻
ADD_MODE = "armed_below_first"
ADD_STEPS = SCHEME[2]


def main(stock_id="2382"):
    df = load(stock_id)
    raw = pd.read_csv(ROOT / "data" / f"{stock_id}.csv", parse_dates=["date"]).set_index("date")
    dps, source = forward_dividend_eps(df, stock_id)
    yld = 100 * dps / raw["close"]
    sigs, add = entries(df)
    buy = sigs["任一"] & (yld >= MIN_YIELD)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    trades, equity = run(df, buy, add, start, df.index[-1], TARGET, add_mode=ADD_MODE, scheme=SCHEME)
    s = summary(trades, equity)

    print(f"【{stock_id} A 版回測 {equity.index[0]:%Y-%m-%d} ~ {equity.index[-1]:%Y-%m-%d}】")
    print(f"  {s['筆數']} 筆，已結案 {s['已結案']} 筆，勝率 {s['勝率%']:.0f}%，每筆平均 {s['每筆平均%']:.1f}%，"
          f"年化 {s['年化%']:.1f}%，最大回撤 {s['最大回撤%']:.1f}%")

    t = df.index[-1]
    close = raw["close"].iloc[-1]
    print(f"\n【{t:%Y-%m-%d} 狀態】收盤 {close:.1f}")
    print(f"  預估股利 {dps.iloc[-1]:.2f} 元（{source.iloc[-1]}），預估殖利率 {yld.iloc[-1]:.2f}%"
          f"，殖利率 5% 對應股價 {dps.iloc[-1] / MIN_YIELD * 100:.0f} 元")
    names = [n for n in sigs if n != "任一"]
    print("  技術買點：" + "、".join(f"{n.split('（')[0]}{'✔' if sigs[n].iloc[-1] else '✘'}" for n in names))

    open_tr = trades[trades["出場"].isna()]
    if open_tr.empty:
        if buy.iloc[-1]:
            print("\n→ 明天開盤：買進 50% 資金")
        else:
            reason = "殖利率未達 5%" if yld.iloc[-1] < MIN_YIELD else "沒有技術買點"
            print(f"\n→ 空手等待（{reason}）")
        return

    tr = open_tr.iloc[0]
    entry = tr["進場"]
    first = raw.loc[entry, "open"]
    # 用原始價格換算給使用者看（回測內部用含息價）
    gain = tr["報酬%"]
    adds = int(tr["加碼"])
    print(f"\n  持有中：{entry:%Y-%m-%d} 進場（首次買價約 {first:.1f}），已加碼 {adds} 次，"
          f"目前報酬 {gain:+.1f}%（含股利、扣成本）")
    if adds == 0:
        print(f"  停利價：收盤 >= 約 {first * (1 + 0.001425) * (1 + TARGET):.1f} 元（之後若除息或加碼會再變動）")
    adj_close = df["close"]
    since = adj_close.loc[entry:]
    adj_first = df.loc[entry, "open"]
    hit = sum(1 for st in ADD_STEPS if (since / adj_first - 1 <= st).any())
    trigger = pv_triggers(df)
    today_add = bool((trigger["wick_buy"] | trigger["pv_buy"]).iloc[-1])
    if adds < len(ADD_STEPS):
        level = first * (1 + ADD_STEPS[adds])
        armed = hit > adds
        print(f"  下一次加碼（加 {SCHEME[1][adds]:.0%}）：{'已觸發門檻，' if armed else f'收盤曾 <= {level:.1f} 元後，'}"
              f"出現爆量長下影線或爆量長紅且收盤 < {first:.1f} 元就加（今天{'有' if today_add else '沒有'}訊號）")
    if gain >= TARGET * 100:
        print("\n→ 明天開盤：全部賣出（已達 20%）")
    elif adds < len(ADD_STEPS) and hit > adds and close < first and add.iloc[-1]:
        print(f"\n→ 明天開盤：加碼 {SCHEME[1][adds]:.0%} 資金")
    else:
        print("\n→ 續抱，等獲利達 20% 或加碼條件")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
