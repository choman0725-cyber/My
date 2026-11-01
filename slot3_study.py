"""只能買 3 檔時的配置（2026-11-01 使用者：「如果只能買三隻，要怎麼配置，給我最佳參數」）。
兩種「3 檔」：
  名額 3：max_slots=3，其他照正式版（套牢、被剔除的部位不佔名額，所以實際可能同時持有 >3 檔）
  硬上限 3：同時最多持有 3 檔（套牢、被剔除的也佔名額；param_opt cfg["hard_cap"]）
以硬上限 3 為基準，一次只改一項：首買比例、信心首買比例、加碼、停利、續抱殖利率；最後把各項的勝出值合併再驗一次。
每個版本跑 20 情境＋後 3 年＋配對（相對硬上限 3 基準）＋500 萬兩個起跑日（含最多同時持有幾檔）。
用法：python slot3_study.py [combo 名稱=json ...]　輸出：results/slot3_eval.csv、slot3_money.csv"""
import json
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

H3 = {**dr.FINAL, "max_slots": 3, "hard_cap": True}
VARIANTS = {"正式版 5 檔": dr.FINAL,
            "名額 3（套牢不佔名額）": {**dr.FINAL, "max_slots": 3},
            "硬上限 3（基準）": H3,
            **{f"硬3 首買 {f:.0%}": {**H3, "first": f} for f in (0.35, 0.65, 0.80, 1.00)},
            "硬3 信心首買 100%": {**H3, "conf_first": (3, 1.0)},
            "硬3 信心首買關閉": {**H3, "conf_first": None},
            "硬3 不加碼": {**H3, "adds": "N 不加碼"},
            "硬3 加碼 -10/-20": {**H3, "adds": "B -10/-20 加30/20"},
            "硬3 加碼 -20/-40": {**H3, "adds": "C -20/-40 加30/20"},
            **{f"硬3 停利 {t:.0%}": {**H3, "target": t} for t in (0.08, 0.20, 0.30)},
            **{f"硬3 續抱 {h}": {**H3, "hold_yield": h} for h in (4.0, 4.5, 5.0)}}
BASE = "硬上限 3（基準）"


def max_concurrent(tr, eq):
    if not len(tr):
        return 0
    days = pd.Series(0, index=eq.index)
    for _, r in tr.iterrows():
        out_ = pd.Timestamp(r["出場"]) if pd.notna(r["出場"]) else days.index[-1] + pd.Timedelta(days=1)   # 未出場＝持有到最後
        days[(days.index >= pd.Timestamp(r["進場"])) & (days.index < out_)] += 1
    return int(days.max())


def main():
    variants = VARIANTS
    extra = [a for a in sys.argv[1:] if "=" in a]
    if extra:                                   # 合併驗證：python slot3_study.py "名稱={...}"
        variants = {"正式版 5 檔": dr.FINAL, BASE: H3,
                    **{a.split("=", 1)[0]: {**H3, **{k: tuple(v) if isinstance(v, list) else v for k, v in json.loads(a.split("=", 1)[1]).items()}} for a in extra}}
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money, tags = {}, {}, {}
    names = [BASE] + [n for n in variants if n != BASE]     # 先跑基準，其他版本才能配對
    for i, name in enumerate(names):
        cfg = variants[name]
        po.apply(cfg); kw = po.to_kw(cfg)
        tags[name] = f"slot3_{i}"
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], tags[name]).loc[name]
        if i:
            for k_, val in paired_from_files("slot3_0", tags[name]).items():
                m[k_] = val
        results[name] = m
        po.apply(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0),
                                     最多同時=max_concurrent(tr, eq))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(results).T.loc[[n for n in variants]]
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    suffix = "_combo" if extra else ""
    out[show].round(2).to_csv(RESULTS / f"slot3{suffix}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"slot3{suffix}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_slot3_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對硬上限 3 基準）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
