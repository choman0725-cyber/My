"""閒錢避險部位（使用者 2026-10-31 晚間的邏輯）：錢仍是五份、做多不留預備金；現金超過總資產 10% 的部分投入避險標的；
避險賺 ≥5% 領出、觀察 2 或 4 週；虧損續抱；續抱期間買股先用現金，買完啟動出清方案：兩平立刻出清、出清的錢找時機加碼剛買的股票。
標的：0050、美債 ETF（00679B 20 年／00719B 1-3 年，資料到位前用年化 2%／4% 代替）、條件式（大盤 200 日線上 0050／線下美債）。
用法：python hedge_study.py [--quick]     輸出：results/hedge_eval.csv、hedge_money.csv、hedge_episodes.csv、hedge_fill.csv"""
import sys
import numpy as np
import pandas as pd

import rules_research as rr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

PR = ROOT / "data" / "universe" / "prices"


def daily_ret(sid, dates):
    p = PR / f"{sid}.csv"
    if not p.exists():
        return None
    px = pd.read_csv(p, parse_dates=["date"]).set_index("date")["adj_close"].reindex(dates).ffill()
    r = px.pct_change().fillna(0).values.copy()
    r[np.isnan(px.values)] = 0.0          # 上市前：視為現金（0 報酬）
    return r


def bull_mask(dates):
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(dates).ffill()
    return (tai > tai.rolling(200).mean()).shift(1).fillna(False).values.astype(bool)


def vehicles(dates):
    """回傳 {名稱: 每日報酬陣列}；債券 ETF 沒有資料時用固定利率代替並在名稱註明。"""
    r50 = daily_ret("0050", dates)
    out = {"0050": r50}
    for sid, lab in (("00679B", "美債20年"), ("00719B", "美債1-3年")):
        r = daily_ret(sid, dates)
        if r is not None:
            out[f"{lab}({sid})"] = r
    if not any("美債" in k for k in out):
        out["美債代替(年化2%)"] = np.full(len(dates), 0.02 / 252)
        out["美債代替(年化4%)"] = np.full(len(dates), 0.04 / 252)
    bull = bull_mask(dates)
    bond = next((v for k, v in out.items() if "美債1-3" in k or "2%" in k), None)
    bond20 = next((v for k, v in out.items() if "美債20" in k), None)
    out["條件式(年線上0050/線下短債)"] = np.where(bull, r50, bond)
    if bond20 is not None:
        out["條件式(年線上0050/線下美債20年)"] = np.where(bull, r50, bond20)
    return out


def main(quick=False):
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
    V = vehicles(d)
    base_h = dict(hedge_reserve=0.10, hedge_take=0.05, hedge_cooldown=10, hedge_add_timing="signal", hedge_add_cap="shortfall")
    variants = {"正式版 E＋D": {}}
    for name, arr in V.items():
        variants[f"H1 {name}·觀察2週"] = {**base_h, "hedge_index": arr}
    main_v = V["0050"]
    variants.update({
        "H2 0050·觀察4週": {**base_h, "hedge_index": main_v, "hedge_cooldown": 20},
        "H3 0050·加碼補到整份額度": {**base_h, "hedge_index": main_v, "hedge_add_cap": "budget"},
        "H4 0050·出清隔天就加碼": {**base_h, "hedge_index": main_v, "hedge_add_timing": "immediate"},
        "H5 0050·現金不足就強制出清": {**base_h, "hedge_index": main_v, "hedge_force": True},
        "H6 0050·第一次賣股後才開始": {**base_h, "hedge_index": main_v, "hedge_from": "first_sell"},
        "H7 0050·領出門檻10%": {**base_h, "hedge_index": main_v, "hedge_take": 0.10},
        "H8 0050·閒 10 天才投入": {**base_h, "hedge_index": main_v, "hedge_idle_days": 10},
        "H9 0050·閒 20 天才投入": {**base_h, "hedge_index": main_v, "hedge_idle_days": 20},
    })
    for key in ("美債1-3年", "條件式(年線上0050/線下短債)"):
        vk = next((k for k in V if k.startswith(key)), None)
        if vk:
            variants[f"H5 {vk}·現金不足就強制出清"] = {**base_h, "hedge_index": V[vk], "hedge_force": True}
            variants[f"H8 {vk}·閒 10 天才投入"] = {**base_h, "hedge_index": V[vk], "hedge_idle_days": 10}
    if quick:
        variants = {k: v for i, (k, v) in enumerate(variants.items()) if i < 3}
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows, eps, fills = [], [], []
    for name, extra in variants.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                led = []
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, ledger=led, **kw, **extra)
                hl = pd.DataFrame(eq.attrs["hedge_log"])
                L = pd.DataFrame(led)
                fb = L[L["動作"] == "買進"] if len(L) else L
                short = 0
                if len(fb):
                    budget_fr = fb["說明"].str.extract(r"額度 ([\d.]+) 的 (\d+)%").astype(float)
                    intended = budget_fr[0] * budget_fr[1] / 100
                    short = int((fb["金額"] < intended * 0.999).sum())
                h_end = eq.attrs["hedge"]["val"] * CAPITAL / 1e4
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1),
                                 避險段數=len(hl), 避險賺領出=int((hl["原因"].str.contains("領出")).sum()) if len(hl) else 0,
                                 避險兩平出清=int((hl["原因"].str.contains("兩平")).sum()) if len(hl) else 0,
                                 避險總損益萬=round(hl["回收"].sub(hl["投入"]).sum() * CAPITAL / 1e4) if len(hl) else 0,
                                 避險最差段=round(hl["報酬%"].min(), 1) if len(hl) else np.nan,
                                 避險最長持有日=int(hl["持有日"].max()) if len(hl) else 0,
                                 首買被預備金限縮次數=short, 首買次數=len(fb), 期末避險部位萬=round(h_end),
                                 出清後加碼次數=int((L["說明"] == "避險出清後加碼").sum()) if len(L) else 0))
                if len(hl) and not monthly and sname == "2017-01-03":
                    eps.append(hl.assign(版本=name))
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "hedge_money.csv", index=False, encoding="utf-8-sig")
    if eps:
        pd.concat(eps).to_csv(RESULTS / "hedge_episodes.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(variants.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = rr.BASE
            m = po.evaluate([name], f"hg_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("hg_0", f"hg_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "hedge_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 400, "display.max_rows", 200, "display.max_columns", 50, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.to_string())


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
