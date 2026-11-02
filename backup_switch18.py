"""備案「換股 18%」（daily_run.FINAL_SW18）完整數字，與正式版並排（2026-11-02 使用者：「用 18% 載入備案算算看」）。
  1. 20 情境＋後 3 年（配對相對正式版）
  2. 500 萬不追加兩個起跑日、500 萬＋每月 10 萬（2017-01-03 起）：期末、IRR、回撤、筆數、換股次數
  3. 2017-01-03 起 500 萬路徑的逐年報酬
  4. 2006 起快取：2007～2016 每年 1 月起跑，算到 2016 年底與算到今天
  5. 每條路徑的換股明細
用法：python backup_switch18.py　輸出：results/backup_switch18_*.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import rules_research as rr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

V = {"正式版": rr.BASE, "備案 換股18%": {**rr.BASE, **rr.BASE_SW18}}


def path(G, dates, kw, s, monthly=0):
    contrib = dr.monthly_contrib(dates, s, monthly, CAPITAL, None) if monthly else None
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, start_n=s, **kw)
    flows = [CAPITAL] + [v * CAPITAL for v in (contrib or {}).values()]
    fd = [dates[s]] + [dates[k] for k in (contrib or {})]
    final = eq.iloc[-1] * CAPITAL
    return tr, eq, dict(投入萬=round(sum(flows) / 1e4), 期末萬=round(final / 1e4), IRR=round(irr(flows, fd, final, dates[-1]), 1),
                        回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr),
                        換股次數=int(tr["原因"].astype(str).str.startswith("換股").sum()))


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    ev, mon, yr, sw = {}, {}, {}, []
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"bk18_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("bk18_0", f"bk18_{i}").items():
                m[k_] = v
        ev[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for pn, s, mo in (("500萬 2016-12-28 起", 1, 0), ("500萬 2017-01-03 起", s17, 0), ("500萬＋每月10萬 2017-01-03 起", s17, 100_000)):
            tr, eq, r = path(G, dates, kw, s, mo)
            mon[(name, pn)] = r
            sw.append(tr[tr["原因"].astype(str).str.startswith("換股")].assign(版本=name, 路徑=pn))
            if pn == "500萬 2017-01-03 起":
                e = eq * CAPITAL
                yr[name] = (e.groupby(e.index.year).last() / e.groupby(e.index.year).last().shift(1).fillna(CAPITAL) - 1).mul(100).round(1)
    # 2006 起快取：每年 1 月起跑
    import long_history as lh
    H = lh.setup(); d = H["dates"]
    e16 = d.get_indexer([pd.Timestamp("2016-12-30")], method="ffill")[0]
    hist = []
    for name, cfg in V.items():
        po._applied.clear(); po.apply(cfg); kw = po.to_kw(cfg)
        for y in range(2007, 2017):
            s = d.get_indexer([pd.Timestamp(y, 1, 1)], method="bfill")[0]
            tr, eq = ps.run(H["sub"], H["member"], d, capital=CAPITAL, start_n=s, **kw)
            q16 = eq.loc[:d[e16]]
            hist.append(dict(版本=name, 起跑=y, 至2016年底IRR=round(irr([CAPITAL], [d[s]], q16.iloc[-1] / q16.iloc[0] * CAPITAL, d[e16]), 1) if y < 2016 else np.nan,
                             至今IRR=round(irr([CAPITAL], [d[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, d[-1]), 1),
                             換股次數=int(tr["原因"].astype(str).str.startswith("換股").sum())))
    ev = pd.DataFrame(ev).T; mon = pd.DataFrame(mon).T; yr = pd.DataFrame(yr); hist = pd.DataFrame(hist)
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in ev.columns]
    ev[show].to_csv(RESULTS / "backup_switch18_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "backup_switch18_money.csv", encoding="utf-8-sig")
    yr.to_csv(RESULTS / "backup_switch18_yearly.csv", encoding="utf-8-sig"); hist.to_csv(RESULTS / "backup_switch18_hist.csv", index=False, encoding="utf-8-sig")
    pd.concat(sw).to_csv(RESULTS / "backup_switch18_switches.csv", index=False, encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_bk18_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True, "display.max_rows", 100):
        print(ev[show].to_string()); print(mon.to_string()); print(yr.to_string())
        print(hist.pivot(index="起跑", columns="版本", values=["至2016年底IRR", "至今IRR", "換股次數"]).to_string())
        print(pd.concat(sw)[["版本", "路徑", "代號", "進場", "出場", "報酬%", "原因"]].to_string(index=False))


if __name__ == "__main__":
    main()
