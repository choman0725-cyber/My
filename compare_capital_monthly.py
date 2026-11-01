"""正式版（含 U1 補足）vs 舊正式版（無補足）vs 0050 定期定額：起始 500 萬／1,000 萬 × 每月 5 萬／10 萬，過去 10 年與 20 年。
資料：2006 起快取（long_history.setup）。10 年＝2016-11-01 起、20 年＝2006-11-01 起，到 2026-10-30。
0050：起始資金一次買進、每月第一個交易日以還原收盤買進，不計交易成本。
輸出 results/compare_capital_monthly.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import long_history as lh
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr

HORIZONS = {"過去10年": "2016-11-01", "過去20年": "2006-11-01"}
CAPS = (5_000_000, 10_000_000)
MONTHLY = (50_000, 100_000)


def etf_path(px, d, s, cap, monthly, midx):
    units = cap / px.iloc[s]; cost = cap
    vals = pd.Series(np.nan, index=d[s:])
    for i in range(s, len(d)):
        if i in midx:
            units += monthly / px.iloc[i]; cost += monthly
        vals.iloc[i - s] = units * px.iloc[i]
    return vals


def main():
    G = lh.setup(); d = G["dates"]
    px = pd.read_csv(ps.UNI / "prices" / "0050.csv", parse_dates=["date"]).set_index("date")["adj_close"].reindex(d).ffill()
    cfg_new = dr.FINAL; cfg_old = {k: v for k, v in dr.FINAL.items() if k != "topup"}
    rows = []
    for hname, hstart in HORIZONS.items():
        s = d.get_indexer([pd.Timestamp(hstart)], method="bfill")[0]
        sub = d[s + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
        for cap in CAPS:
            for monthly in MONTHLY:
                contrib = {i: monthly / cap for i in midx}
                flows = [cap] + [monthly] * len(midx); fdates = [d[s]] + [d[i] for i in midx]
                total_in = cap + monthly * len(midx)
                for vname, cfg in (("正式版（含補足 U1）", cfg_new), ("舊正式版（無補足）", cfg_old)):
                    po.apply(cfg); kw = po.to_kw(cfg)
                    tr, eq = ps.run(G["sub"], G["member"], d, capital=cap, contributions=contrib, start_n=s, **kw)
                    end = eq.iloc[-1] * cap
                    rows.append(dict(期間=hname, 起跑=str(d[s].date()), 起始萬=cap / 1e4, 每月萬=monthly / 1e4, 版本=vname, 總投入萬=round(total_in / 1e4),
                                     期末萬=round(end / 1e4), 淨獲利萬=round((end - total_in) / 1e4), IRR=round(irr(flows, fdates, end, d[-1]), 1),
                                     最大回撤=round(oos.nav_dd(eq, contrib), 1), 筆數=len(tr), 勝率=round((tr["報酬%"] > 0).mean() * 100) if len(tr) else None))
                v = etf_path(px, d, s, cap, monthly, set(midx))
                eqe = v / cap
                rows.append(dict(期間=hname, 起跑=str(d[s].date()), 起始萬=cap / 1e4, 每月萬=monthly / 1e4, 版本="0050 定期定額", 總投入萬=round(total_in / 1e4),
                                 期末萬=round(v.iloc[-1] / 1e4), 淨獲利萬=round((v.iloc[-1] - total_in) / 1e4), IRR=round(irr(flows, fdates, v.iloc[-1], d[-1]), 1),
                                 最大回撤=round(oos.nav_dd(eqe, contrib), 1), 筆數=None, 勝率=None))
            print(f"  {hname} {cap / 1e4:.0f} 萬完成", flush=True)
    R = pd.DataFrame(rows); R.to_csv(RESULTS / "compare_capital_monthly.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(R.to_string(index=False))


if __name__ == "__main__":
    main()
