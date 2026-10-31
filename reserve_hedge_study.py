"""閒錢配置：永遠保留「一份」（總資產 ÷ 5＝20%）當緊急現金，超過一份的閒錢才配置。以新正式版 E＋D 為基準：
  B 其餘放 0050            C 其餘放 0056
  D 其餘：加權指數在 200 日線上放 0050，線下回到現金      E 同 D，但線下改放年化 2%（短債）
  F 其餘年化 4%（純短債）   G 其餘：年線上 0050、年線下年化 4%
近似：視為可即時變現、不計交易成本（條件切換每年約 1～3 次，真實成本約每次 0.3%）。
每個版本：500 萬不追加／每月 10 萬（2017-01-03 與 2016-12-28）、20 情境＋後 3 年＋配對。
用法：python reserve_hedge_study.py   輸出：results/reserve_hedge_eval.csv、reserve_hedge_money.csv"""
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
    px = {e: pd.read_csv(ROOT / "data" / "universe" / "prices" / f"{e}.csv", parse_dates=["date"]).set_index("date")["adj_close"].reindex(d).ffill() for e in ("0050", "0056")}
    r50, r56 = px["0050"].pct_change().fillna(0).values, px["0056"].pct_change().fillna(0).values
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(d).ffill()
    bull = (tai > tai.rolling(200).mean()).shift(1).fillna(False).values.astype(bool)     # 用前一日判斷
    daily2, daily4 = 0.02 / 252, 0.04 / 252
    V = {"正式版 E＋D": {},
         "B 留一份，其餘放 0050": {"cash_index": r50, "cash_reserve": RESERVE},
         "C 留一份，其餘放 0056": {"cash_index": r56, "cash_reserve": RESERVE},
         "D 留一份，年線上 0050／線下現金": {"cash_index": np.where(bull, r50, 0.0), "cash_reserve": RESERVE},
         "E 留一份，年線上 0050／線下 2% 債": {"cash_index": np.where(bull, r50, daily2), "cash_reserve": RESERVE},
         "F 留一份，其餘 4% 債": {"cash_rate": 0.04, "cash_reserve": RESERVE},
         "G 留一份，年線上 0050／線下 4% 債": {"cash_index": np.where(bull, r50, daily4), "cash_reserve": RESERVE}}
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
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "reserve_hedge_money.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(V.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = dr.FINAL
            m = po.evaluate([name], f"rh_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("rh_0", f"rh_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "reserve_hedge_eval.csv", encoding="utf-8-sig")
    piv = mon.pivot_table(index="版本", columns=["起跑", "每月投入萬"], values=["期末萬", "IRR", "回撤"]).loc[list(V)]
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬：期末（萬）／IRR／回撤"); print(piv.round(1).to_string())


if __name__ == "__main__":
    main()
