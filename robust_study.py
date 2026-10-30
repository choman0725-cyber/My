"""穩健度測試（只用樣本內 2017～2023，最後三年 2024～2026 保留不碰）。

每個候選版本在 5 個起始日 × 4 種追加方式 × 3 種冷卻天數 = 60 種情境下各跑一次，
統計 IRR 的中位數、最差 10%、標準差，以及最大回撤、最長持有、持有超過 2 年的比例。
用法：python robust_study.py
"""
import itertools
import pickle
from multiprocessing import Pool

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import BUY_COST, RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, ELECTRONICS

IS_END = pd.Timestamp("2023-12-31")
STARTS = ["2017-01-03", "2017-07-03", "2018-01-02", "2018-07-02", "2019-01-02"]
CONTRIBS = {
    "不追加": {},
    "每年50萬": {y: 500_000 for y in range(2018, 2024)},
    "每年100萬": {y: 1_000_000 for y in range(2018, 2024)},
    "分段50/80萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}},
}
COOLDOWNS = (5, 7, 10)

_R5 = {"removal_exit": "tech_profit", "free_slot_removed": True}
_V2 = {"one_per_day": True, "target_util": 0.8, "util_mode": "invested", "first": 0.8}
RULES = {
    "①解讀二·R5·不停損(EPS轉負出場)": {**_V2, **_R5, "exit_eps_loss": True},
    "①解讀二·R5·滿2年強制賣": {**_V2, **_R5, "max_hold_days": 730},
    "①解讀二·R5·A＋需好標的": {**_V2, **_R5, "target_schedule": [(0, 0.20), (365, 0.0)], "offset_loss": True,
                              "offset_min_hold_days": 365, "time_add_days": 182, "need_candidate": True},
    "①解讀二·R1·不停損": {**_V2, "removal_exit": "immediate"},
    "①解讀二·R1·滿2年強制賣": {**_V2, "removal_exit": "immediate", "max_hold_days": 730},
    "②原版·套牢不佔名額·R5": {"stale_free_slot": True, **_R5},
    "②原版·套牢不佔名額·R5·滿2年強制賣": {"stale_free_slot": True, **_R5, "max_hold_days": 730},
}
SPLITS = {"不分區": None, "0050區2＋0056區3": (2, 3), "0050區3＋0056區2": (3, 2)}

G = {}


def setup():
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    ps.attach_fundamentals(data, dates)
    zone = {e: {k: v.values for k, v in ps.membership(
        cons[(cons["etf"] == e) & cons["stock_id"].isin(ELECTRONICS)], dates).items()} for e in ("0050", "0056")}
    member = ps.membership(cons[cons["stock_id"].isin(ELECTRONICS)], dates)
    G.update(dates=dates, zone=zone, member=member, sub={k: v for k, v in data.items() if k in member},
             etf={e: ps.load_prices(e)[0]["close"].reindex(dates).ffill() for e in ("0050", "0056")})


def one(task):
    rule, split, start, cname, cd = task
    dates = G["dates"]
    s_n = dates.get_indexer([pd.Timestamp(start)], method="bfill")[0]
    e_n = dates.get_indexer([IS_END], method="ffill")[0]
    sched = {y: a for y, a in CONTRIBS[cname].items() if dates[s_n].year < y}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched}
    contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
    flows = [CAPITAL] + list(sched.values())
    flow_dates = [dates[s_n]] + [dates[first_day[y]] for y in sched]
    if rule.startswith("ETF"):
        px = G["etf"][rule[-4:]]
        shares = sum(c * (1 - BUY_COST) / px.iloc[n] for c, n in zip(flows, [s_n] + list(first_day.values())))
        final = shares * px.iloc[e_n]
        seg = px.iloc[s_n:e_n + 1]
        return task, irr(flows, flow_dates, final, dates[e_n]), 100 * (seg / seg.cummax() - 1).min(), np.nan, np.nan
    kw = {**RULES[rule]}
    if "cooldown" not in kw:
        kw["cooldown"] = cd
    sp = SPLITS[split]
    extra = {"slot_split": {"0050": (sp[0], G["zone"]["0050"]), "0056": (sp[1], G["zone"]["0056"])}} if sp else {}
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib,
                    start_n=s_n, end_n=e_n, **kw, **extra)
    final = eq.iloc[-1] * CAPITAL
    rets = eq.pct_change()
    for n in (contrib or {}):
        d = dates[n]
        rets.loc[d] = (eq.loc[d] - contrib[n]) / eq.shift(1).loc[d] - 1
    nav = (1 + rets.fillna(0)).cumprod()
    held = (tr["出場"].fillna(dates[e_n]) - tr["進場"]).dt.days
    return (task, irr(flows, flow_dates, final, dates[e_n]), 100 * (nav / nav.cummax() - 1).min(),
            held.max() / 365 if len(held) else 0, 100 * (held > 730).mean() if len(held) else 0)


def main():
    setup()
    tasks = [(r, sp, st, c, cd) for r in RULES for sp in SPLITS for st in STARTS for c in CONTRIBS for cd in COOLDOWNS]
    tasks += [(f"ETF買進持有 {e}", "—", st, c, 0) for e in ("0050", "0056") for st in STARTS for c in CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one, tasks, chunksize=4)
    df = pd.DataFrame([dict(版本=t[0], 分區=t[1], 起始=t[2], 追加=t[3], 冷卻=t[4], IRR=i, 回撤=m, 最長持有=h, 超過2年比例=p)
                       for t, i, m, h, p in res])
    df.to_csv(RESULTS / "robust_in_sample_runs.csv", index=False, encoding="utf-8-sig")
    g = df.groupby(["版本", "分區"]).agg(情境數=("IRR", "size"), IRR中位數=("IRR", "median"),
                                       IRR最差10=("IRR", lambda x: x.quantile(0.1)), IRR最差=("IRR", "min"),
                                       IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"), 回撤最差=("回撤", "min"),
                                       最長持有=("最長持有", "max"), 超過2年比例=("超過2年比例", "mean"))
    g = g.sort_values("IRR中位數", ascending=False)
    g.round(2).to_csv(RESULTS / "robust_in_sample_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(g.round(1).to_string())


if __name__ == "__main__":
    main()
