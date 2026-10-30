"""樣本外驗證（2024-01 ～ 2026-10），用 robust_study.py 在前 7 年選出的規則。

1. 延續：與樣本內相同的 5 個起始日一路跑到最新，只統計 2024 年起這段
   （2023 年底的持股與現金帶入；2023 年底資產當作期初投入，之後的追加照排程）。
2. 單獨：2024-01 / 2024-07 / 2025-01 重新以 500 萬開始，只跑後三年。
追加方式：不追加、每年 50 萬、每年 100 萬、分段（2018-20 每年 50 萬、21-23 每年 80 萬、24-26 每年 100 萬）。
用法：python oos_study.py
"""
from multiprocessing import Pool

import numpy as np
import pandas as pd

import portfolio_study as ps
import robust_study as rs
from backtest import BUY_COST, RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

OOS_START = pd.Timestamp("2024-01-01")
STARTS_FULL = rs.STARTS
STARTS_OOS = ["2024-01-02", "2024-07-01", "2025-01-02"]
CONTRIBS = {
    "不追加": {},
    "每年50萬": {y: 500_000 for y in range(2018, 2027)},
    "每年100萬": {y: 1_000_000 for y in range(2018, 2027)},
    "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)},
                    **{y: 1_000_000 for y in (2024, 2025, 2026)}},
}
G = rs.G


def nav_dd(eq, contrib):
    rets = eq.pct_change()
    for n in (contrib or {}):
        d = G["dates"][n]
        if d in rets.index and d != eq.index[0]:
            rets.loc[d] = (eq.loc[d] - contrib[n]) / eq.shift(1).loc[d] - 1
    nav = (1 + rets.fillna(0)).cumprod()
    return 100 * (nav / nav.cummax() - 1).min()


def one(task):
    mode, rule, split, start, cname, cd = task
    dates = G["dates"]
    s_n = dates.get_indexer([pd.Timestamp(start)], method="bfill")[0]
    e_n = len(dates) - 1
    o_n = dates.get_indexer([OOS_START], method="bfill")[0]
    sched = {y: a for y, a in CONTRIBS[cname].items() if dates[s_n].year < y}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched}
    contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None

    if rule.startswith("ETF"):
        px = G["etf"][rule[-4:]]
        shares = np.cumsum([0.0] * 0 + [0.0])  # 佔位
        buys = [(s_n, CAPITAL)] + [(first_day[y], a) for y, a in sched.items()]
        hold = lambda upto: sum(c * (1 - BUY_COST) / px.iloc[n] for n, c in buys if n <= upto)
        if mode == "延續":
            v0 = hold(o_n - 1) * px.iloc[o_n - 1]
            later = [(n, c) for n, c in buys if n >= o_n]
            flows, fdates = [v0] + [c for _, c in later], [dates[o_n - 1]] + [dates[n] for n, _ in later]
        else:
            flows, fdates = [c for _, c in buys], [dates[n] for n, _ in buys]
        final = hold(e_n) * px.iloc[e_n]
        seg = px.iloc[(o_n if mode == "延續" else s_n):e_n + 1]
        return task, irr(flows, fdates, final, dates[e_n]), 100 * (seg / seg.cummax() - 1).min(), np.nan

    kw = {**rs.RULES[rule], "cooldown": cd}
    sp = rs.SPLITS[split]
    extra = {"slot_split": {"0050": (sp[0], G["zone"]["0050"]), "0056": (sp[1], G["zone"]["0056"])}} if sp else {}
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib,
                    start_n=s_n, end_n=e_n, **kw, **extra)
    eq = eq * CAPITAL
    if mode == "延續":
        v0 = eq.loc[dates[o_n - 1]]
        later = {n: c * CAPITAL for n, c in (contrib or {}).items() if n >= o_n}
        flows, fdates = [v0] + list(later.values()), [dates[o_n - 1]] + [dates[n] for n in later]
        seg = eq.loc[dates[o_n - 1]:]
        dd = nav_dd(seg / CAPITAL, {n: c / CAPITAL for n, c in later.items()})
        t = tr[tr["進場"] >= OOS_START]
    else:
        flows = [CAPITAL] + [c * CAPITAL for c in (contrib or {}).values()]
        fdates = [dates[s_n]] + [dates[n] for n in (contrib or {})]
        dd = nav_dd(eq / CAPITAL, contrib)
        t = tr
    held = (t["出場"].fillna(dates[e_n]) - t["進場"]).dt.days
    return task, irr(flows, fdates, eq.iloc[-1], dates[e_n]), dd, held.max() / 365 if len(held) else 0


def main():
    rs.setup()
    tasks = []
    for mode, starts in (("延續", STARTS_FULL), ("單獨", STARTS_OOS)):
        tasks += [(mode, r, sp, st, c, cd) for r in rs.RULES for sp in rs.SPLITS for st in starts
                  for c in CONTRIBS for cd in rs.COOLDOWNS]
        tasks += [(mode, f"ETF買進持有 {e}", "—", st, c, 0) for e in ("0050", "0056") for st in starts for c in CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one, tasks, chunksize=4)
    df = pd.DataFrame([dict(驗證=t[0], 版本=t[1], 分區=t[2], 起始=t[3], 追加=t[4], 冷卻=t[5], IRR=i, 回撤=m, 最長持有=h)
                       for t, i, m, h in res])
    df.to_csv(RESULTS / "oos_runs.csv", index=False, encoding="utf-8-sig")
    g = df.groupby(["驗證", "版本", "分區"]).agg(情境數=("IRR", "size"), IRR中位數=("IRR", "median"),
                                              IRR最差10=("IRR", lambda x: x.quantile(0.1)), IRR標準差=("IRR", "std"),
                                              回撤中位數=("回撤", "median"), 回撤最差=("回撤", "min"))
    ins = pd.read_csv(RESULTS / "robust_in_sample_summary.csv", index_col=[0, 1])
    g = g.join(ins[["IRR中位數", "IRR最差10"]].rename(columns=lambda c: "前7年" + c), on=["版本", "分區"])
    g.round(2).to_csv(RESULTS / "oos_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        for mode in ("延續", "單獨"):
            print(f"【{mode}】")
            print(g.loc[mode].sort_values("IRR中位數", ascending=False).round(1).to_string(), "\n")


if __name__ == "__main__":
    main()
