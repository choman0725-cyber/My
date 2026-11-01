"""利潤率模式 vs 純 EPS 法：用單檔完整財報（data/<代號>_financials.csv）比較預估股利的準確度與殖利率分布。

兩種預估都是「預估 EPS × 近 3 年平均配息率」，差別只在預估 EPS：
  EPS法：近四季 EPS
  EPS＋利潤率法：近四季 EPS × 利潤率調整係數（近 2 季毛利率／營業利益率／淨利率 vs 近四季，見 portfolio_study.margin_factor）
準確度：每年股利公告前一天的推估值 vs 實際公告值（年配股在公告後直接用公告值，所以只看公告前）。
輸出 results/<代號>_forward_yield_EPS利潤率法.csv（每日收盤、係數、兩種預估股利與殖利率）。
用法：python margin_yield_study.py [代號]（預設 2382；需要 data/<代號>_financials.csv、_dividend.csv、_dividend_result.csv）
"""
import sys

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import RESULTS, ROOT


def single_stock_tables(stock_id):
    fin = pd.read_csv(ROOT / "data" / f"{stock_id}_financials.csv")
    fin["stock_id"] = fin["stock_id"].astype(str)
    eps_all = fin[fin["type"] == "EPS"][["stock_id", "date", "value"]]
    div_all = pd.read_csv(ROOT / "data" / f"{stock_id}_dividend.csv")
    res_all = pd.read_csv(ROOT / "data" / f"{stock_id}_dividend_result.csv")
    return ps.eps_table(eps_all, stock_id), ps.dividend_events(div_all, stock_id, res_all), ps.margin_table(fin, stock_id)


def accuracy(est, div):
    """每個年度：公告前一天的推估 vs 實際公告股利。"""
    rows = {}
    for fy, r in div.groupby("fy").agg(cash=("cash", "sum"), announced=("announced", "min")).iterrows():
        before = est[est.index < r["announced"]].dropna()
        if len(before) and fy >= 2016:
            rows[fy] = {"實際": r["cash"], "推估": round(before.iloc[-1], 2), "誤差%": round(100 * (before.iloc[-1] / r["cash"] - 1))}
    return pd.DataFrame(rows).T


def main(stock_id="2382"):
    df, raw_close = ps.load_prices(stock_id)
    eps, div, m = single_stock_tables(stock_id)
    factor = ps.margin_factor(df.index, m)
    dps_eps = ps.forward_dividend(df.index, eps, div)
    dps_mg = ps.forward_dividend(df.index, eps, div, factor=factor)
    y_eps, y_mg = 100 * dps_eps / raw_close, 100 * dps_mg / raw_close
    out = pd.DataFrame({"收盤": raw_close, "利潤率係數": factor.round(3), "預估股利_EPS法": dps_eps.round(2),
                        "預估股利_EPS利潤率法": dps_mg.round(2), "殖利率_EPS法%": y_eps.round(2), "殖利率_EPS利潤率法%": y_mg.round(2)})
    out.to_csv(RESULTS / f"{stock_id}_forward_yield_EPS利潤率法.csv", encoding="utf-8-sig")

    q = m.assign(毛利率=m["gross"] / m["revenue"], 營業利益率=m["op"] / m["revenue"], 淨利率=m["net"] / m["revenue"])
    q = q.set_index(q["quarter_end"].dt.strftime("%Y-%m"))[["毛利率", "營業利益率", "淨利率"]] * 100
    fac_q = pd.Series({t.strftime("%Y-%m"): factor[factor.index >= p].iloc[0] if (factor.index >= p).any() else np.nan
                       for t, p in zip(m["quarter_end"], m["published"])})
    q["係數(該季公布後)"] = fac_q
    acc = pd.concat({"EPS法": accuracy(dps_eps, div), "EPS＋利潤率法": accuracy(dps_mg, div)}, axis=1)
    start = df.index[0] + pd.Timedelta(days=400)
    yearly = pd.DataFrame({"EPS法": y_eps[start:].groupby(y_eps[start:].index.year).median(),
                           "EPS＋利潤率法": y_mg[start:].groupby(y_mg[start:].index.year).median(),
                           "係數中位數": factor[start:].groupby(factor[start:].index.year).median()}).round(2)
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(f"【{stock_id} 各季利潤率%與公布後的調整係數】")
        print(q.round(2).tail(16).to_string(), "\n")
        print("【推估準確度：股利公告前一天的推估 vs 實際】")
        print(acc.to_string())
        err = acc.xs("誤差%", axis=1, level=1).abs()
        print("平均絕對誤差%：", err.mean().round(1).to_dict(), "\n")
        print("【每年預估殖利率中位數%】")
        print(yearly.to_string(), "\n")
        t = df.index[-1]
        print(f"最後日 {t.date()}：係數 {factor[t]:.3f}，EPS法 {dps_eps[t]:.2f} 元（{y_eps[t]:.2f}%）→ "
              f"EPS＋利潤率法 {dps_mg[t]:.2f} 元（{y_mg[t]:.2f}%）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
