"""預估殖利率算法的全池比較：在正式版規則（daily_run.FINAL）下，只換「預估股利」的算法，看績效與推估準確度。

變化（都是 預估 EPS × 配息率，年配股已公告未除息一律用公告值）：
  A 現行：近四季 EPS × 近 3 年平均配息率
  B 近四季 EPS × 利潤率調整係數 × 近 3 年平均（需 financials_all.csv）
  C 年配股待發股利年度四季已公布 → 整年 EPS；否則近四季。× 近 3 年平均
  D C 的 EPS × 最近一個已知年度配息率
  E C 的 EPS × 近 3 年加權配息率（5/3/2）
  G C 的 EPS，年度未完整時近四季 × 利潤率係數。× 近 3 年平均（需 financials_all.csv）
績效：param_opt.evaluate（前 7 年 20 情境、後 3 年延續／單獨）＋ 500 萬 2017 起不追加。
準確度：全池年配股每年股利公告前一天的推估 vs 實際，平均絕對誤差與中位數誤差（2017 年起）。
需要 results/portfolio_prepared.pkl（python portfolio_electronics.py 會建）。用法：python yield_variant_study.py
"""
import pickle

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

VARIANTS = {
    "A 現行：近四季EPS×近3年均": dict(eps_base="ttm", payout="mean"),
    "B 近四季EPS×利潤率係數": dict(eps_base="ttm", payout="mean", margin=True),
    "C 整年EPS(年度完整時)": dict(eps_base="fy", payout="mean"),
    "D 整年EPS×去年配息率": dict(eps_base="fy", payout="last"),
    "E 整年EPS×加權配息率5/3/2": dict(eps_base="fy", payout="weighted"),
    "G 整年EPS，未完整時×利潤率係數": dict(eps_base="fy", payout="mean", margin=True),
}


def build_yields(data, dates):
    """回傳 {變化名: {sid: 每日殖利率陣列}} 與 {變化名: 準確度 DataFrame}。"""
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv")
    div_all = pd.read_csv(ps.UNI / "dividend_all.csv")
    res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv")
    fin_path = ps.UNI / "financials_all.csv"
    fin_all = pd.read_csv(fin_path) if fin_path.exists() else None
    variants = {k: v for k, v in VARIANTS.items() if fin_all is not None or not v.get("margin")}
    if fin_all is None:
        print("沒有 financials_all.csv，略過利潤率係數的變化（B、G）")
    yields = {k: {} for k in variants}
    acc_rows = {k: [] for k in variants}
    for sid in data:
        df, raw_close = ps.load_prices(sid)
        eps, div = ps.eps_table(eps_all, sid), ps.dividend_events(div_all, sid, res_all)
        factor = ps.margin_factor(df.index, ps.margin_table(fin_all, sid)) if fin_all is not None else None
        annual = (div.groupby("fy").size() == 1).all() if len(div) else False
        by = div.groupby("fy").agg(cash=("cash", "sum"), ann=("announced", "min")) if len(div) else None
        for name, spec in variants.items():
            dps = ps.forward_dividend(df.index, eps, div, factor=factor if spec.get("margin") else None,
                                      eps_base=spec["eps_base"], payout=spec["payout"])
            yields[name][sid] = (100 * dps / raw_close).reindex(dates).values
            if annual:
                for fy, r in by.iterrows():
                    if fy < 2016 or r["cash"] <= 0:
                        continue
                    before = dps[dps.index < r["ann"]].dropna()
                    if len(before):
                        acc_rows[name].append(dict(代號=sid, 年度=fy, 實際=r["cash"], 推估=before.iloc[-1], 誤差=100 * (before.iloc[-1] / r["cash"] - 1)))
    acc = {k: pd.DataFrame(v) for k, v in acc_rows.items()}
    return yields, acc


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    mem_all = ps.membership(cons, dates)
    yields, acc = build_yields(data, dates)
    # 檢查：A 版應與 prepared 的 yield 一致
    for sid, d in G["sub"].items():
        a, b = yields["A 現行：近四季EPS×近3年均"][sid], d["yield"]
        assert np.allclose(np.nan_to_num(a, nan=-9), np.nan_to_num(b, nan=-9), atol=1e-9), sid

    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【全池年配股：股利公告前一天的推估 vs 實際（2016 年起）】")
    arow = {}
    for name, a in acc.items():
        e = a["誤差"]
        arow[name] = dict(筆數=len(a), 平均絕對誤差=e.abs().mean(), 中位絕對誤差=e.abs().median(), 中位誤差=e.median(),
                          誤差超過20pct比例=100 * (e.abs() > 20).mean())
    A = pd.DataFrame(arow).T
    print(A.round(1).to_string())
    print()

    rows, money = {}, []
    for name in yields:
        Y = yields[name]
        for sid, d in G["sub"].items():
            d["yield"] = Y[sid]
        Yall = pd.DataFrame({s: np.where(mem_all[s].values, Y[s], np.nan) for s in Y if s in mem_all}, index=dates)
        po._mk[("all", len(dates))] = (Yall.median(axis=1).values, Yall.std(axis=1).values, Yall.notna().sum(axis=1).values)
        po._applied.clear()
        po.CONFIGS[name] = {**dr.FINAL}
        po.apply(po.CONFIGS[name])
        m = po.evaluate([name], "yieldvar")
        rows[name] = m.loc[name]
        kw = po.to_kw(po.CONFIGS[name])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw)
        cl = tr[tr["出場"].notna()]
        money.append(dict(版本=name, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                          最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                          平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
        print(f"  {name} 完成", flush=True)
    M = pd.DataFrame(rows).T
    M.round(2).to_csv(RESULTS / "yield_variant_summary.csv", encoding="utf-8-sig")
    A.round(2).to_csv(RESULTS / "yield_variant_accuracy.csv", encoding="utf-8-sig")
    pd.DataFrame(money).to_csv(RESULTS / "yield_variant_money.csv", index=False, encoding="utf-8-sig")
    print("\n【穩健度：前 7 年 20 情境、後 3 年延續／單獨】")
    print(M[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    print("\n【500 萬 2017 起不追加】")
    print(pd.DataFrame(money).to_string(index=False))


if __name__ == "__main__":
    main()
