"""休息時只賣有賺的、賠錢的留著照常加碼、休息期內不新買；與「全部出清」及正式版對照。"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
import rest_study
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    med, sd, cnt = po.market_stats("all")
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(dates).ffill()
    ma60, ma240 = tx.rolling(60).mean(), tx.rolling(240).mean()
    G["rest"] = {"市場中位數<3.5%": np.nan_to_num(med, nan=9) < 3.5, "市場中位數<4.0%": np.nan_to_num(med, nan=9) < 4.0,
                 "大盤<年線": (tx < ma240).values, "大盤季線<年線(死叉)": (ma60 < ma240).values}
    C = {"正式版（不休息）": {}}
    for k in G["rest"]:
        C[f"休息只賣有賺：{k}"] = {"rest": k, "rest_mode": "profit"}
    C["組合+50% 只賣有賺"] = {"rest_gain": 0.5, "rest_mode": "profit"}
    C["組合+100% 只賣有賺"] = {"rest_gain": 1.0, "rest_mode": "profit"}
    C["每 1 年只賣有賺"] = {"settle": (12, "profit")}
    C["每 2 年只賣有賺"] = {"settle": (24, "profit")}
    C["每 3 年只賣有賺"] = {"settle": (36, "profit")}
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**dr.FINAL, **x}; names.append(n)
    m = po.evaluate(names, "restprofit")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw); cl = tr[tr["出場"].notna()]
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                        休息賣出筆數=int(tr["原因"].str.contains("休息|出清|定期結算").sum()), 平均現金pct=round(100 - eq.attrs["資金使用率%"], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "rest_profit_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2016-12-28 起不追加】"); print(M.to_string(index=False))

if __name__ == "__main__":
    main()
