"""彙整所有穩健度測試（mix / hold / yieldhold / offset_final），用三段指標排名前五，並以 500 萬試算金額。"""
import pandas as pd

import portfolio_study as ps
import robust_study as rs
import robust_mix as mix
import robust_hold as hold
import robust_yield_hold as yh
import robust_offset_final as of
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

R = RESULTS
cands = {}  # name -> (kw, split_name, IS row, OOS cont row, OOS alone row)

def add(name, kw, split, is_row, oc, oa):
    key = (tuple(sorted((k, str(v)) for k, v in kw.items())), split)
    if key in cands or is_row is None or oc is None or oa is None:
        return
    cands[key] = (name, kw, split, is_row, oc, oa)

mi = pd.read_csv(R / "mix_in_sample_summary.csv", index_col=[0, 1]); mo = pd.read_csv(R / "mix_oos_summary.csv", index_col=[0, 1, 2])
for (v, sp), row in mi.iterrows():
    if ("延續", v, sp) in mo.index:
        add(f"{v}｜{sp}", mix.CONFIGS[v], sp, row, mo.loc[("延續", v, sp)], mo.loc[("單獨", v, sp)])
hi = pd.read_csv(R / "hold_in_sample_summary.csv", index_col=[0, 1, 2]); ho = pd.read_csv(R / "hold_oos_summary.csv", index_col=[0, 1, 2])
for (h, l, sp), row in hi.iterrows():
    v = f"{h}｜{l}"
    if ("延續", v, sp) in ho.index:
        add(f"首選底·{h}·{l}｜{sp}", hold.CONFIGS[v], sp, row, ho.loc[("延續", v, sp)], ho.loc[("單獨", v, sp)])
yi = pd.read_csv(R / "yieldhold_in_sample_summary.csv", index_col=[0, 1, 2]); yo = pd.read_csv(R / "yieldhold_oos_summary.csv", index_col=[0, 1, 2])
for (b, y, sp), row in yi.iterrows():
    v = f"{b}｜{y}"
    add(f"首選底·{b}·{y}｜{sp}", yh.CONFIGS[v], sp, row, yo.loc[("延續", v, sp)], yo.loc[("單獨", v, sp)])
oi = pd.read_csv(R / "offset_final_in_sample.csv", index_col=[0, 1]); oo = pd.read_csv(R / "offset_final_oos.csv", index_col=[0, 1])
for (f, o), row in oi.iterrows():
    v = f"{f}｜{o}"; kw, sp = of.CONFIGS[v]
    add(f"{f}·{o}｜{sp}", kw, sp, row, oo.loc[("延續", v)], oo.loc[("單獨", v)])

rows = []
for name, kw, sp, i, c, a in cands.values():
    rows.append(dict(版本=name, 前7年=i["IRR中位數"], 延續=c["IRR中位數"], 單獨=a["IRR中位數"],
                     三段最差10最小=min(i["IRR最差10"], c["IRR最差10"], a["IRR最差10"]),
                     三段標準差平均=(i["IRR標準差"] + c["IRR標準差"] + a["IRR標準差"]) / 3,
                     前7年回撤=i["回撤中位數"], 最長持有=i["最長持有"]))
t = pd.DataFrame(rows)
t["三段中位平均"] = t[["前7年", "延續", "單獨"]].mean(axis=1)
t["綜合"] = t["三段中位平均"].rank(ascending=False) + t["三段最差10最小"].rank(ascending=False) + t["三段標準差平均"].rank()
t = t.sort_values("綜合").reset_index(drop=True)
t.round(2).to_csv(R / "top_overall_ranking.csv", index=False, encoding="utf-8-sig")
top5 = t.head(5)
with pd.option_context("display.width", 300, "display.max_colwidth", 80, "display.unicode.east_asian_width", True):
    print(f"候選 {len(t)} 個版本，前 10：")
    print(t.head(10)[["版本", "前7年", "延續", "單獨", "三段中位平均", "三段最差10最小", "三段標準差平均", "前7年回撤", "最長持有"]].round(1).to_string())

# 試算：500 萬，2017-01 起，四種追加方式，冷卻 7 天
rs.setup(); G = rs.G; dates = G["dates"]
first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
         "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
by_name = {v[0]: v for v in cands.values()}
out = []
for name in top5["版本"]:
    _, kw, sp, *_ = by_name[name]
    spl = mix.rs.SPLITS.get(sp) if sp in ("不分區", "0050區2＋0056區3", "0050區3＋0056區2") else None
    spl = {"不分區": None, "0050區2＋0056區3": (2, 3), "0050區3＋0056區2": (3, 2)}[sp]
    extra = {"slot_split": {"0050": (spl[0], G["zone"]["0050"]), "0056": (spl[1], G["zone"]["0056"])}} if spl else {}
    for sname, sched in SCHED.items():
        contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, cooldown=7, **kw, **extra)
        flows = [CAPITAL] + list(sched.values()); fdates = [dates[1]] + [dates[first_day[y]] for y in sched]
        final = eq.iloc[-1] * CAPITAL
        rets = eq.pct_change()
        for n in (contrib or {}):
            rets.loc[dates[n]] = (eq.loc[dates[n]] - contrib[n]) / eq.shift(1).loc[dates[n]] - 1
        nav = (1 + rets.fillna(0)).cumprod()
        closed = tr[tr["出場"].notna()]
        out.append(dict(版本=name, 追加=sname, 總投入萬=sum(flows) / 1e4, 期末資產萬=final / 1e4, 獲利萬=(final - sum(flows)) / 1e4,
                        IRR=irr(flows, fdates, final, dates[-1]), 最大回撤=100 * (nav / nav.cummax() - 1).min(),
                        筆數=len(tr), 勝率=100 * (closed["報酬%"] > 0).mean(), 最長持有年=((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365))
o = pd.DataFrame(out)
o.round(1).to_csv(R / "top5_money.csv", index=False, encoding="utf-8-sig")
with pd.option_context("display.width", 300, "display.max_colwidth", 80, "display.unicode.east_asian_width", True):
    print("\n【試算：500 萬起，2017-01 ～ 2026-10】")
    print(o.round(1).to_string(index=False))
