"""同樣「半導體＋電腦及週邊」的分類，也從 0051／0052 成分股挑（2026-11-01 使用者）。
正式版 E＋D＋U1、5 檔不變，只換可買的股票（當天在任一 ETF 名單內、且產業別是半導體或電腦及週邊）：
  T0 現行 47 檔（0050／0056）　T1 ＋0052 的半導體／電腦　T2 ＋0051 的半導體／電腦　T3 ＋兩者
分類：data/universe/industry_twse_all.csv（0050／0051／0052／0056 全部成分股；上市中取證交所 OpenAPI，已下市手填，不確定的在 source 註明）。
市場中位數門檻照舊用 0050＋0056 全部成分股。資料：results/portfolio_prepared_2006_all.pkl（建法見 HANDOFF 11.5）。
每個版本：20 情境＋後 3 年＋配對（相對 T0）、500 萬兩個起跑日、2006–2016 每年 1 月起跑（算到 2016 年底與算到今天）。
用法：python pool_etf_tech_study.py　輸出：results/pool_etf_tech_eval.csv、_money.csv、_hist.csv"""
import numpy as np
import pandas as pd

import rules_research as rr
import param_opt as po
import portfolio_study as ps
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, POOL
from pool_expand_study import load, setup_pool
from stock_fit import paired_from_files

SC = {"半導體業", "電腦及週邊設備業"}


def pools(cons):
    ind = pd.read_csv(ps.UNI / "industry_twse_all.csv", dtype=str).set_index("stock_id")["industry"]
    tech = set(ind.index[ind.isin(SC)])
    f = lambda c: c[c["stock_id"].isin(tech)]
    t0 = cons["0050"][cons["0050"]["stock_id"].isin(POOL)]
    return {"T0 現行 47 檔": t0, "T1 ＋0052 半導體／電腦": pd.concat([t0, f(cons["0052"])]),
            "T2 ＋0051 半導體／電腦": pd.concat([t0, f(cons["0051"])]),
            "T3 ＋0051＋0052 半導體／電腦": pd.concat([t0, f(cons["0052"]), f(cons["0051"])])}


def main():
    cons, d, data, sig = load()
    P = pools(cons)
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    s1228 = d.get_indexer([pd.Timestamp("2016-12-28")], method="bfill")[0]
    e16 = d.get_indexer([pd.Timestamp("2016-12-30")], method="ffill")[0]
    res, money, hist = {}, {}, []
    for i, (name, cdf) in enumerate(P.items()):
        G = setup_pool(cdf, d, data, sig); kw = po.to_kw(rr.BASE)
        po.CONFIGS[name] = rr.BASE
        m = po.evaluate([name], f"pet_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("pet_0", f"pet_{i}").items():
                m[k_] = v
        m["檔數"] = len(G["sub"])
        res[name] = m
        po.apply(rr.BASE)
        for sn, s in (("2016-12-28", s1228), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
            v = eq.iloc[-1] / eq.iloc[0]
            money[(name, sn)] = dict(期末萬=round(v * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [d[s]], v * CAPITAL, d[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0))
        for yr in range(2007, 2017):
            s = d.get_indexer([pd.Timestamp(yr, 1, 1)], method="bfill")[0]
            tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
            q16 = eq.loc[:d[e16]]
            hist.append(dict(版本=name, 起跑=yr, 至2016年底IRR=round(irr([CAPITAL], [d[s]], q16.iloc[-1] / q16.iloc[0] * CAPITAL, d[e16]), 1) if yr < 2016 else np.nan,
                             至2016年底回撤=round(100 * (q16 / q16.cummax() - 1).min(), 1),
                             至今IRR=round(irr([CAPITAL], [d[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, d[-1]), 1)))
        print(f"  {name}（{len(G['sub'])} 檔）完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["檔數", "前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    t = pd.DataFrame(hist); base = t[t["版本"] == next(iter(P))].set_index("起跑")
    summ = {}
    for name, g in t.groupby("版本", sort=False):
        g = g.set_index("起跑")
        d16 = (g["至2016年底IRR"] - base["至2016年底IRR"]).dropna(); dn = g["至今IRR"] - base["至今IRR"]
        summ[name] = dict(至2016平均IRR=round(g["至2016年底IRR"].mean(), 1), 至2016最差=g["至2016年底IRR"].min(),
                          至2016配對=f"{(d16 > .05).sum()}/{(d16.abs() <= .05).sum()}/{(d16 < -.05).sum()}", 至2016最差回撤=g["至2016年底回撤"].min(),
                          至今平均IRR=round(g["至今IRR"].mean(), 1), 至今配對=f"{(dn > .05).sum()}/{(dn.abs() <= .05).sum()}/{(dn < -.05).sum()}")
    out[show].to_csv(RESULTS / "pool_etf_tech_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "pool_etf_tech_money.csv", encoding="utf-8-sig")
    t.to_csv(RESULTS / "pool_etf_tech_hist.csv", index=False, encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_pet_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 T0）"); print(out[show].to_string())
        print("\n500 萬不追加"); print(mon.to_string())
        print("\n2006–2016 每年起跑"); print(pd.DataFrame(summ).T.to_string())


if __name__ == "__main__":
    main()
