"""進場時把推估殖利率打折（加嚴）的比較。

想法：一半的股利公告會低於推估，所以買進時用「推估 × (1 − 折扣)」和門檻比，只買就算股利少 X% 也還夠便宜的股票。
年配股已公告未除息的日子用的是公告值（確定的數字），不打折；續抱判斷與同日排序預設仍用原推估值。
變化：折扣 10／20／30%；折扣也套用在公告值；折扣也套用在續抱判斷；折扣 20% ＋「低於推估 20% 且低於去年→伺機出場」。
用法：python haircut_study.py（需 results/portfolio_prepared.pkl 與 data/universe/financials_all.csv）
"""
import pickle

import numpy as np
import pandas as pd

import daily_run as dr
import miss_study as ms
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

VARIANTS = {"正式版": dict(cut=0.0)}
for c in (0.10, 0.20, 0.30):
    VARIANTS[f"買進推估打{1 - c:.0%}折"] = dict(cut=c)
VARIANTS["買進打8折(含公告值)"] = dict(cut=0.20, incl_announced=True)
VARIANTS["買進與續抱都打8折"] = dict(cut=0.20, hold=True)
VARIANTS["買進打8折＋低於推估20%且低於去年→伺機出場"] = dict(cut=0.20, miss=("both", 0.20, "tech_profit"))

_orig_apply, _orig_to_kw = po.apply, po.to_kw


def apply2(cfg):
    _orig_apply({k: v for k, v in cfg.items() if k != "haircut"})
    if cfg.get("haircut"):
        thr = po.buy_threshold(cfg)
        sig = rs.G["sig"][po.ENTRIES[cfg["entry"]]]
        for sid, d in rs.G["sub"].items():
            d["buy"] = sig[sid] & ~np.isnan(thr) & (np.nan_to_num(d["yield_buy"], nan=-1) >= thr)


def to_kw2(cfg):
    kw = _orig_to_kw({k: v for k, v in cfg.items() if k not in ("haircut", "miss_exit", "miss_key")})
    if cfg.get("miss_exit"):
        kw.update(miss_exit=cfg["miss_exit"], miss_key=cfg["miss_key"])
    return kw


po.apply, po.to_kw = apply2, to_kw2


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    mem_all = ps.membership(cons, dates)
    est, events = ms.build(data, dates)
    A, A0 = est["A"], est["A0"]
    Yall = pd.DataFrame({s: np.where(mem_all[s].values, A[s], np.nan) for s in A if s in mem_all}, index=dates)
    mk = (Yall.median(axis=1).values, Yall.std(axis=1).values, Yall.notna().sum(axis=1).values)
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)

    rows, money = {}, []
    for name, spec in VARIANTS.items():
        for sid, d in G["sub"].items():
            y = A[sid]
            ann = ~np.isnan(y) & ~np.isnan(A0[sid]) & (np.abs(y - A0[sid]) > 1e-9)   # 用公告值的日子
            disc = y * (1 - spec["cut"])
            yb = disc if spec.get("incl_announced") else np.where(ann, y, disc)
            d["yield_buy"] = yb
            d["yield"] = yb if spec.get("hold") else y
            if spec.get("miss"):
                fl = ms.flags(events, dates, "A0", spec["miss"][0], spec["miss"][1])
                d["miss"] = fl.get(sid, np.zeros(len(dates), bool))
        po._mk[("all", len(dates))] = mk
        po._applied.clear()
        cfg = {**dr.FINAL, "haircut": bool(spec["cut"])}
        if spec.get("miss"):
            cfg.update(miss_exit=spec["miss"][2], miss_key="miss")
        po.CONFIGS[name] = cfg
        po.apply(cfg)
        m = po.evaluate([name], "haircut")
        rows[name] = m.loc[name]
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **po.to_kw(cfg))
        cl = tr[tr["出場"].notna()]
        money.append(dict(版本=name, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                          最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                          平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 全池買訊日數=sum(int(d["buy"].sum()) for d in G["sub"].values()),
                          期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
        tr.to_csv(RESULTS / f"haircut_study_trades_{name}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name} 完成", flush=True)
    M = pd.DataFrame(rows).T
    M.round(2).to_csv(RESULTS / "haircut_study_summary.csv", encoding="utf-8-sig")
    pd.DataFrame(money).to_csv(RESULTS / "haircut_study_money.csv", index=False, encoding="utf-8-sig")
    print("\n【穩健度：前 7 年 20 情境、後 3 年延續／單獨】")
    print(M[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    print("\n【500 萬 2017 起不追加】")
    print(pd.DataFrame(money).to_string(index=False))


if __name__ == "__main__":
    main()
