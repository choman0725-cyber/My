"""加碼金額改成「該股票當時市值的 X%」：以新正式版 E＋D 為基準，跌深加碼（−15%／−30% 兩段）各加部位市值 X%，
X＝20／30／40／50%；定期加碼（持有滿半年仍虧損）另測部位市值 20%／30%；並與「額度基準」原版並排。
每個版本跑 20 情境＋後 3 年＋與正式版的配對＋500 萬。用法：python add_position_study.py
輸出：results/add_position_eval.csv、add_position_money.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

for x in (0.20, 0.30, 0.40, 0.50):
    po.ADD_SCHEMES[f"P{int(x * 100)} 部位市值 {int(x * 100)}%/{int(x * 100)}%"] = ((x, x), (-0.15, -0.30))

VARIANTS = {"正式版 E＋D（額度 30/20，定期加碼額度 20%）": {}}
for x in (0.20, 0.30, 0.40, 0.50):
    VARIANTS[f"跌深加碼＝部位市值 {int(x * 100)}%"] = {"adds": f"P{int(x * 100)} 部位市值 {int(x * 100)}%/{int(x * 100)}%", "deep_add_base": "position"}
VARIANTS["跌深加碼＝部位市值 30%＋定期加碼＝部位市值 20%"] = {"adds": "P30 部位市值 30%/30%", "deep_add_base": "position", "time_add_base": "position", "time_add_amount": 0.20}
VARIANTS["跌深加碼＝部位市值 30%＋定期加碼＝部位市值 30%"] = {"adds": "P30 部位市值 30%/30%", "deep_add_base": "position", "time_add_base": "position", "time_add_amount": 0.30}
VARIANTS["跌深額度 30/20＋定期加碼＝部位市值 30%"] = {"time_add_base": "position", "time_add_amount": 0.30}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    names = list(VARIANTS)
    for n, ov in VARIANTS.items():
        po.CONFIGS[n] = {**dr.FINAL, **ov}
    m = po.evaluate(names, "addpos")
    money = {}
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(n, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                  回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 加碼次數=int(tr["加碼"].sum()), 資金使用率=round(eq.attrs.get("資金使用率%", np.nan), 0))
    mon = pd.DataFrame(money).T
    show = ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例"] + po.SHOW_PAIR
    m[show].round(2).to_csv(RESULTS / "add_position_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "add_position_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("20 情境＋後 3 年（配對相對正式版 E＋D）"); print(m[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
