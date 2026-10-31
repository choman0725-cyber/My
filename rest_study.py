"""「某個時間全面出清休息，再伺機重新建倉」會不會更好？
休息觸發：市場貴（全成分股殖利率中位數低於門檻）、大盤轉空（加權指數跌破季線／年線、季線下穿年線）、
組合獲利達標（自上次出清起 +50%／+100%）、固定每 2／3 年。休息期內全部出清、不新買；結束後照正式規則重新建倉。"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    med, sd, cnt = po.market_stats("all")
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(dates).ffill()
    ma60, ma120, ma240 = tx.rolling(60).mean(), tx.rolling(120).mean(), tx.rolling(240).mean()
    R = {
        "市場中位數<3.5%": np.nan_to_num(med, nan=9) < 3.5,
        "市場中位數<3.0%": np.nan_to_num(med, nan=9) < 3.0,
        "市場中位數<4.0%": np.nan_to_num(med, nan=9) < 4.0,
        "大盤<季線": (tx < ma120).values,
        "大盤<年線": (tx < ma240).values,
        "大盤季線<年線(死叉)": (ma60 < ma240).values,
        "大盤<年線 且 市場中位數<4%": ((tx < ma240).values & (np.nan_to_num(med, nan=9) < 4.0)),
    }
    G["rest"] = R
    yrs = pd.DataFrame({k: pd.Series(v, index=dates) for k, v in R.items()}).groupby(dates.year).mean().round(2) * 100
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【各休息條件每年成立的比例 %】"); print(yrs.T.to_string())
    C = {"正式版（不休息）": {}}
    for k in R:
        C[f"休息：{k}"] = {"rest": k}
    C["組合+50% 全出清再建倉"] = {"rest_gain": 0.5}
    C["組合+100% 全出清再建倉"] = {"rest_gain": 1.0}
    C["每 2 年全出清再建倉"] = {"settle": (24, "all")}
    C["每 3 年全出清再建倉"] = {"settle": (36, "all")}
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**dr.FINAL, **x}; names.append(n)
    m = po.evaluate(names, "rest")
    print("\n【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw); cl = tr[tr["出場"].notna()]
        nrest = int((tr["原因"].str.contains("全面|全出清|定期結算")).sum())
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                        出清筆數=nrest, 平均現金pct=round(100 * (1 - np.mean([1 - c for c in [0]]) ) , 1) if False else round(100 - eq.attrs["資金使用率%"], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "rest_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2016-12-28 起不追加】"); print(M.to_string(index=False))

if __name__ == "__main__":
    main()
