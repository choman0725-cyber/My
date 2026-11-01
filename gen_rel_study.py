"""一般股也看「相對自己中值」（2026-11-01 使用者：殖利率已達 5% 但仍低於自己中位的不買，門檻用 k 倍）。
以正式版 E＋D＋U1 為基準，只加一條：一般股（自己 3 年殖利率中位 ≥4%）買進另需 殖利率 ≥ 自己中位 × k
（設定鍵 gen_rel；成長股、續抱、其他規則不變；中位算不出來視為通過）。k 掃 1.00～1.25。
每個版本跑 20 情境＋後 3 年＋與正式版的配對＋500 萬兩個起跑日；另列 2017 起買點事件數。
用法：python gen_rel_study.py　輸出：results/gen_rel_eval.csv、gen_rel_money.csv"""
import sys

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

VARIANTS = {"正式版": None, "一般股 ≥中位×1.00": 1.0, "一般股 ≥中位×1.05": 1.05, "一般股 ≥中位×1.10": 1.10,
            "一般股 ≥中位×1.15": 1.15, "一般股 ≥中位×1.25": 1.25}
# python gen_rel_study.py 5y：中位數視窗改 5 年（1250 日）——①成長股判定與門檻改 5 年（只改這一件）②一般股規則用 5 年中位
VARIANTS_5Y = {"正式版": {}, "成長股改 5 年中位": {"growth_rel": (1.25, 4.0, 1250)},
               "一般股 ≥5年中位×1.00": {"gen_rel": 1.0, "gen_rel_win": 1250}, "一般股 ≥5年中位×1.25": {"gen_rel": 1.25, "gen_rel_win": 1250}}


def main():
    five = "5y" in sys.argv
    tag, variants = ("genrel5y", VARIANTS_5Y) if five else ("genrel", {k: {"gen_rel": v} for k, v in VARIANTS.items()})
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money, events = {}, {}, {}
    for i, (name, extra) in enumerate(variants.items()):
        cfg = {**dr.FINAL, **extra}
        po.apply(cfg); kw = po.to_kw(cfg)
        sc = np.concatenate([d["conf_score"][s17:][d["buy"][s17:]] for d in G["sub"].values()])
        events[name] = dict(買點事件=len(sc), 信心3以上比例=round(100 * (sc >= 3).mean(), 1), 平均信心=round(sc.mean(), 2))
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], f"{tag}_{i}").loc[name]
        if i:
            for k_, val in paired_from_files(f"{tag}_0", f"{tag}_{i}").items():
                m[k_] = val
        results[name] = m
        po.apply(cfg)       # evaluate 在本程序依序算時會套用同一設定；保險起見再套一次
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    out = out[show].join(pd.DataFrame(events).T)
    mon = pd.DataFrame(money).T
    out.round(2).to_csv(RESULTS / f"{tag.replace('genrel', 'gen_rel')}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"{tag.replace('genrel', 'gen_rel')}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob(f"param_opt_{tag}_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out.round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
