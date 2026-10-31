"""reserve_hedge_study 的補充：真正的「避險」＝大盤跌破 200 日線時，把超過一份的閒錢改持反向 0050（−1×0050 日報酬，再扣 1% 年費）。
  H 年線上 0050／線下反向      I 年線上現金／線下反向（純避險）
輸出：results/reserve_hedge_inverse_eval.csv / _money.csv（配對相對正式版，沿用 rh_0 的情境檔）"""
import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

RESERVE = 0.20


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    p50 = pd.read_csv(ROOT / "data" / "universe" / "prices" / "0050.csv", parse_dates=["date"]).set_index("date")["adj_close"].reindex(d).ffill()
    r50 = p50.pct_change().fillna(0).values
    inv = -r50 - 0.01 / 252
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(d).ffill()
    bull = (tai > tai.rolling(200).mean()).shift(1).fillna(False).values.astype(bool)
    V = {"H 留一份，年線上 0050／線下反向": {"cash_index": np.where(bull, r50, inv), "cash_reserve": RESERVE},
         "I 留一份，年線上現金／線下反向": {"cash_index": np.where(bull, 0.0, inv), "cash_reserve": RESERVE}}
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows = []
    for name, extra in V.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, **kw, **extra)
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1)))
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "reserve_hedge_inverse_money.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(V.items(), start=10):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = dr.FINAL
            m = po.evaluate([name], f"rh_{i}").loc[name]
            for k_, v in paired_from_files("rh_0", f"rh_{i}").items():
                m[k_] = v
            res[name] = m
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "reserve_hedge_inverse_eval.csv", encoding="utf-8-sig")
    # 年線下的天數與反向在這些天的累積報酬（說明用）
    bear_days = int((~bull[s17:]).sum()); inv_cum = float(np.prod(1 + inv[s17:][~bull[s17:]]) - 1)
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(f"\n2017 起年線下天數 {bear_days}／{len(d) - s17}，反向在年線下日子的累積報酬 {inv_cum * 100:.1f}%")
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.pivot_table(index="版本", columns=["起跑", "每月投入萬"], values=["期末萬", "IRR", "回撤"]).round(1).to_string())


if __name__ == "__main__":
    main()
