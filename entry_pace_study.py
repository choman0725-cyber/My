"""進場節奏（2026-11-01，使用者要求）。動機：2006 起回測裡「先買一部分、等條件再補」意外把 2008 回撤從 −49% 壓到 −31% 而年化不變。
在正式版 E＋D 上測（2017 起 20 情境＋後 3 年＋500 萬）：
  P1 首買分批：先買首買金額的 50%，其餘等該股 20／60 個交易日內再出現技術買點／加碼訊號時補；到期不補（drop）或直接補（add）
  P2 大盤（加權指數）在 200 日線下首買減半      P3 年線下不新買（只加碼）      P6 年線下不加碼
  P2＋P6                                        P4 每週最多新買一檔（one_per_day＋cooldown 5）、每兩週一檔（10）
  P7 首買分批（20 天 drop）＋年線下首買減半
輸出 results/entry_pace_eval.csv、entry_pace_money.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files
from hedge_study import bull_mask


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    bull = bull_mask(d)
    base_ff = {sid: G["sub"][sid]["first_frac"].copy() for sid in G["sub"]}
    # (kwargs, first_frac 乘數陣列 or None, add_mult 陣列 or None)
    variants = {
        "正式版 E＋D": ({}, None, None),
        "P1a 首買分批50%·20天內補·到期不補": ({"first_split": (0.5, 20, "drop")}, None, None),
        "P1b 首買分批50%·20天內補·到期直接補": ({"first_split": (0.5, 20, "add")}, None, None),
        "P1c 首買分批50%·60天內補·到期不補": ({"first_split": (0.5, 60, "drop")}, None, None),
        "P2 年線下首買減半": ({}, np.where(bull, 1.0, 0.5), None),
        "P3 年線下不新買": ({}, np.where(bull, 1.0, 0.0), None),
        "P6 年線下不加碼": ({}, None, np.where(bull, 1.0, 0.0)),
        "P2＋P6 年線下首買減半且不加碼": ({}, np.where(bull, 1.0, 0.5), np.where(bull, 1.0, 0.0)),
        "P4a 每週最多新買一檔": ({"one_per_day": True, "cooldown": 5}, None, None),
        "P4b 每兩週最多新買一檔": ({"one_per_day": True, "cooldown": 10}, None, None),
        "P7 首買分批＋年線下首買減半": ({"first_split": (0.5, 20, "drop")}, np.where(bull, 1.0, 0.5), None),
    }

    def apply_arrays(ffm, am):
        for sid, dd in G["sub"].items():
            dd["first_frac"] = base_ff[sid] * (ffm if ffm is not None else 1.0)
            if am is not None:
                dd["add_mult"] = am
            else:
                dd.pop("add_mult", None)

    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows = []
    for name, (extra, ffm, am) in variants.items():
        apply_arrays(ffm, am)
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                led = []
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, ledger=led, **kw, **extra)
                L = pd.DataFrame(led)
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1),
                                 筆數=len(tr), 第二批補進=int((L["說明"] == "首買分批·第二批").sum()) if len(L) else 0,
                                 資金使用率=round(eq.attrs["資金使用率%"], 0)))
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / "entry_pace_money.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, (extra, ffm, am)) in enumerate(variants.items()):
            apply_arrays(ffm, am)
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = dr.FINAL
            m = po.evaluate([name], f"ep_{i}").loc[name]
            if i:
                for k_, v in paired_from_files("ep_0", f"ep_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
        apply_arrays(None, None)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "前7年回撤", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "entry_pace_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.to_string())


if __name__ == "__main__":
    main()
