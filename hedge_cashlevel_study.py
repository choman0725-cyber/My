"""避險第三版定義（使用者 2026-11-01）：現金 > 20% ×（現金＋未套牢持股市值，套牢股不計）→ 等 1 週沒買到 → 現金 50% 投入
0050／00719B／條件式 → 主引擎買進後不賠就出。主要看 500 萬＋每月 10 萬；也附 20 情境。
變體：當天就投入（不等）、只投入超過 20% 的部分、套牢只算虧損 >30%、加「賺 5% 領出」。
輸出 results/hedge_cashlevel_eval.csv、hedge_cashlevel_money.csv、hedge_cashlevel_episodes.csv"""
import pandas as pd

import rules_research as rr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files
from hedge_study import vehicles

SPEC = dict(hedge_mode="cashlevel", hedge_reserve=0.20, hedge_wait=5, hedge_frac=0.5, hedge_take=None, hedge_add_cap="none",
            hedge_exit_cooldown=False, hedge_trap="stale", hedge_from="first_sell")


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
    V = vehicles(d)
    veh = {"0050": V["0050"], "00719B": V["美債1-3年(00719B)"], "條件式": V["條件式(年線上0050/線下短債)"]}
    variants = {"正式版 E＋D": {}}
    for vn, arr in veh.items():
        variants[f"C {vn}·等1週·現金50%"] = {**SPEC, "hedge_index": arr}
    variants["C 0050·當天投入·現金50%"] = {**SPEC, "hedge_index": veh["0050"], "hedge_wait": 0}
    variants["C 0050·等1週·起跑資金也算閒錢"] = {**SPEC, "hedge_index": veh["0050"], "hedge_from": "start"}
    variants["C 0050·等1週·只投超過20%的部分"] = {**SPEC, "hedge_index": veh["0050"], "hedge_frac": None}
    variants["C 0050·等1週·套牢只算虧>30%"] = {**SPEC, "hedge_index": veh["0050"], "hedge_trap": "deep"}
    variants["C 0050·等1週·加賺5%領出"] = {**SPEC, "hedge_index": veh["0050"], "hedge_take": 0.05, "hedge_cooldown": 10}
    variants["C 條件式·當天投入·現金50%"] = {**SPEC, "hedge_index": veh["條件式"], "hedge_wait": 0}
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows, eps = [], []
    for name, extra in variants.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (100_000, 0):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                led = []
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, ledger=led, **kw, **extra)
                hl = pd.DataFrame(eq.attrs["hedge_log"]); L = pd.DataFrame(led)
                fb = L[L["動作"] == "買進"] if len(L) else L
                short = 0
                if len(fb):
                    bf = fb["說明"].str.extract(r"額度 ([\d.]+) 的 (\d+)%").astype(float)
                    short = int((fb["金額"] < bf[0] * bf[1] / 100 * 0.999).sum())
                days_in = int(sum(hl["持有日"])) if len(hl) else 0
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1),
                                 避險段數=len(hl), 避險總損益萬=round(hl["回收"].sub(hl["投入"]).sum() * CAPITAL / 1e4) if len(hl) else 0,
                                 避險持有日合計=days_in, 避險最長持有日=int(hl["持有日"].max()) if len(hl) else 0,
                                 避險最差段=round(hl["報酬%"].min(), 1) if len(hl) else None,
                                 期末避險部位萬=round(eq.attrs["hedge"]["val"] * CAPITAL / 1e4), 首買被限縮=short, 首買數=len(fb), 筆數=len(tr)))
                if len(hl) and monthly and sname == "2017-01-03":
                    eps.append(hl.assign(版本=name))
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "hedge_cashlevel_money.csv", index=False, encoding="utf-8-sig")
    if eps:
        pd.concat(eps).to_csv(RESULTS / "hedge_cashlevel_episodes.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(variants.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = rr.BASE
            m = po.evaluate([name], f"hc_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("hc_0", f"hc_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "hedge_cashlevel_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.max_columns", 40, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.to_string())


if __name__ == "__main__":
    main()
