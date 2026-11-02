"""小帳戶該用 5 檔正式版還是 3 檔版（2026-11-02，給第二帳戶用；股票池＝現行 47 檔）。
3 檔版 FINAL_3 是在電子 90 檔上調的，這裡在 47 檔上重跑：
  1. 20 情境＋後 3 年（配對相對 5 檔正式版）
  2. 指定本金＋每月追加（預設 236 萬＋每月 2 萬），2016-12-28 與 2017-01-03 起跑：期末、IRR、回撤、最多同時持股、每檔首買金額
用法：python small_account_slots.py [本金] [每月]　輸出：results/small_account_slots_eval.csv、_money.csv"""
import sys

import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from stock_fit import paired_from_files

CAP = float(sys.argv[1]) if len(sys.argv) > 1 else 2_360_000
MONTHLY = float(sys.argv[2]) if len(sys.argv) > 2 else 20_000
V = {"5 檔正式版": dr.FINAL, "3 檔版（首買 65%）": {**dr.FINAL, **dr.FINAL_3},
     "3 檔版 首買 50%": {**dr.FINAL, **dr.FINAL_3, "first": 0.5}, "3 檔版 首買 80%": {**dr.FINAL, **dr.FINAL_3, "first": 0.8}}


def max_concurrent(tr, dates):
    ev = pd.concat([pd.Series(1, index=pd.to_datetime(tr["進場"])), pd.Series(-1, index=pd.to_datetime(tr["出場"]).fillna(dates[-1] + pd.Timedelta(days=1)))])
    return int(ev.sort_index(kind="stable").cumsum().max()) if len(tr) else 0


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    ev, mon = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"sas_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("sas_0", f"sas_{i}").items():
                m[k_] = v
        ev[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            mc = dr.monthly_contrib(dates, s, MONTHLY, CAP, None)
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAP, contributions=mc or None, start_n=s, **kw)
            flows = [CAP] + [v * CAP for v in mc.values()]; fd = [dates[s]] + [dates[k] for k in mc]
            mon[(name, sn)] = dict(投入萬=round(sum(flows) / 1e4), 期末萬=round(eq.iloc[-1] * CAP / 1e4), IRR=round(irr(flows, fd, eq.iloc[-1] * CAP, dates[-1]), 1),
                                   回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 最多同時=max_concurrent(tr, dates),
                                   起跑首買萬=round(CAP / cfg.get("max_slots", 5) * cfg.get("first", 0.5) / 1e4, 1))
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
    ev = pd.DataFrame(ev).T; mon = pd.DataFrame(mon).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in ev.columns]
    ev[show].to_csv(RESULTS / "small_account_slots_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "small_account_slots_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_sas_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(ev[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
