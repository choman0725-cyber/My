"""保留的兩個版本（續抱 5%＋停利 10%、續抱 4.5%＋停利 20%），比較持股上限 3 / 5 / 7 檔。
穩健度：前 7 年 20 情境（5 起始日 × 4 追加方式）＋後 3 年延續／單獨；
試算：500 萬自 2017-01 起，四種每年追加方式。用法：python slots_study.py"""
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

VERSIONS = {"V1 續抱5%＋停利10%": {**po.BASE_A, "hold_yield": 5.0, "target": 0.10},
            "V2 續抱4.5%＋停利20%": {**po.BASE_A, "hold_yield": 4.5, "target": 0.20}}
SLOTS = (3, 5, 7)


def main():
    po.setup()
    rows = []
    for v, cfg in VERSIONS.items():
        for k in SLOTS:
            name = f"{v}｜{k}檔"
            po.CONFIGS[name] = {**cfg, "max_slots": k}
            rows.append((v, k, name))
    m = po.evaluate([r[2] for r in rows], "slots")
    out = pd.DataFrame([dict(版本=v, 檔數=k, **m.loc[n].to_dict()) for v, k, n in rows])
    out.round(2).to_csv(RESULTS / "slots_summary.csv", index=False, encoding="utf-8-sig")
    # 追加方式別的樣本內中位數
    runs = pd.read_csv(RESULTS / "param_opt_slots_is_runs.csv")
    tasks = [(n, po.CONFIGS[n]["split"], st, c, 0) for n in [r[2] for r in rows] for st in rs.STARTS for c in rs.CONTRIBS]
    runs["追加"] = [t[3] for t in tasks]
    by_c = runs.groupby(["版本", "追加"])["IRR"].median().unstack()
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("【穩健度】"); print(out[["版本", "檔數"] + po.SHOW + ["前7年回撤", "超過2年比例"]].round(1).to_string(index=False))
        print("\n【前 7 年各追加方式 IRR 中位數】"); print(by_c.round(1).to_string())

    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    money = []
    for v, k, name in rows:
        cfg = po.CONFIGS[name]; po.apply(cfg); kw = po.to_kw(cfg)
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, **kw)
            flows = [CAPITAL] + list(sched.values()); fdates = [dates[1]] + [dates[first_day[y]] for y in sched]
            final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for n in (contrib or {}):
                rets.loc[dates[n]] = (eq.loc[dates[n]] - contrib[n]) / eq.shift(1).loc[dates[n]] - 1
            nav = (1 + rets.fillna(0)).cumprod()
            closed = tr[tr["出場"].notna()]
            money.append(dict(版本=v, 檔數=k, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                              IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                              筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(), 最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
    mo = pd.DataFrame(money)
    mo.round(1).to_csv(RESULTS / "slots_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】"); print(mo.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
