"""起跑日敏感度：規則固定，起跑日從 2016-12-28 到 2017-02-28 每個交易日各跑一次 500 萬不追加，
看期末資產的分佈（最小／中位／最大、變異係數），比較 A、E 與加「一天一檔」「冷卻 N 日」的版本，
再對冷卻版本跑 20 情境＋後 3 年確認。目的：使用者希望「起跑日差幾天、結果不要差這麼多」。
用法：python start_dispersion_study.py
輸出：results/start_dispersion.csv（每個起跑日的期末）、start_dispersion_summary.csv、start_dispersion_eval.csv"""
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
import growth_yield_study as gy

START_FROM, START_TO = "2016-12-28", "2017-02-28"
COOL = {"一天一檔": dict(one_per_day=True, cooldown=0), "冷卻3日": dict(one_per_day=True, cooldown=3),
        "冷卻5日": dict(one_per_day=True, cooldown=5), "冷卻10日": dict(one_per_day=True, cooldown=10)}


def set_rule(G, dates, orig, R, sig, prof, use_E):
    for sid, d in G["sub"].items():
        if use_E:
            ratio, med = R[sid]; growth = np.nan_to_num(med, nan=99) < gy.GROWTH_MED
            d["buy"] = np.where(growth, sig[sid] & (np.nan_to_num(ratio, nan=0) >= 1.25) & prof[sid], orig[sid])
            d["hy_rel"] = np.where(growth, med, dr.FINAL["hold_yield"])
        else:
            d["buy"] = orig[sid]; d["hy_rel"] = np.full(len(dates), dr.FINAL["hold_yield"])


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    sig = G["sig"][po.ENTRIES[dr.FINAL["entry"]]]
    prof = {sid: ps.profit_years_flag(d.get("annual_eps"), dates, dr.FINAL["profit_years"]) for sid, d in G["sub"].items()}
    R = gy.relative_ratio(G, dates)
    orig = {sid: d["buy"].copy() for sid, d in G["sub"].items()}
    key = po._applied["buy"]
    starts = [i for i, t in enumerate(dates) if pd.Timestamp(START_FROM) <= t <= pd.Timestamp(START_TO)]
    configs = {"A 正式版": (False, {}), **{f"A＋{k}": (False, v) for k, v in COOL.items()},
               "E 成長股相對規則": (True, {}), **{f"E＋{k}": (True, v) for k, v in COOL.items()}}
    rows = []
    for name, (use_E, extra) in configs.items():
        set_rule(G, dates, orig, R, sig, prof, use_E)
        kw2 = {**kw, "hold_yield": "hy_rel", **extra}
        for s in starts:
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw2)
            rows.append(dict(版本=name, 起跑=dates[s].date(), 期末萬=eq.iloc[-1] * CAPITAL / 1e4,
                             IRR=irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 回撤=100 * (eq / eq.cummax() - 1).min(), 筆數=len(tr)))
        print(f"  {name} 完成", flush=True)
    df = pd.DataFrame(rows); df.round(2).to_csv(RESULTS / "start_dispersion.csv", index=False, encoding="utf-8-sig")
    g = df.groupby("版本").agg(起跑日數=("期末萬", "size"), 期末最小=("期末萬", "min"), 期末中位=("期末萬", "median"), 期末最大=("期末萬", "max"),
                            期末標準差=("期末萬", "std"), IRR最小=("IRR", "min"), IRR中位=("IRR", "median"), IRR最大=("IRR", "max"), IRR標準差=("IRR", "std"))
    g["最大÷最小"] = g["期末最大"] / g["期末最小"]; g["變異係數%"] = 100 * g["期末標準差"] / g["期末中位"]
    g = g.loc[list(configs)]
    g.round(2).to_csv(RESULTS / "start_dispersion_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(f"\n起跑日 {START_FROM}～{START_TO} 每個交易日各跑一次（500 萬不追加，到 {dates[-1].date()}）")
        print(g.round(1).to_string())

    # 20 情境＋後 3 年：A、A＋冷卻、E、E＋冷卻（配對相對 A）
    _to_kw = po.to_kw
    results = {}
    try:
        for i, (name, (use_E, extra)) in enumerate(configs.items()):
            set_rule(G, dates, orig, R, sig, prof, use_E)
            po._applied["buy"] = key
            po.to_kw = lambda cfg, extra=extra: {**_to_kw(cfg), "hold_yield": "hy_rel", **extra}
            po.CONFIGS[name] = dr.FINAL
            m = po.evaluate([name], f"sd_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("sd_0", f"sd_{i}").items():
                    m[k_] = v
            results[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
        for sid, d in G["sub"].items():
            d["buy"] = orig[sid]; d.pop("hy_rel", None)
        po._applied["buy"] = key
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "前7年標準差", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "start_dispersion_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 A）"); print(out[show].round(2).to_string())


if __name__ == "__main__":
    main()
