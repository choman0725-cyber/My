"""把 param_opt 階段一、二的所有設定用三段綜合排名（三段平均、最差 10%、標準差），
並對挑出的最佳參數組合做 500 萬試算。用法：python param_opt_final.py"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

s1 = pd.read_csv(RESULTS / "param_opt_stage1.csv")
s1["組合"] = s1["參數"] + "=" + s1["值"].astype(str)
s1.loc[s1["是底值"], "組合"] = "底"
s2 = pd.read_csv(RESULTS / "param_opt_stage2.csv")
allc = pd.concat([s1[["底", "組合"] + po.SHOW], s2[["底", "組合"] + po.SHOW]]).drop_duplicates(["底", "組合"])
allc["綜合"] = allc["三段平均"].rank(ascending=False) + allc["最差10最小"].rank(ascending=False) + allc["標準差平均"].rank()
allc = allc.sort_values("綜合").reset_index(drop=True)
allc.round(2).to_csv(RESULTS / "param_opt_ranking.csv", index=False, encoding="utf-8-sig")

FINAL = {
    "A 原版": po.BASE_A,
    "A1 停利10%": {**po.BASE_A, "target": 0.10},
    "A2 停利10%＋B3×Rb延後": {**po.BASE_A, "target": 0.10, "defer": "B3×Rb"},
    "A3 定期加碼額度50%": {**po.BASE_A, "time_add_amount": 0.50},
    "B 原版": po.BASE_B,
    "B1 首買65%": {**po.BASE_B, "first": 0.65},
    "B2 首買65%＋B3×Rb延後": {**po.BASE_B, "first": 0.65, "defer": "B3×Rb"},
}


def main():
    po.setup()
    with pd.option_context("display.width", 320, "display.max_rows", 60, "display.max_colwidth", 70, "display.unicode.east_asian_width", True):
        print("【階段一＋二全部設定 三段綜合排名 前 15】")
        print(allc.head(15)[["底", "組合"] + po.SHOW].round(1).to_string(index=False))
    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    out = []
    for name, cfg in FINAL.items():
        po.apply(cfg); kw = po.to_kw(cfg); sp = po.SPLITS[cfg["split"]]
        extra = {"slot_split": {"0050": (sp[0], G["zone"]["0050"]), "0056": (sp[1], G["zone"]["0056"])}} if sp else {}
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, **kw, **extra)
            flows = [CAPITAL] + list(sched.values()); fdates = [dates[1]] + [dates[first_day[y]] for y in sched]
            final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for n in (contrib or {}):
                rets.loc[dates[n]] = (eq.loc[dates[n]] - contrib[n]) / eq.shift(1).loc[dates[n]] - 1
            nav = (1 + rets.fillna(0)).cumprod()
            closed = tr[tr["出場"].notna()]
            out.append(dict(版本=name, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                            IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                            筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(),
                            最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
    o = pd.DataFrame(out)
    o.round(1).to_csv(RESULTS / "param_opt_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 60, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】")
        print(o.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
