"""買進門檻的 5% 底線在「用推估值的日子」提高（5.1／5.2／…），年配股已公告的日子維持 5%。

買進門檻 = max(當天全成分股推估殖利率中位數, 底線)；底線：推估日 = FLOOR_EST，公告日 = 5.0。
市場中位數、續抱 4.75%、同日排序都不變。用法：python floor_study.py
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

FLOORS = (5.0, 5.1, 5.2, 5.3, 5.5, 6.0)
_orig_apply, _orig_to_kw = po.apply, po.to_kw


def apply2(cfg):
    _orig_apply({k: v for k, v in cfg.items() if k != "floor_est"})
    if cfg.get("floor_est"):
        med, _, _ = po.market_stats("all")
        thr_est, thr_ann = np.fmax(med, cfg["floor_est"]), np.fmax(med, 5.0)
        sig = rs.G["sig"][po.ENTRIES[cfg["entry"]]]
        for sid, d in rs.G["sub"].items():
            thr = np.where(d["ann_day"], thr_ann, thr_est)
            d["buy"] = sig[sid] & ~np.isnan(thr) & (np.nan_to_num(d["yield"], nan=-1) >= thr)


def to_kw2(cfg):
    return _orig_to_kw({k: v for k, v in cfg.items() if k != "floor_est"})


po.apply, po.to_kw = apply2, to_kw2


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    est, _ = ms.build(data, dates)
    A, A0 = est["A"], est["A0"]
    for sid, d in G["sub"].items():
        y = A[sid]
        d["ann_day"] = ~np.isnan(y) & ~np.isnan(A0[sid]) & (np.abs(y - A0[sid]) > 1e-9)
    med, _, _ = po.market_stats("all")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    S = pd.Series(med, index=dates)
    print("【每年市場中位數低於各底線的交易日比例%（底線有作用的日子）】")
    print(pd.DataFrame({f"<{f}": S.groupby(S.index.year).apply(lambda x: 100 * (x < f).mean()) for f in FLOORS}).round(0).to_string())

    rows, money = {}, []
    for f in FLOORS:
        name = "正式版（底線 5.0）" if f == 5.0 else f"推估日底線 {f}／公告日 5.0"
        po._applied.clear()
        cfg = {**dr.FINAL, "floor_est": f if f != 5.0 else None}
        po.CONFIGS[name] = cfg
        po.apply(cfg)
        m = po.evaluate([name], "floor")
        rows[name] = m.loc[name]
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **po.to_kw(cfg))
        cl = tr[tr["出場"].notna()]
        money.append(dict(版本=name, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                          最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                          平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 全池買訊日數=sum(int(d["buy"].sum()) for d in G["sub"].values()),
                          期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
        tr.to_csv(RESULTS / f"floor_study_trades_{f}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name} 完成", flush=True)
    M = pd.DataFrame(rows).T
    M.round(2).to_csv(RESULTS / "floor_study_summary.csv", encoding="utf-8-sig")
    pd.DataFrame(money).to_csv(RESULTS / "floor_study_money.csv", index=False, encoding="utf-8-sig")
    print("\n【穩健度：前 7 年 20 情境、後 3 年延續／單獨】")
    print(M[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    print("\n【500 萬 2017 起不追加】")
    print(pd.DataFrame(money).to_string(index=False))


if __name__ == "__main__":
    main()
