"""拆帳（V1＋V2，各看全部 0050＋0056 電子股）時，其中一組持股上限改 3 檔。
組合：V1 3 檔＋V2 5 檔、V1 5 檔＋V2 3 檔、兩組都 3 檔、V1 3 檔＋V2 7 檔、V1 7 檔＋V2 3 檔，對照兩組都 5 檔。
每組資金各半。用法：python slots_split_study.py"""
import pandas as pd

import mix_v12 as mx
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

V1, V2 = mx.V1, mx.V2
def S(cfg, k): return {**cfg, "max_slots": k}
MIX = {
    "V1 5檔＋V2 5檔（對照）": (S(V1, 5), S(V2, 5), 0.5),
    "V1 3檔＋V2 5檔": (S(V1, 3), S(V2, 5), 0.5),
    "V1 5檔＋V2 3檔": (S(V1, 5), S(V2, 3), 0.5),
    "V1 3檔＋V2 3檔": (S(V1, 3), S(V2, 3), 0.5),
    "V1 3檔＋V2 7檔": (S(V1, 3), S(V2, 7), 0.5),
    "V1 7檔＋V2 3檔": (S(V1, 7), S(V2, 3), 0.5),
    "V1 4檔＋V2 4檔": (S(V1, 4), S(V2, 4), 0.5),
    "V1 3檔＋V2 5檔 (資金3:5)": (S(V1, 3), S(V2, 5), 3 / 8),
    "V1 5檔＋V2 3檔 (資金5:3)": (S(V1, 5), S(V2, 3), 5 / 8),
}


def main():
    po.setup()
    po.one_is, po.one_oos = mx.one_is, mx.one_oos
    for n, t in MIX.items():
        mx.MIXES[n] = t; po.CONFIGS[n] = {**V1}
    names = list(MIX)
    m = po.evaluate(names, "slotsplit")
    out = m.loc[names]
    out.round(2).to_csv(RESULTS / "slots_split_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())

    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    money = []
    for name in names:
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
    mo.round(1).to_csv(RESULTS / "slots_split_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】"); print(mo.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
