"""交叉混合前五名的規則零件，只用前 7 年（2017～2023）打分，再用後 3 年驗證。

零件：
  資金投入：原版(首買額度50%=總資產10%) / 中間(首買65%、實際投入≤80%、一天一檔) / 解讀二(首買80%、≤80%、一天一檔)
  分區：不分區 / 0050區2＋0056區3 / 0050區3＋0056區2
  套牢不佔名額：有 / 無
  EPS 轉負出場：有 / 無
  A 方案：無 / 完整A(滿1年回本賣＋補虧＋每半年加碼，需好標的) / 只每半年加碼 / 只滿1年回本賣(需好標的)
  持有上限：無 / 滿2年強制賣
  固定：R5（移出後有賺才看技術賣訊、移出不佔名額）、停利 20%
評分（皆以 40 種情境的 IRR 分布計算）：中位數、最差10%、標準差、中位數/標準差、中位數/|回撤中位數|、綜合排名。
用法：python robust_mix.py
"""
import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd

import portfolio_study as ps
import robust_study as rs
import oos_study as oos
from backtest import RESULTS

CAP = {
    "原版": {},
    "中間": {"one_per_day": True, "target_util": 0.8, "util_mode": "invested", "first": 0.65},
    "解讀二": {"one_per_day": True, "target_util": 0.8, "util_mode": "invested", "first": 0.8},
}
STALE = {"套牢不佔名額": {"stale_free_slot": True}, "": {}}
EPS = {"EPS轉負出場": {"exit_eps_loss": True}, "": {}}
APACK = {
    "": {},
    "完整A": {"target_schedule": [(0, 0.20), (365, 0.0)], "offset_loss": True, "offset_min_hold_days": 365,
            "time_add_days": 182, "need_candidate": True},
    "每半年加碼": {"time_add_days": 182},
    "滿1年回本賣(需好標的)": {"target_schedule": [(0, 0.20), (365, 0.0)], "need_candidate": True},
}
HOLD = {"": {}, "滿2年強制賣": {"max_hold_days": 730}}
R5 = {"removal_exit": "tech_profit", "free_slot_removed": True}
COOLDOWNS = (5, 10)
G = rs.G


def configs():
    out = {}
    for (cn, ck), (sn, sk), (en, ek), (an, ak), (hn, hk) in itertools.product(
            CAP.items(), STALE.items(), EPS.items(), APACK.items(), HOLD.items()):
        name = "·".join(x for x in (cn, sn, en, an, hn) if x)
        out[name] = {**ck, **sk, **ek, **ak, **hk, **R5}
    return out


CONFIGS = configs()


def one_is(task):
    name, split, start, cname, cd = task
    rs.RULES[name] = CONFIGS[name]
    return rs.one((name, split, start, cname, cd))


def one_oos(task):
    mode, name, split, start, cname, cd = task
    rs.RULES[name] = CONFIGS[name]
    return oos.one((mode, name, split, start, cname, cd))


def summarize(df, key):
    g = df.groupby(key).agg(情境數=("IRR", "size"), IRR中位數=("IRR", "median"),
                            IRR最差10=("IRR", lambda x: x.quantile(0.1)), IRR標準差=("IRR", "std"),
                            回撤中位數=("回撤", "median"), 回撤最差=("回撤", "min"), 最長持有=("最長持有", "max"))
    g["IRR/標準差"] = g["IRR中位數"] / g["IRR標準差"]
    g["IRR/回撤"] = g["IRR中位數"] / g["回撤中位數"].abs()
    ranks = sum(g[c].rank(ascending=False) for c in ("IRR中位數", "IRR最差10", "IRR/標準差", "IRR/回撤"))
    g["綜合排名"] = ranks.rank(method="min").astype(int)
    return g.sort_values("綜合排名")


def main():
    rs.setup()
    rs.RULES.update(CONFIGS)
    tasks = [(n, sp, st, c, cd) for n in CONFIGS for sp in rs.SPLITS for st in rs.STARTS for c in rs.CONTRIBS
             for cd in COOLDOWNS]
    print(f"前 7 年：{len(CONFIGS)} 種規則 × {len(rs.SPLITS)} 種分區 × {len(rs.STARTS) * len(rs.CONTRIBS) * len(COOLDOWNS)} 情境 = {len(tasks)} 次")
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=8)
    df = pd.DataFrame([dict(版本=t[0], 分區=t[1], 起始=t[2], 追加=t[3], 冷卻=t[4], IRR=i, 回撤=m, 最長持有=h, 超過2年比例=p)
                       for t, i, m, h, p in res])
    df.to_csv(RESULTS / "mix_in_sample_runs.csv", index=False, encoding="utf-8-sig")
    g = summarize(df, ["版本", "分區"])
    g.round(2).to_csv(RESULTS / "mix_in_sample_summary.csv", encoding="utf-8-sig")

    top = g.head(8).index.tolist()
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, cd) for n, sp in top for st in starts for c in oos.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], 分區=t[2], 起始=t[3], 追加=t[4], 冷卻=t[5], IRR=i, 回撤=m, 最長持有=h)
                       for t, i, m, h in res])
    do.to_csv(RESULTS / "mix_oos_runs.csv", index=False, encoding="utf-8-sig")
    go = do.groupby(["驗證", "版本", "分區"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(0.1)),
                                            IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"))
    go.round(2).to_csv(RESULTS / "mix_oos_summary.csv", encoding="utf-8-sig")

    with pd.option_context("display.width", 300, "display.max_rows", 60, "display.unicode.east_asian_width", True):
        print("\n【前 7 年綜合排名前 20】")
        print(g.head(20).round(2).to_string())
        print("\n【前 8 名的後 3 年驗證】")
        for mode in ("延續", "單獨"):
            print(f"-- {mode}")
            print(go.loc[mode].loc[top].round(1).to_string())


if __name__ == "__main__":
    main()
