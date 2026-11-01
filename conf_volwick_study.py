"""信心值 F4 的放量／引線改看個股（2026-11-01 使用者：「有沒有放量跟引線應該大盤跟個股都要看，但主要是個股」）。
以正式版 E＋D＋U1 為基準，只改 F4 的放量／引線來源，年線一律看大盤、門檻維持信心 ≥3 首買 80%：
  正式版（大盤）：大盤 200 日線 ＋ 大盤前 5 日放量 ＋ 大盤前 5 日放量長下影線
  個股取代：      大盤 200 日線 ＋ 個股前 5 日放量 ＋ 個股前 5 日放量長下影線
  個股為主：      個股各 1 分、大盤各 0.5 分
  兩者並重：      個股、大盤各 1 分
每個版本跑 20 情境＋後 3 年＋與正式版的配對＋500 萬兩個起跑日；另列買點事件中信心 ≥3 的比例。
用法：python conf_volwick_study.py　輸出：results/conf_volwick_eval.csv、conf_volwick_money.csv"""
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

VARIANTS = {"正式版（大盤放量／引線）": None, "個股取代大盤": "stock", "個股為主（大盤 0.5）": "stock_main", "個股＋大盤並重": "both"}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money, events = {}, {}, {}
    for i, (name, vw) in enumerate(VARIANTS.items()):
        cfg = {**dr.FINAL, "conf_vw": vw}
        po.apply(cfg); kw = po.to_kw(cfg)
        sc = np.concatenate([d["conf_score"][s17:][d["buy"][s17:]] for d in G["sub"].values()])
        events[name] = dict(買點事件=len(sc), 信心3以上比例=round(100 * (sc >= 3).mean(), 1), 平均信心=round(sc.mean(), 2))
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], f"confvw_{i}").loc[name]
        if i:
            for k_, val in paired_from_files("confvw_0", f"confvw_{i}").items():
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
    out.round(2).to_csv(RESULTS / "conf_volwick_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "conf_volwick_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_confvw_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out.round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
