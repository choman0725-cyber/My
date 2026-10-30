"""V1（續抱 5%＋停利 10%）與 V2（續抱 4.5%＋停利 20%）的混合。

方式一：參數取中間值 —— 續抱殖利率 4.5 / 4.75 / 5.0 × 停利 10 / 12 / 15 / 18 / 20。
方式二：資金拆成兩個子帳戶各自照 V1、V2 操作（不互相調整）—— V1 比重 70 / 50 / 30%。
每個設定跑前 7 年 20 情境＋後 3 年驗證，並對較好的做 500 萬試算。用法：python mix_v12.py
"""
import pandas as pd

import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

V1 = {**po.BASE_A, "hold_yield": 5.0, "target": 0.10}
V2 = {**po.BASE_A, "hold_yield": 4.5, "target": 0.20}
MIXES = {}  # name -> (cfg1, cfg2, w1)
_orig_run = ps.run
_cur = {}


def zone_member(etf):
    """只看某一檔 ETF（0050 / 0056）成分股的 member；None＝兩者皆可。"""
    if etf is None:
        return rs.G["member"]
    key = f"member_{etf}"
    if key not in rs.G:
        rs.G[key] = {k: pd.Series(v, index=rs.G["dates"]) for k, v in rs.G["zone"][etf].items()}
    return rs.G[key]


def blended_run(data, member, dates, **kw):
    cfg1, cfg2, w, *etfs = _cur["mix"]
    e1, e2 = etfs if etfs else (None, None)
    po.apply(cfg1); tr1, eq1 = _orig_run(data, zone_member(e1), dates, **kw, **po.to_kw(cfg1))
    po.apply(cfg2); tr2, eq2 = _orig_run(data, zone_member(e2), dates, **kw, **po.to_kw(cfg2))
    return pd.concat([tr1.assign(帳戶="帳戶1"), tr2.assign(帳戶="帳戶2")], ignore_index=True), w * eq1 + (1 - w) * eq2


def _prep(name):
    if name in MIXES:
        _cur["mix"] = MIXES[name]; ps.run = blended_run; rs.RULES[name] = {}
    else:
        ps.run = _orig_run; po.apply(po.CONFIGS[name]); rs.RULES[name] = po.to_kw(po.CONFIGS[name])


def one_is(t):
    _prep(t[0]); return rs.one(t)


def one_oos(t):
    _prep(t[1]); return oos.one(t)


def main():
    po.setup()
    po.one_is, po.one_oos = one_is, one_oos  # 讓 po.evaluate 用這裡的工作函式
    rows = []
    for hy in (4.5, 4.75, 5.0):
        for t in (0.10, 0.12, 0.15, 0.18, 0.20):
            name = f"參數｜續抱{hy}%＋停利{t:.0%}"
            po.CONFIGS[name] = {**po.BASE_A, "hold_yield": hy, "target": t}
            rows.append(("參數中間值", name))
    for w in (0.7, 0.5, 0.3):
        name = f"資金｜V1 {w:.0%}＋V2 {1 - w:.0%}"
        MIXES[name] = (V1, V2, w); po.CONFIGS[name] = {**V1, "split": "不分區"}
        rows.append(("資金拆帳", name))
    names = [n for _, n in rows]
    m = po.evaluate(names, "mix12")
    out = pd.DataFrame([dict(方式=k, 版本=n, **m.loc[n].to_dict()) for k, n in rows])
    out.round(2).to_csv(RESULTS / "mix_v12_summary.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out[["方式", "版本"] + po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string(index=False))

    G = rs.G; dates = G["dates"]
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    picks = ["參數｜續抱4.75%＋停利15%", "參數｜續抱5.0%＋停利15%", "參數｜續抱4.75%＋停利10%", "參數｜續抱4.75%＋停利20%",
             "資金｜V1 70%＋V2 30%", "資金｜V1 50%＋V2 50%", "資金｜V1 30%＋V2 70%"]
    money = []
    for name in picks:
        _prep(name)
        kw = rs.RULES[name]
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
            money.append(dict(版本=name, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                              IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                              筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(), 最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
    ps.run = _orig_run
    mo = pd.DataFrame(money)
    mo.round(1).to_csv(RESULTS / "mix_v12_money.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n【500 萬試算 2017-01 ～ 2026-10】"); print(mo.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
