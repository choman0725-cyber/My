"""單一帳戶、每檔分兩批賣（取代 V1/V2 資金拆帳）。
第 1 批：獲利 >= 10% 且殖利率 < 5% 賣一半；第 2 批：獲利 >= 20% 且殖利率 < 4.5% 賣剩下的。
另測幾種變形，與 V1、V2、五五拆帳對照。用法：python tranche_study.py"""
import pandas as pd

import mix_v12 as mx
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

TRANCHES = {
    "分批｜10%<5% 半 → 20%<4.5% 全": [(0.5, 0.10, 5.0), (0.5, 0.20, 4.5)],
    "分批｜10%<5% 半 → 20%<5% 全": [(0.5, 0.10, 5.0), (0.5, 0.20, 5.0)],
    "分批｜10%<5% 半 → 30%<4.5% 全": [(0.5, 0.10, 5.0), (0.5, 0.30, 4.5)],
    "分批｜10%<5% 半 → 20%<4% 全": [(0.5, 0.10, 5.0), (0.5, 0.20, 4.0)],
    "分批｜三批 10%<5% / 20%<4.75% / 30%<4.5%": [(1 / 3, 0.10, 5.0), (1 / 3, 0.20, 4.75), (1 / 3, 0.30, 4.5)],
    "分批｜10%<5% 三成 → 20%<4.5% 七成": [(0.3, 0.10, 5.0), (0.7, 0.20, 4.5)],
}


def main():
    po.setup()
    po.one_is, po.one_oos = mx.one_is, mx.one_oos
    names = []
    po.CONFIGS["V1 續抱5%＋停利10%"] = mx.V1; po.CONFIGS["V2 續抱4.5%＋停利20%"] = mx.V2
    names += ["V1 續抱5%＋停利10%", "V2 續抱4.5%＋停利20%"]
    mx.MIXES["拆帳｜V1 50%＋V2 50%"] = (mx.V1, mx.V2, 0.5); po.CONFIGS["拆帳｜V1 50%＋V2 50%"] = {**mx.V1}
    names.append("拆帳｜V1 50%＋V2 50%")
    for n, tr in TRANCHES.items():
        po.CONFIGS[n] = {**po.BASE_A, "hold_yield": None, "target": 9.0, "tranches": tr}
        names.append(n)
    m = po.evaluate(names, "tranche")
    out = m.loc[names]
    out.round(2).to_csv(RESULTS / "tranche_summary.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())

    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    money = []
    for name in ["拆帳｜V1 50%＋V2 50%"] + list(TRANCHES):
        mx._prep(name); kw = rs.RULES[name]
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, **kw)
            if sname == "不追加" and name == list(TRANCHES)[0]:
                tr.to_csv(RESULTS / "tranche_trades_500.csv", index=False, encoding="utf-8-sig")
            flows = [CAPITAL] + list(sched.values()); fdates = [dates[1]] + [dates[first_day[y]] for y in sched]
            final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for n in (contrib or {}):
                rets.loc[dates[n]] = (eq.loc[dates[n]] - contrib[n]) / eq.shift(1).loc[dates[n]] - 1
            nav = (1 + rets.fillna(0)).cumprod()
            closed = tr[tr["出場"].notna()]
            money.append(dict(版本=name, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                              IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                              筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(), 最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
    ps.run = mx._orig_run
    mo = pd.DataFrame(money)
    mo.round(1).to_csv(RESULTS / "tranche_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】"); print(mo.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
