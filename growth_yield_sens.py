"""成長股相對規則的敏感度：k（倍數）、成長股定義（3 年殖利率中位 < X%）、中位數視窗（500／750／1000 日）。
每個版本跑 20 情境＋後 3 年＋與正式版 A 的配對＋500 萬。用法：python growth_yield_sens.py
輸出：results/growth_yield_sens.csv"""
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

VARIANTS = [  # (k, 成長股中位門檻, 視窗)
    (1.25, 4.0, 750), (1.5, 4.0, 750), (1.1, 4.0, 750), (2.0, 4.0, 750),
    (1.25, 3.0, 750), (1.25, 5.0, 750), (1.25, 99.0, 750),      # 99＝所有股票都用相對規則（＝舊的 relative_yield 做法）
    (1.25, 4.0, 500), (1.25, 4.0, 1000),
]


def ratios(G, dates, window):
    out = {}
    for sid, d in G["sub"].items():
        y = pd.Series(d["yield"], index=dates)
        med = y.rolling(window, min_periods=min(250, window // 2)).median().shift(1)
        out[sid] = ((y / med).values, med.values)
    return out


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    s_n = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sig = G["sig"][po.ENTRIES[dr.FINAL["entry"]]]
    prof = {sid: ps.profit_years_flag(d.get("annual_eps"), dates, dr.FINAL["profit_years"]) for sid, d in G["sub"].items()}
    orig = {sid: d["buy"].copy() for sid, d in G["sub"].items()}
    key = po._applied["buy"]
    _to_kw = po.to_kw
    po.to_kw = lambda cfg: {**_to_kw(cfg), "hold_yield": "hy_rel"}
    Rcache = {}
    rows, money = {}, {}
    def run(name, tag, k=None, gmed=4.0, window=750):
        R = Rcache.setdefault(window, ratios(G, dates, window))
        for sid, d in G["sub"].items():
            ratio, med = R[sid]
            if k is None:
                d["buy"] = orig[sid]; d["hy_rel"] = np.full(len(dates), dr.FINAL["hold_yield"])
            else:
                growth = np.nan_to_num(med, nan=99) < gmed
                rel = sig[sid] & (np.nan_to_num(ratio, nan=0) >= k) & prof[sid]
                d["buy"] = np.where(growth, rel, orig[sid]); d["hy_rel"] = np.where(growth, med, dr.FINAL["hold_yield"])
        po._applied["buy"] = key
        po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], tag).loc[name]
        if tag != "gys_A":
            for k_, v in paired_from_files("gys_A", tag).items():
                m[k_] = v
        rows[name] = m
        kw2 = {**kw, "hold_yield": "hy_rel"}
        for sname, s in (("2016-12-28", 1), ("2017-01-03", s_n)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw2)
            money[(name, sname)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                        回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}　最差10 {m['最差10最小']:.2f}　σ {m['標準差平均']:.2f}　配對 {m.get('前7年配對', '')} / {m.get('後3年配對', '')}", flush=True)
    try:
        run("A 正式版", "gys_A")
        for i, (k, gmed, w) in enumerate(VARIANTS):
            run(f"k={k} 中位<{gmed:.0f}% 視窗{w}", f"gys_{i}", k, gmed, w)
    finally:
        po.to_kw = _to_kw
        for sid, d in G["sub"].items():
            d["buy"] = orig[sid]; d.pop("hy_rel", None)
        po._applied["buy"] = key
    out = pd.DataFrame(rows).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / "growth_yield_sens.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "growth_yield_sens_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 A）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
