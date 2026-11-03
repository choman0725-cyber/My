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
from portfolio_electronics import CAPITAL, ELECTRONICS, POOL as _POOL

POOL = _POOL   # 正式版股票池（47 檔）；要重現 2026-11-01 以前的研究（電子 90 檔）先設 POOL = ELECTRONICS 再 setup()



def backtest_end():
    """回測資料截止日（2026-11-02 使用者：回測跟到最新、但自動）：股票池裡仍在市（最後報價距 TAIEX 最後日 10 天內）
    的股票，最後報價日的最小值＝「最近一個全池都更新完的交易日」。13:35 Yahoo 暫定只更新十檔，所以當天下午仍是前一個交易日；
    16:00 FinMind 全池更新後才會往前一天。只在 rules_research.BACKTEST_END 設 None 時使用；目前固定 2026-10-30。"""
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"].max()
    last = {}
    for sid in POOL:
        p = ps.UNI / "prices" / f"{sid}.csv"
        if p.exists():
            last[sid] = pd.Timestamp(pd.read_csv(p, usecols=["date"])["date"].iloc[-1])
    alive = [d for d in last.values() if d >= tai - pd.Timedelta(days=10)]
    return min(alive) if alive else tai

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


def setup(live=False, end=None):
    """live=True（每日程式）：用到最新一天。live=False（研究、驗證）：資料截到 end；end=None 用 rules_research.BACKTEST_END。"""
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()
    data, _ = pickle.loads((RESULTS / "portfolio_prepared.pkl").read_bytes())
    ps.attach_fundamentals(data, dates)
    zone = {e: {k: v.values for k, v in ps.membership(
        cons[(cons["etf"] == e) & cons["stock_id"].isin(POOL)], dates).items()} for e in ("0050", "0056")}
    member = ps.membership(cons[cons["stock_id"].isin(POOL)], dates)
    G.update(dates=dates, zone=zone, member=member, sub={k: v for k, v in data.items() if k in member},
             etf={e: ps.load_prices(e)[0]["close"].reindex(dates).ffill() for e in ("0050", "0056")})
    if not live:
        truncate(end or default_end())


def default_end():
    """研究預設截止日：rules_research.BACKTEST_END；None 才自動（backtest_end）。延後 import 避免循環。"""
    import rules_research as rr
    return rr.BACKTEST_END or backtest_end()


def truncate(cut):
    """把 G 裡的日曆、每檔陣列、成分股、分區、ETF、技術買點快取（有的話）全部截到 cut（含）為止。
    每日程式 --asof 與回測截止日共用；下市標記 last_n 比日曆長 1 代表仍在市。"""
    cut = pd.Timestamp(cut)
    keep = G["dates"] <= cut
    n_keep = int(keep.sum())
    if n_keep == len(keep):
        return
    G["dates"] = G["dates"][keep]
    for d in G["sub"].values():
        for k, v in list(d.items()):
            if isinstance(v, np.ndarray) and len(v) == len(keep):
                d[k] = v[:n_keep]
            elif isinstance(v, pd.DataFrame) and len(v) == len(keep):
                d[k] = v.iloc[:n_keep]
        d["last_n"] = d["last_n"] if d["last_n"] <= n_keep else n_keep + 1
    G["member"] = {k: v.iloc[:n_keep] for k, v in G["member"].items()}
    G["zone"] = {e: {k: v[:n_keep] for k, v in m.items()} for e, m in G["zone"].items()}
    G["etf"] = {e: v.iloc[:n_keep] for e, v in G["etf"].items()}
    if "sig" in G:
        G["sig"] = {e: {sid: v[:n_keep] for sid, v in m.items()} for e, m in G["sig"].items()}


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
    extra = ({"slot_split": sp} if isinstance(sp, dict) else      # dict＝自訂分區 {區名: (名額, {sid: bool 陣列})}（turnover_study 衛星名額）
             {"slot_split": {"0050": (sp[0], G["zone"]["0050"]), "0056": (sp[1], G["zone"]["0056"])}} if sp else {})
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib,
                    start_n=s_n, end_n=e_n, **kw, **extra)
    final = eq.iloc[-1] * CAPITAL
    rets = eq.pct_change()
    for n in (contrib or {}):
        d = dates[n]
        rets.loc[d] = (eq.loc[d] - contrib[n]) / eq.shift(1).loc[d] - 1
    nav = (1 + rets.fillna(0)).cumprod()
    held = (pd.to_datetime(tr["出場"]).fillna(dates[e_n]) - pd.to_datetime(tr["進場"])).dt.days   # 沒有成交時欄位不是日期型別
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
