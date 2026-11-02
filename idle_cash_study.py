"""閒置現金的去處：以新正式版 E＋D 為基準，閒錢（現金 − 預留）
  (a) 年化 2%／4%（模擬短天期美債 ETF 的利息；長天期美債 ETF 沒有價格資料，且 2022～2023 是負報酬，不在此模擬）
  (b) 放 0050（用 0050 日報酬，視為可即時變現、不計交易成本；預留 0% 與 10%）
看 500 萬不追加／每月 10 萬，兩個起跑日，以及 20 情境＋後 3 年＋配對。
另：放空規則（SHORT_RULES：加權指數 MA5<MA20<MA60 且對 MA20 乖離 −10%～+1%）成立的日子，E＋D 手上有多少閒錢？
用法：python idle_cash_study.py
輸出：results/idle_cash_eval.csv、idle_cash_money.csv、idle_cash_regime.csv"""
import numpy as np
import pandas as pd

import rules_research as rr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    px = pd.read_csv(ROOT / "data" / "universe" / "prices" / "0050.csv", parse_dates=["date"]).set_index("date")["adj_close"].reindex(d).ffill()
    r50 = px.pct_change().fillna(0).values
    V = {"正式版 E＋D（閒錢 0%）": {}, "閒錢年化 2%": {"cash_rate": 0.02}, "閒錢年化 4%": {"cash_rate": 0.04},
         "閒錢放 0050（預留 0%）": {"cash_index": r50}, "閒錢放 0050（預留 10%）": {"cash_index": r50, "cash_reserve": 0.10}}
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first()
    midx = [d.get_loc(t) for t in months.values]
    rows = []
    for name, extra in V.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, **kw, **extra)
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 總投入萬=round(sum(flows) / 1e4), 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1), 筆數=len(tr)))
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "idle_cash_money.csv", index=False, encoding="utf-8-sig")
    # 20 情境
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(V.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = rr.BASE
            m = po.evaluate([name], f"idle_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("idle_0", f"idle_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "idle_cash_eval.csv", encoding="utf-8-sig")
    # 放空環境裡的閒錢
    ledger = []; tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s17, ledger=ledger, **kw)
    L = pd.DataFrame(ledger); L["日期"] = pd.to_datetime(L["日期"])
    cash = L.groupby("日期")["現金"].last().reindex(d).ffill()        # 對帳單的現金已是「本金＝1」的比例
    cash.iloc[:s17] = np.nan
    val = eq.reindex(d)
    cash_pct = (100 * cash / val)
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"].reindex(d).ffill()
    ma5, ma20, ma60 = tai.rolling(5).mean(), tai.rolling(20).mean(), tai.rolling(60).mean()
    bias = 100 * (tai / ma20 - 1)
    bear = ((ma5 < ma20) & (ma20 < ma60) & (bias >= -10) & (bias <= 1)).reindex(d).fillna(False)
    df = pd.DataFrame({"現金%": cash_pct, "空頭環境": bear}).loc[d[s17]:]
    g = df.groupby(df.index.year).apply(lambda x: pd.Series({"交易日": len(x), "空頭環境日": int(x["空頭環境"].sum()), "平均現金%": x["現金%"].mean(),
                                                            "空頭環境時平均現金%": x.loc[x["空頭環境"], "現金%"].mean() if x["空頭環境"].any() else np.nan,
                                                            "現金≥20%的日子": int((x["現金%"] >= 20).sum()),
                                                            "現金≥20%且空頭環境": int(((x["現金%"] >= 20) & x["空頭環境"]).sum())}))
    g.round(1).to_csv(RESULTS / "idle_cash_regime.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n500 萬（不追加／每月 10 萬）"); print(mon.to_string(index=False))
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n放空環境（MA5<MA20<MA60 且乖離 −10～+1%）vs E＋D 的閒錢（2017-01-03 起、不追加）"); print(g.round(1).to_string())
        tot = df; print(f"\n全期：空頭環境日 {int(tot['空頭環境'].sum())}／{len(tot)}；現金≥20% 的日子 {int((tot['現金%']>=20).sum())}，其中在空頭環境的 {int(((tot['現金%']>=20)&tot['空頭環境']).sum())} 天")


if __name__ == "__main__":
    main()
