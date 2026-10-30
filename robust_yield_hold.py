"""停利到了但殖利率仍 >=5% 就續抱，直到殖利率 <5%。前 7 年 40 情境打分，後 3 年驗證。

底 A：不設上限首選（原版＋套牢不佔名額＋EPS轉負出場＋每半年加碼＋R5）
底 B：底 A ＋ Hc（停利逐步降低、滿 2 年強制賣）
用法：python robust_yield_hold.py
"""
from multiprocessing import Pool

import pandas as pd

import oos_study as oos
import robust_study as rs
from backtest import RESULTS
from robust_mix import COOLDOWNS, summarize

BASE = {"stale_free_slot": True, "exit_eps_loss": True, "time_add_days": 182,
        "removal_exit": "tech_profit", "free_slot_removed": True}
BASES = {"不設上限": {}, "Hc兩年上限": {"target_schedule": [(0, .20), (365, .15), (548, .10), (640, 0.0)], "max_hold_days": 730}}
YRULES = {
    "原停利": {},
    "Y1殖利率≥5%續抱": {"hold_yield": 5.0},
    "Y2＋保利(回落5%)": {"hold_yield": 5.0, "hold_yield_floor": 0.05},
    "Y3＋封頂40%": {"hold_yield": 5.0, "hold_yield_cap": 0.40},
    "Y4＋保利＋封頂": {"hold_yield": 5.0, "hold_yield_floor": 0.05, "hold_yield_cap": 0.40},
}
SPLITS = {"0050區2＋0056區3": (2, 3), "不分區": None}
CONFIGS = {f"{b}｜{y}": {**BASE, **bk, **yk} for b, bk in BASES.items() for y, yk in YRULES.items()}


def one_is(t):
    rs.RULES[t[0]] = CONFIGS[t[0]]
    return rs.one(t)


def one_oos(t):
    rs.RULES[t[1]] = CONFIGS[t[1]]
    return oos.one(t)


def main():
    rs.setup()
    rs.SPLITS.clear(); rs.SPLITS.update(SPLITS)
    tasks = [(n, sp, st, c, cd) for n in CONFIGS for sp in SPLITS for st in rs.STARTS for c in rs.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=8)
    df = pd.DataFrame([dict(版本=t[0], 分區=t[1], 起始=t[2], 追加=t[3], 冷卻=t[4], IRR=i, 回撤=m, 最長持有=h, 超過2年比例=p)
                       for t, i, m, h, p in res])
    df["底"] = df["版本"].str.split("｜").str[0]; df["規則"] = df["版本"].str.split("｜").str[1]
    df.to_csv(RESULTS / "yieldhold_in_sample_runs.csv", index=False, encoding="utf-8-sig")
    g = summarize(df, ["底", "規則", "分區"]).sort_index()
    g.round(2).to_csv(RESULTS / "yieldhold_in_sample_summary.csv", encoding="utf-8-sig")
    top = [(f"{b}｜{y}", sp) for b, y, sp in g.index]
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, cd) for n, sp in top for st in starts for c in oos.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], 分區=t[2], 起始=t[3], 追加=t[4], 冷卻=t[5], IRR=i, 回撤=m, 最長持有=h)
                       for t, i, m, h in res])
    go = do.groupby(["驗證", "版本", "分區"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)),
                                            IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"), 最長持有=("最長持有", "max"))
    go.round(2).to_csv(RESULTS / "yieldhold_oos_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 80, "display.unicode.east_asian_width", True):
        print("【前 7 年】"); print(g.round(2).to_string())
        for mode in ("延續", "單獨"):
            print(f"\n【後 3 年 {mode}】"); print(go.loc[mode].sort_index().round(1).to_string())


if __name__ == "__main__":
    main()
