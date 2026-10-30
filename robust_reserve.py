"""冷卻期 × 加碼讓位給新買點，套在三個底上；前 7 年 40 情境＋後 3 年驗證。"""
from multiprocessing import Pool

import pandas as pd

import oos_study as oos
import robust_study as rs
import robust_yield_hold as yh
from backtest import RESULTS
from robust_mix import summarize

BASES = {
    "第1名Y1不分區": (yh.CONFIGS["不設上限｜Y1殖利率≥5%續抱"], "不分區"),
    "第3名Y3封頂2+3": (yh.CONFIGS["不設上限｜Y3＋封頂40%"], "0050區2＋0056區3"),
    "兩年上限Hc+Y4不分區": (yh.CONFIGS["Hc兩年上限｜Y4＋保利＋封頂"], "不分區"),
}
COOL = {"無冷卻·一天可多檔": {}, "一天一檔": {"one_per_day": True, "cooldown": 0}}
for n in (3, 5, 7, 10):
    COOL[f"冷卻{n}日"] = {"one_per_day": True, "cooldown": n}
RESERVE = {"P0不保留": {}, "P1留一筆首買": {"add_reserve": "one"}, "P2留快到買點": {"add_reserve": "near1"}, "P3留快到買點(寬)": {"add_reserve": "near2"}}
SPLITS = {"不分區": None, "0050區2＋0056區3": (2, 3)}
CONFIGS = {f"{b}｜{cn}｜{rn}": ({**bk, **ck, **rk}, sp) for b, (bk, sp) in BASES.items() for cn, ck in COOL.items() for rn, rk in RESERVE.items()}


def one_is(t):
    rs.RULES[t[0]] = CONFIGS[t[0]][0]; return rs.one(t)


def one_oos(t):
    rs.RULES[t[1]] = CONFIGS[t[1]][0]; return oos.one(t)


def main():
    rs.setup(); rs.SPLITS.clear(); rs.SPLITS.update(SPLITS)
    pairs = [(n, sp) for n, (_, sp) in CONFIGS.items()]
    # 冷卻天數已是規則的一部分，情境只跑起始日 × 追加（cooldown 參數對 one_per_day=False 無效，對其他版本由規則覆蓋）
    tasks = [(n, sp, st, c, 0) for n, sp in pairs for st in rs.STARTS for c in rs.CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=8)
    df = pd.DataFrame([dict(版本=t[0], IRR=i, 回撤=m, 最長持有=h) for t, i, m, h, p in res])
    g = df.groupby("版本").agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)), IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"), 最長持有=("最長持有", "max"))
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, 0) for n, sp in pairs for st in starts for c in oos.CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], IRR=i, 回撤=m) for t, i, m, h in res])
    go = do.groupby(["驗證", "版本"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)), IRR標準差=("IRR", "std"))
    m = pd.DataFrame({"前7年": g["IRR中位數"], "前7年最差10": g["IRR最差10"], "前7年回撤": g["回撤中位數"],
                      "延續": go.loc["延續"]["IRR中位數"], "延續最差10": go.loc["延續"]["IRR最差10"],
                      "單獨": go.loc["單獨"]["IRR中位數"], "單獨最差10": go.loc["單獨"]["IRR最差10"],
                      "標準差平均": (g["IRR標準差"] + go.loc["延續"]["IRR標準差"] + go.loc["單獨"]["IRR標準差"]) / 3})
    m["三段平均"] = m[["前7年", "延續", "單獨"]].mean(axis=1)
    m["最差10最小"] = m[["前7年最差10", "延續最差10", "單獨最差10"]].min(axis=1)
    m.round(2).to_csv(RESULTS / "reserve_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(m[["前7年", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年回撤"]].round(1).to_string())


if __name__ == "__main__":
    main()
