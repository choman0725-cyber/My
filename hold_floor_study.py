"""續抱殖利率門檻 4.75% 在「用推估值的日子」改成其他值，年配股已公告的日子維持 4.75%。

賣出（主）：獲利 >= 12% 且預估殖利率 < 續抱門檻；門檻：推估日 = HOLD_EST，公告日 = 4.75。
買進門檻、市場中位數、排序都不變。用法：python hold_floor_study.py
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

HOLDS = (4.75, 4.5, 4.85, 5.0, 5.25, 5.5)
_orig_to_kw = po.to_kw


def to_kw2(cfg):
    kw = _orig_to_kw({k: v for k, v in cfg.items() if k != "hold_est"})
    if cfg.get("hold_est"):
        kw["hold_yield"] = "hy_est"   # 每檔每日門檻陣列
    return kw


po.to_kw = to_kw2


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    est, _ = ms.build(data, dates)
    A, A0 = est["A"], est["A0"]
    ann = {sid: ~np.isnan(A[sid]) & ~np.isnan(A0[sid]) & (np.abs(A[sid] - A0[sid]) > 1e-9) for sid in G["sub"]}
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)

    rows, money = {}, []
    for h in HOLDS:
        name = "正式版（續抱 4.75）" if h == 4.75 else f"推估日續抱 {h}／公告日 4.75"
        for sid, d in G["sub"].items():
            d["hy_est"] = np.where(ann[sid], 4.75, h)
        po._applied.clear()
        cfg = {**dr.FINAL, "hold_est": h if h != 4.75 else None}
        po.CONFIGS[name] = cfg
        po.apply(cfg)
        m = po.evaluate([name], "holdfloor")
        rows[name] = m.loc[name]
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **po.to_kw(cfg))
        cl = tr[tr["出場"].notna()]
        money.append(dict(版本=name, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                          最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                          平均持有日=int(cl["持有日"].mean()) if len(cl) else 0,
                          殖利率續抱賣出=int(cl["原因"].astype(str).str.contains("殖利率").sum()), 期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
        tr.to_csv(RESULTS / f"hold_floor_study_trades_{h}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name} 完成", flush=True)
    M = pd.DataFrame(rows).T
    M.round(2).to_csv(RESULTS / "hold_floor_study_summary.csv", encoding="utf-8-sig")
    pd.DataFrame(money).to_csv(RESULTS / "hold_floor_study_money.csv", index=False, encoding="utf-8-sig")
    print("\n【穩健度：前 7 年 20 情境、後 3 年延續／單獨】")
    print(M[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    print("\n【500 萬 2017 起不追加】")
    print(pd.DataFrame(money).to_string(index=False))


if __name__ == "__main__":
    main()
