"""最多持有兩年的出場方式 × 整張資金處理方式，用前 7 年 40 情境打分，再用後 3 年驗證。

底：原版＋套牢不佔名額＋EPS轉負出場＋每半年加碼＋R5（robust_mix 首選）。
用法：python robust_hold.py
"""
from multiprocessing import Pool

import pandas as pd

import oos_study as oos
import robust_study as rs
from backtest import RESULTS
from robust_mix import COOLDOWNS, summarize

BASE = {"stale_free_slot": True, "exit_eps_loss": True, "time_add_days": 182,
        "removal_exit": "tech_profit", "free_slot_removed": True}
HOLDS = {
    "不設上限": {},
    "H0滿2年強制賣": {"max_hold_days": 730},
    "Hb滿1.5年停利10%": {"target_schedule": [(0, .20), (548, .10)], "max_hold_days": 730},
    "Hc逐步降停利(15/10/回本)": {"target_schedule": [(0, .20), (365, .15), (548, .10), (640, 0.0)], "max_hold_days": 730},
    "Hd滿1.5年回本賣": {"target_schedule": [(0, .20), (548, 0.0)], "max_hold_days": 730},
    "He滿1年有好標的回本換": {"target_schedule": [(0, .20), (365, 0.0)], "need_candidate": True, "max_hold_days": 730},
    "Hf滿1.5年有賺遇技術賣訊": {"late_tech_days": 548, "max_hold_days": 730},
    "Hg=Hb+Hf": {"target_schedule": [(0, .20), (548, .10)], "late_tech_days": 548, "max_hold_days": 730},
}
LOTS = {"零股": None, "放棄": "skip", "調用未來資金": "borrow"}
SPLITS = {"0050區2＋0056區3": (2, 3), "不分區": None}
CONFIGS = {f"{h}｜{l}": {**BASE, **hk, "lot_mode": lm} for h, hk in HOLDS.items() for l, lm in LOTS.items()}


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
    df["出場"] = df["版本"].str.split("｜").str[0]
    df["張數"] = df["版本"].str.split("｜").str[1]
    df.to_csv(RESULTS / "hold_in_sample_runs.csv", index=False, encoding="utf-8-sig")
    g = summarize(df, ["出場", "張數", "分區"])
    g.round(2).to_csv(RESULTS / "hold_in_sample_summary.csv", encoding="utf-8-sig")

    top = [(f"{h}｜{l}", sp) for h, l, sp in g.head(10).index]
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, cd) for n, sp in top for st in starts for c in oos.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], 分區=t[2], 起始=t[3], 追加=t[4], 冷卻=t[5], IRR=i, 回撤=m, 最長持有=h)
                       for t, i, m, h in res])
    do.to_csv(RESULTS / "hold_oos_runs.csv", index=False, encoding="utf-8-sig")
    go = do.groupby(["驗證", "版本", "分區"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)),
                                            IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"), 最長持有=("最長持有", "max"))
    go.round(2).to_csv(RESULTS / "hold_oos_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 80, "display.unicode.east_asian_width", True):
        print("【前 7 年：出場方式 × 張數處理 × 分區】")
        print(g.round(2).to_string())
        print("\n【前 7 年：只看張數處理（各出場方式平均）】")
        print(df.groupby("張數")["IRR"].agg(["median", lambda x: x.quantile(.1), "std"]).round(2).to_string())
        print("\n【前 10 名的後 3 年驗證】")
        for mode in ("延續", "單獨"):
            print(f"-- {mode}")
            print(go.loc[mode].loc[top].round(1).to_string())


if __name__ == "__main__":
    main()
