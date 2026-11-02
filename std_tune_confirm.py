"""std_tune_study 的候選（單次上限 5% 總資產、每檔只補一次）在正式 2017 框架上的確認：20 情境＋配對、500 萬四條路徑、37 個起跑日。
輸出 results/std_tune_confirm_eval.csv、std_tune_confirm_money.csv、start_dispersion_cap5.csv"""
import pandas as pd

import rules_research as rr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

U1 = rr.BASE["topup"]
V = {"U1 正式版": U1, "U1·單次上限 5% 總資產": {**U1, "max_amt": 0.05}, "U1·每檔只補一次": {**U1, "max_per_pos": 1},
     "U1·單次上限 5%＋每檔一次": {**U1, "max_amt": 0.05, "max_per_pos": 1}}


def main():
    po.setup(); G = rs.G; d = G["dates"]
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows, res = [], {}
    for i, (name, tu) in enumerate(V.items()):
        cfg = {**rr.BASE, "topup": tu}; po.apply(cfg); kw = po.to_kw(cfg)
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i_ for i_ in midx if i_ > s] if monthly else []
                contrib = {i_: monthly / CAPITAL for i_ in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i_] for i_ in idx]
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, **kw)
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1), 筆數=len(tr)))
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], f"sc_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("sc_0", f"sc_{i}").items():
                m[k_] = v
        res[name] = m
        print(f"  {name} 完成：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "std_tune_confirm_money.csv", index=False, encoding="utf-8-sig")
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "前7年標準差", "延續", "延續標準差", "單獨", "單獨標準差", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "std_tune_confirm_eval.csv", encoding="utf-8-sig")
    # 37 個起跑日：U1 vs 上限 5%
    cfg_c = {**rr.BASE, "topup": V["U1·單次上限 5% 總資產"]}
    starts = [i_ for i_ in range(1, len(d)) if pd.Timestamp("2016-12-28") <= d[i_] <= pd.Timestamp("2017-02-28")]
    disp = []
    for s in starts:
        po.apply(rr.BASE); e0 = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **po.to_kw(rr.BASE))[1]
        po.apply(cfg_c); e1 = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **po.to_kw(cfg_c))[1]
        disp.append(dict(起跑=d[s].date(), U1萬=round(e0.iloc[-1] * 500), 上限5萬=round(e1.iloc[-1] * 500)))
    D = pd.DataFrame(disp); D["差%"] = ((D["上限5萬"] / D["U1萬"] - 1) * 100).round(1); D.to_csv(RESULTS / "start_dispersion_cap5.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.max_columns", 40, "display.unicode.east_asian_width", True):
        print("\n20 情境（2017 框架，配對相對 U1）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.pivot_table(index="版本", columns=["起跑", "每月投入萬"], values=["期末萬", "IRR", "回撤"], sort=False).round(1).to_string())
        print("\n37 起跑日：上限 5% vs U1  min/中位/max", D["U1萬"].min(), D["U1萬"].median(), D["U1萬"].max(), "→", D["上限5萬"].min(), D["上限5萬"].median(), D["上限5萬"].max(),
              " 贏/平/輸(±2%)", int((D["差%"] > 2).sum()), int((D["差%"].abs() <= 2).sum()), int((D["差%"] < -2).sum()), " 變異係數", round(D["U1萬"].std() / D["U1萬"].mean(), 3), round(D["上限5萬"].std() / D["上限5萬"].mean(), 3))


if __name__ == "__main__":
    main()
