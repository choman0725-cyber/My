"""避險部位——使用者 2026-11-01 定案的細節：起始資金不算閒錢（第一次賣股後才開始）、停利當天直接投入、美債用 00719B（1-3 年）。
三個標的（0050／00719B／條件式：年線上 0050、線下 00719B）各跑 20 情境＋後 3 年＋500 萬。輸出 results/hedge_final_eval.csv、hedge_final_money.csv"""
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files
from hedge_study import vehicles

SPEC = dict(hedge_reserve=0.10, hedge_take=0.05, hedge_cooldown=10, hedge_add_timing="signal", hedge_add_cap="shortfall",
            hedge_from="first_sell", hedge_idle_days=0)


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    V = vehicles(d)
    variants = {"正式版 E＋D": {}, "避險 0050": {**SPEC, "hedge_index": V["0050"]},
                "避險 美債1-3年(00719B)": {**SPEC, "hedge_index": V["美債1-3年(00719B)"]},
                "避險 條件式(年線上0050/線下00719B)": {**SPEC, "hedge_index": V["條件式(年線上0050/線下短債)"]}}
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows = []
    for name, extra in variants.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, **kw, **extra)
                hl = pd.DataFrame(eq.attrs["hedge_log"])
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1),
                                 避險段數=len(hl), 避險總損益萬=round(hl["回收"].sub(hl["投入"]).sum() * CAPITAL / 1e4) if len(hl) else 0,
                                 避險最長持有日=int(hl["持有日"].max()) if len(hl) else 0, 筆數=len(tr)))
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "hedge_final_money.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(variants.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = dr.FINAL
            m = po.evaluate([name], f"hf_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("hf_0", f"hf_{i}").items():
                    m[k_] = v
            res[name] = m
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "hedge_final_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.to_string())


if __name__ == "__main__":
    main()
