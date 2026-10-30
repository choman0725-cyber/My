"""最終版本（Hc+Y4 不分區、不設上限+Y3 2+3）加上各種補虧方式，前 7 年 40 情境 + 後 3 年驗證。"""
from multiprocessing import Pool

import pandas as pd

import oos_study as oos
import robust_study as rs
from backtest import RESULTS
from robust_mix import COOLDOWNS, summarize

BASE = {"stale_free_slot": True, "exit_eps_loss": True, "time_add_days": 182,
        "removal_exit": "tech_profit", "free_slot_removed": True}
FINALS = {
    "首選Hc+Y4": ({**BASE, "target_schedule": [(0, .20), (365, .15), (548, .10), (640, 0.0)], "max_hold_days": 730,
                 "hold_yield": 5.0, "hold_yield_floor": 0.05, "hold_yield_cap": 0.40}, "不分區"),
    "不設上限+Y3": ({**BASE, "hold_yield": 5.0, "hold_yield_cap": 0.40}, "0050區2＋0056區3"),
}
OFFSETS = {
    "不補虧": {},
    "全部補虧": {"offset_loss": True},
    "只補套1年以上": {"offset_loss": True, "offset_min_hold_days": 365},
    "只補虧30%以上": {"offset_loss": True, "offset_only_deep": True},
    "補套1年以上＋需好標的": {"offset_loss": True, "offset_min_hold_days": 365, "need_candidate": True},
}
SPLITS = {"不分區": None, "0050區2＋0056區3": (2, 3)}
CONFIGS = {f"{f}｜{o}": ({**fk, **ok}, sp) for f, (fk, sp) in FINALS.items() for o, ok in OFFSETS.items()}


def one_is(t):
    rs.RULES[t[0]] = CONFIGS[t[0]][0]
    return rs.one(t)


def one_oos(t):
    rs.RULES[t[1]] = CONFIGS[t[1]][0]
    return oos.one(t)


def main():
    rs.setup()
    rs.SPLITS.clear(); rs.SPLITS.update(SPLITS)
    pairs = [(n, sp) for n, (_, sp) in CONFIGS.items()]
    tasks = [(n, sp, st, c, cd) for n, sp in pairs for st in rs.STARTS for c in rs.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=8)
    df = pd.DataFrame([dict(版本=t[0], 分區=t[1], 起始=t[2], 追加=t[3], 冷卻=t[4], IRR=i, 回撤=m, 最長持有=h, 超過2年比例=p)
                       for t, i, m, h, p in res])
    df["底"] = df["版本"].str.split("｜").str[0]; df["補虧"] = df["版本"].str.split("｜").str[1]
    g = summarize(df, ["底", "補虧"]).sort_index()
    g.round(2).to_csv(RESULTS / "offset_final_in_sample.csv", encoding="utf-8-sig")
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, cd) for n, sp in pairs for st in starts for c in oos.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], IRR=i, 回撤=m) for t, i, m, h in res])
    go = do.groupby(["驗證", "版本"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)),
                                      IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"))
    go.round(2).to_csv(RESULTS / "offset_final_oos.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print("【前 7 年】"); print(g[["IRR中位數", "IRR最差10", "IRR標準差", "回撤中位數", "回撤最差", "最長持有"]].round(2).to_string())
        for mode in ("延續", "單獨"):
            print(f"\n【後 3 年 {mode}】"); print(go.loc[mode].round(1).to_string())


if __name__ == "__main__":
    main()
