"""股票池擴大（pool_expand_study 的 P0／P1／P2）的 20 情境＋後 3 年＋配對，以及 10 年路徑的逐年對照。
用 2006 起全成分股快取；情境起訖以日期查，與正式框架相同。輸出 results/pool_expand_eval.csv、pool_expand_yearly.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files
from pool_expand_study import load, pools, pools_elec, setup_pool


def yearly(eq):
    y = eq.groupby(eq.index.year).last(); prev = y.shift(1); prev.iloc[0] = eq.iloc[0]
    return ((y / prev - 1) * 100).round(1)


def main(elec=False):
    cons, dates, data, sig = load(); d = dates
    P = pools_elec(cons) if elec else pools(cons)
    names = list(P) if elec else ["P0 現行 0050/0056 電子股", "P1 ＋0052", "P2 ＋0052＋0051 科技股（代理分類）"]
    tag = "pee" if elec else "pe"
    res, yt = {}, {}
    s = d.get_indexer([pd.Timestamp("2016-11-01")], method="bfill")[0]
    sub = d[s + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    contrib = {i: 100_000 / 5_000_000 for i in midx}
    for i, name in enumerate(names):
        G = setup_pool(P[name], dates, data, sig); kw = po.to_kw(dr.FINAL)
        tr, eq = ps.run(G["sub"], G["member"], d, capital=5_000_000, contributions=contrib, start_n=s, **kw)
        yt[name] = yearly(eq)
        po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], f"{tag}_{i}").loc[name]
        if i:
            for k_, v in paired_from_files(f"{tag}_0", f"{tag}_{i}").items():
                m[k_] = v
        res[name] = m
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "前7年回撤", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / ("pool_expand_elec_eval.csv" if elec else "pool_expand_eval.csv"), encoding="utf-8-sig")
    Y = pd.DataFrame(yt); Y.to_csv(RESULTS / ("pool_expand_elec_yearly.csv" if elec else "pool_expand_yearly.csv"), encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 P0）"); print(out[show].round(2).to_string())
        print("\n逐年（2016-11-01 起、500 萬＋每月 10 萬）"); print(Y.to_string())


if __name__ == "__main__":
    import sys
    main(elec="--elec" in sys.argv)
