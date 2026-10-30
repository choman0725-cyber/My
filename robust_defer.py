"""賣出時若處於突破狀態，等下一個反轉再賣。突破 B1/B2/B3 × 反轉 Ra/Rb/Rc，套在三個底上；前 7 年 40 情境＋後 3 年驗證。"""
from multiprocessing import Pool

import pandas as pd

import oos_study as oos
import robust_study as rs
import robust_yield_hold as yh
from backtest import RESULTS
from robust_mix import COOLDOWNS, summarize

BASES = {
    "第1名Y1不分區": (yh.CONFIGS["不設上限｜Y1殖利率≥5%續抱"], "不分區"),
    "第3名Y3封頂2+3": (yh.CONFIGS["不設上限｜Y3＋封頂40%"], "0050區2＋0056區3"),
    "兩年上限Hc+Y4不分區": (yh.CONFIGS["Hc兩年上限｜Y4＋保利＋封頂"], "不分區"),
}
DEFERS = {"不延後": {}}
for b in ("B1", "B2", "B3"):
    for r in ("Ra", "Rb", "Rc"):
        DEFERS[f"{b}×{r}"] = {"defer_breakout": f"breakout_{b}", "defer_reversal": f"reversal_{r}"}
DEFERS["B1×Ra·無保利"] = {"defer_breakout": "breakout_B1", "defer_reversal": "reversal_Ra", "defer_floor": 9.0}
SPLITS = {"不分區": None, "0050區2＋0056區3": (2, 3)}
CONFIGS = {f"{b}｜{dn}": ({**bk, **dk}, sp) for b, (bk, sp) in BASES.items() for dn, dk in DEFERS.items()}


def one_is(t):
    rs.RULES[t[0]] = CONFIGS[t[0]][0]; return rs.one(t)


def one_oos(t):
    rs.RULES[t[1]] = CONFIGS[t[1]][0]; return oos.one(t)


def main():
    rs.setup(); rs.SPLITS.clear(); rs.SPLITS.update(SPLITS)
    pairs = [(n, sp) for n, (_, sp) in CONFIGS.items()]
    tasks = [(n, sp, st, c, cd) for n, sp in pairs for st in rs.STARTS for c in rs.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=8)
    df = pd.DataFrame([dict(版本=t[0], 分區=t[1], 起始=t[2], 追加=t[3], 冷卻=t[4], IRR=i, 回撤=m, 最長持有=h, 超過2年比例=p) for t, i, m, h, p in res])
    df["底"] = df["版本"].str.split("｜").str[0]; df["延後"] = df["版本"].str.split("｜").str[1]
    g = summarize(df, ["底", "延後"]).sort_index()
    g.round(2).to_csv(RESULTS / "defer_in_sample.csv", encoding="utf-8-sig")
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, sp, st, c, cd) for n, sp in pairs for st in starts for c in oos.CONTRIBS for cd in COOLDOWNS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=8)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], IRR=i, 回撤=m) for t, i, m, h in res])
    go = do.groupby(["驗證", "版本"]).agg(IRR中位數=("IRR", "median"), IRR最差10=("IRR", lambda x: x.quantile(.1)), IRR標準差=("IRR", "std"), 回撤中位數=("回撤", "median"))
    go.round(2).to_csv(RESULTS / "defer_oos.csv", encoding="utf-8-sig")
    gi = g.reset_index(); gi["版本"] = gi["底"] + "｜" + gi["延後"]; gi = gi.set_index("版本")
    merged = pd.DataFrame({"前7年": gi["IRR中位數"], "前7年最差10": gi["IRR最差10"], "前7年標準差": gi["IRR標準差"], "前7年回撤": gi["回撤中位數"], "最長持有": gi["最長持有"],
                           "延續": go.loc["延續"]["IRR中位數"], "延續最差10": go.loc["延續"]["IRR最差10"], "單獨": go.loc["單獨"]["IRR中位數"], "單獨最差10": go.loc["單獨"]["IRR最差10"]})
    merged["三段平均"] = merged[["前7年", "延續", "單獨"]].mean(axis=1)
    merged["三段最差10最小"] = merged[["前7年最差10", "延續最差10", "單獨最差10"]].min(axis=1)
    merged.round(2).to_csv(RESULTS / "defer_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 80, "display.unicode.east_asian_width", True):
        print(merged[["前7年", "延續", "單獨", "三段平均", "三段最差10最小", "前7年標準差", "前7年回撤", "最長持有"]].round(1).to_string())


if __name__ == "__main__":
    main()
