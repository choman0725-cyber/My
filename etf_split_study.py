"""拆帳 ＋ 分範圍：一個帳戶只買 0050 成分股、另一個只買 0056 成分股，各自最多 5 檔。
組合：V1/V2 × 0050/0056 的四種配法，以及同規則分範圍，對照不分範圍的五五拆帳與單一帳戶只看 0050 / 只看 0056。
用法：python etf_split_study.py"""
import pandas as pd

import mix_v12 as mx
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

V1, V2 = mx.V1, mx.V2
MIX = {
    "拆帳｜V1 全部＋V2 全部": (V1, V2, 0.5),
    "拆帳｜V1 只0050＋V2 只0056": (V1, V2, 0.5, "0050", "0056"),
    "拆帳｜V2 只0050＋V1 只0056": (V2, V1, 0.5, "0050", "0056"),
    "拆帳｜V1 只0050＋V1 只0056": (V1, V1, 0.5, "0050", "0056"),
    "拆帳｜V2 只0050＋V2 只0056": (V2, V2, 0.5, "0050", "0056"),
    "拆帳｜V1 只0050＋V2 只0056 (4:6)": (V1, V2, 0.4, "0050", "0056"),
    "拆帳｜V1 只0050＋V2 只0056 (6:4)": (V1, V2, 0.6, "0050", "0056"),
    "單帳戶｜V1 只0050": (V1, V1, 1.0, "0050", "0050"),
    "單帳戶｜V1 只0056": (V1, V1, 1.0, "0056", "0056"),
    "單帳戶｜V2 只0050": (V2, V2, 1.0, "0050", "0050"),
    "單帳戶｜V2 只0056": (V2, V2, 1.0, "0056", "0056"),
}


def main():
    po.setup()
    po.one_is, po.one_oos = mx.one_is, mx.one_oos
    for n, t in MIX.items():
        mx.MIXES[n] = t; po.CONFIGS[n] = {**V1}
    names = list(MIX)
    m = po.evaluate(names, "etfsplit")
    out = m.loc[names]
    out.round(2).to_csv(RESULTS / "etf_split_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())

    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    money = []
    for name in names[:5]:
        mx._prep(name); kw = rs.RULES[name]
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, **kw)
            flows = [CAPITAL] + list(sched.values()); fdates = [dates[1]] + [dates[first_day[y]] for y in sched]
            final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for n in (contrib or {}):
                rets.loc[dates[n]] = (eq.loc[dates[n]] - contrib[n]) / eq.shift(1).loc[dates[n]] - 1
            nav = (1 + rets.fillna(0)).cumprod()
            closed = tr[tr["出場"].notna()]
            money.append(dict(版本=name, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                              IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                              筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(), 最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
    ps.run = mx._orig_run
    mo = pd.DataFrame(money)
    mo.round(1).to_csv(RESULTS / "etf_split_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】"); print(mo.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
