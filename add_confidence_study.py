"""加碼金額依「加碼訊號當天的信心值」調整：以新正式版 E＋D 為基準，
   信心 ≥3 → 加碼 ×1.5 或 ×2.0；信心 ≤1 → 加碼 ×0.5 或不加；高低同時用。跌深加碼與定期加碼都乘同一倍數。
每個版本跑 20 情境＋後 3 年＋與正式版的配對＋500 萬。用法：python add_confidence_study.py
輸出：results/add_confidence_eval.csv、add_confidence_money.csv"""
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

VARIANTS = {  # 名稱: (hi, hi_mult, lo, lo_mult)
    "正式版 E＋D（加碼不看信心）": None,
    "信心≥3 加碼×1.5": (3, 1.5, None, 1.0), "信心≥3 加碼×2.0": (3, 2.0, None, 1.0),
    "信心≤1 加碼×0.5": (None, 1.0, 1, 0.5), "信心≤1 不加碼": (None, 1.0, 1, 0.0),
    "≥3 ×1.5、≤1 ×0.5": (3, 1.5, 1, 0.5), "≥3 ×2.0、≤1 不加": (3, 2.0, 1, 0.0),
    "≥4 ×2.0、≤1 ×0.5": (4, 2.0, 1, 0.5),
}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL); key = po._applied["buy"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money = {}, {}
    for i, (name, v) in enumerate(VARIANTS.items()):
        for sid, d in G["sub"].items():
            sc = d["conf_score"]
            mult = np.ones(len(dates))
            if v is not None:
                hi, hm, lo, lm = v
                if hi is not None:
                    mult = np.where(sc >= hi, hm, mult)
                if lo is not None:
                    mult = np.where(sc <= lo, lm, mult)
            d["add_mult"] = mult
        po._applied["buy"] = key
        po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], f"addconf_{i}").loc[name]
        if i:
            for k_, val in paired_from_files("addconf_0", f"addconf_{i}").items():
                m[k_] = val
        results[name] = m
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 加碼次數=int(tr["加碼"].sum()), 資金使用率=round(eq.attrs.get("資金使用率%", np.nan), 0))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    for d in G["sub"].values():
        d.pop("add_mult", None)
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / "add_confidence_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "add_confidence_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版 E＋D）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
