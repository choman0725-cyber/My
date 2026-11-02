"""買點選擇看信心值（2026-11-01 使用者）：
  ①同一天買點多於空位時，信心高者先買（同分比殖利率；正式版是殖利率高者先）——設定鍵 cand_order="conf"
  ②等更好的：觀察名單有「殖利率已達門檻、技術面接近買點、今天沒買訊、信心比較高」的股票時，先不買，最多等 5 天，
    等到就買它，沒等到且原本那檔殖利率仍達門檻就到期買原本那檔——設定鍵 wait_better=5（另測 3、10 天看敏感度）
  ③①＋②
每個版本跑 20 情境＋後 3 年＋與正式版的配對＋500 萬兩個起跑日。
用法：python conf_pick_study.py　輸出：results/conf_pick_eval.csv、conf_pick_money.csv"""
import numpy as np
import pandas as pd

import rules_research as rr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

VARIANTS = {"正式版": {}, "①信心高者先買": {"cand_order": "conf"}, "②等更好的 5 天": {"wait_better": 5},
            "②等更好的 3 天": {"wait_better": 3}, "②等更好的 10 天": {"wait_better": 10},
            "①＋②（5 天）": {"cand_order": "conf", "wait_better": 5}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money, events = {}, {}, {}
    for i, (name, extra) in enumerate(VARIANTS.items()):
        cfg = {**rr.BASE, **extra}
        po.apply(cfg); kw = po.to_kw(cfg)
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], f"confpick_{i}").loc[name]
        if i:
            for k_, val in paired_from_files("confpick_0", f"confpick_{i}").items():
                m[k_] = val
        results[name] = m
        po.apply(cfg)       # evaluate 在本程序依序算時會套用同一設定；保險起見再套一次
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            if sn == "2017-01-03":
                cf = [G["sub"][r.代號]["conf_score"][dates.get_indexer([r.進場])[0] - 1] for r in tr.itertuples()]
                events[name] = dict(平均進場信心=round(float(np.mean(cf)), 2), 信心3以上筆數=int(np.sum(np.array(cf) >= 3)))
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    out = out[show].join(pd.DataFrame(events).T)
    mon = pd.DataFrame(money).T
    out.round(2).to_csv(RESULTS / "conf_pick_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "conf_pick_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_confpick_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out.round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
