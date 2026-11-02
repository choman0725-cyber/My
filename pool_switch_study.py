"""全部成分股當股票池（timing_study 那套：0050／0056／0051／0052 歷年全部 351 檔、各產業都有），再套「換股 18%」（2026-11-02 使用者）。
想法：股票池大、各產業發動時間不同，名額常滿 → 換股可能更有用。正式版規則 5 檔不變，只換股票池、開關換股：
  P0 現行 47 檔（0050／0056 名單內的半導體＋電腦及週邊）
  P1 0050／0056 歷年全部成分股（各產業）
  P2 四檔 ETF 歷年全部成分股（任一名單內就可買）
每個池子 × {正式版, 換股 18%（daily_run.FINAL_SW18）}：20 情境＋後 3 年（配對相對 P0 正式版）、500 萬兩個起跑日、2007–2016 每年 1 月起跑。
資料：results/portfolio_prepared_2006_all.pkl（2006 起、自己中位數真歷史，所以 P0 正式版與 2017 快取的 33.31 略不同）。
用法：python pool_switch_study.py　輸出：results/pool_switch_eval.csv、_money.csv、_hist.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, POOL
from pool_expand_study import load, setup_pool
from stock_fit import paired_from_files

RULES = {"正式版": dr.FINAL, "換股18%": {**dr.FINAL, **dr.FINAL_SW18}}


def pools(cons):
    c50 = cons["0050"]
    return {"P0 47檔": c50[c50["stock_id"].isin(POOL)], "P1 0050/0056全部": c50,
            "P2 四檔ETF全部": pd.concat([c50, cons["0051"], cons["0052"]])}


def main():
    cons, d, data, sig = load()
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    s1228 = d.get_indexer([pd.Timestamp("2016-12-28")], method="bfill")[0]
    e16 = d.get_indexer([pd.Timestamp("2016-12-30")], method="ffill")[0]
    res, money, hist = {}, {}, []
    i = 0
    for pname, cdf in pools(cons).items():
        for rname, cfg in RULES.items():
            name = f"{pname}｜{rname}"
            G = setup_pool(cdf, d, data, sig); po.apply(cfg); kw = po.to_kw(cfg)
            po.CONFIGS[name] = cfg
            m = po.evaluate([name], f"psw_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("psw_0", f"psw_{i}").items():
                    m[k_] = v
            m["檔數"] = len(G["sub"]); res[name] = m
            po.apply(cfg)
            for sn, s in (("2016-12-28", s1228), ("2017-01-03", s17)):
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
                v = eq.iloc[-1] / eq.iloc[0]
                money[(name, sn)] = dict(期末萬=round(v * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [d[s]], v * CAPITAL, d[-1]), 1),
                                         回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr),
                                         換股次數=int(tr["原因"].astype(str).str.startswith("換股").sum()))
            for yr in range(2007, 2017):
                s = d.get_indexer([pd.Timestamp(yr, 1, 1)], method="bfill")[0]
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
                q16 = eq.loc[:d[e16]]
                hist.append(dict(版本=name, 起跑=yr, 至2016年底IRR=round(irr([CAPITAL], [d[s]], q16.iloc[-1] / q16.iloc[0] * CAPITAL, d[e16]), 1) if yr < 2016 else np.nan,
                                 至今IRR=round(irr([CAPITAL], [d[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, d[-1]), 1)))
            print(f"  {name}（{len(G['sub'])} 檔）：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
            i += 1
    out = pd.DataFrame(res).T
    show = [c for c in ["檔數", "前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T; t = pd.DataFrame(hist)
    base = t[t["版本"] == t["版本"].iloc[0]].set_index("起跑"); summ = {}
    for name, g in t.groupby("版本", sort=False):
        g = g.set_index("起跑"); d16 = (g["至2016年底IRR"] - base["至2016年底IRR"]).dropna(); dn = g["至今IRR"] - base["至今IRR"]
        summ[name] = dict(至2016平均IRR=round(g["至2016年底IRR"].mean(), 1), 至2016最差=g["至2016年底IRR"].min(), 至2016配對=f"{(d16 > .05).sum()}/{(d16.abs() <= .05).sum()}/{(d16 < -.05).sum()}",
                          至今平均IRR=round(g["至今IRR"].mean(), 1), 至今配對=f"{(dn > .05).sum()}/{(dn.abs() <= .05).sum()}/{(dn < -.05).sum()}")
    out[show].to_csv(RESULTS / "pool_switch_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "pool_switch_money.csv", encoding="utf-8-sig")
    t.to_csv(RESULTS / "pool_switch_hist.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summ).T.to_csv(RESULTS / "pool_switch_hist_summary.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_psw_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string()); print(pd.DataFrame(summ).T.to_string())


if __name__ == "__main__":
    main()
