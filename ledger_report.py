"""正式版（續抱 4.75%＋停利 12%）完整對帳單：每一筆買進／加碼／賣出的日期、價格、股數、金額、成交後現金與持股，
以及每年年底的持股明細與資產。預設 500 萬、2017-01 起、不追加。

用法：python ledger_report.py [--capital 5000000] [--start 2017-01-03] [--contrib 2018:500000,...]
輸出：results/對帳單_正式版.csv（逐筆）、results/對帳單_正式版_年底持股.csv、results/對帳單_正式版.md（可直接閱讀）
"""
import argparse

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT, SELL_COST
from portfolio_contrib import irr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--start", default="2017-01-03")
    ap.add_argument("--contrib", default="")
    a = ap.parse_args()
    cap = a.capital
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    names = pd.read_csv(ROOT / "data" / "universe" / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]
    s_n = dates.get_indexer([pd.Timestamp(a.start)], method="bfill")[0]
    sched = {int(y): float(v) for y, v in (x.split(":") for x in a.contrib.split(",") if x)}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched if (dates.year == y).any()}
    contrib = {first_day[y]: sched[y] / cap for y in first_day} or None

    ledger = []
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=cap, contributions=contrib, start_n=s_n, ledger=ledger, **kw)
    L = pd.DataFrame(ledger)
    L["名稱"] = L["代號"].map(names).fillna("")
    for c in ("金額", "現金", "持股市值", "總資產"):
        L[c] = (L[c] * cap).round(0)
    L["股數"] = (L["股數"] * cap).round(0)
    L["價格"] = L["價格"].round(2)
    L["說明"] = L["說明"].str.replace(r"成本 ([0-9.]+)", lambda m: f"成本 {float(m.group(1)) * cap / 1e4:,.1f} 萬", regex=True) \
                     .str.replace(r"額度 ([0-9.]+)", lambda m: f"額度 {float(m.group(1)) * cap / 1e4:,.1f} 萬", regex=True)
    L["庫存水位pct"] = (100 * L["持股市值"] / L["總資產"]).round(1)
    L["現金pct"] = (100 * L["現金"] / L["總資產"]).round(1)
    L = L[["日期", "代號", "名稱", "動作", "價格", "股數", "金額", "說明", "現金", "現金pct", "持股檔數", "持股市值", "庫存水位pct", "總資產", "持股"]]
    L.to_csv(RESULTS / "對帳單_正式版.csv", index=False, encoding="utf-8-sig")

    # 年底持股快照：重跑到每年最後一個交易日取部位
    snaps = []
    for y in sorted(set(dates[s_n:].year)):
        e_n = int(np.where(dates.year == y)[0][-1])
        _, eq_y = ps.run(G["sub"], G["member"], dates, capital=cap, contributions=contrib, start_n=s_n, end_n=e_n, **kw)
        pos, cash = eq_y.attrs["positions"], eq_y.attrs["cash"]
        total = eq_y.iloc[-1] * cap
        for sid, q in pos.items():
            px = G["sub"][sid]["close_ff"][e_n]; avg = q["cost"] / q["shares"]
            snaps.append(dict(年底=dates[e_n].date(), 代號=sid, 名稱=names.get(sid, ""), 進場=dates[q["start"]].date(), 股數=round(q["shares"] * cap),
                              平均成本=round(avg, 2), 收盤=round(px, 2), 市值=round(q["shares"] * px * cap), 損益pct=round(100 * (px / avg - 1), 1),
                              占比pct=round(100 * q["shares"] * px * cap / total, 1), 已加碼=q["adds"] + q.get("time_adds", 0)))
        snaps.append(dict(年底=dates[e_n].date(), 代號="現金", 名稱="", 進場="", 股數="", 平均成本="", 收盤="", 市值=round(cash * cap),
                          損益pct="", 占比pct=round(100 * cash / eq_y.iloc[-1], 1), 已加碼=""))
        snaps.append(dict(年底=dates[e_n].date(), 代號="合計", 名稱="", 進場="", 股數="", 平均成本="", 收盤="", 市值=round(total),
                          損益pct="", 占比pct=100.0, 已加碼=""))
    S = pd.DataFrame(snaps)
    S.to_csv(RESULTS / "對帳單_正式版_年底持股.csv", index=False, encoding="utf-8-sig")

    # 每月月底庫存水位
    months = []
    for me in pd.Series(dates[s_n:]).groupby(dates[s_n:].to_period("M")).last():
        e_n = dates.get_loc(me)
        _, eq_m = ps.run(G["sub"], G["member"], dates, capital=cap, contributions=contrib, start_n=s_n, end_n=e_n, **kw)
        pos, cash = eq_m.attrs["positions"], eq_m.attrs["cash"]; total = eq_m.iloc[-1]
        w = sorted(((q["shares"] * G["sub"][sid]["close_ff"][e_n] / total, sid) for sid, q in pos.items()), reverse=True)
        months.append(dict(月底=me.date(), 總資產萬=round(total * cap / 1e4), 現金萬=round(cash * cap / 1e4), 現金pct=round(100 * cash / total, 1),
                           庫存水位pct=round(100 * (1 - cash / total), 1), 持股檔數=len(pos), 佔名額檔數=sum(1 for sid, q in pos.items()
                               if not ((dates[e_n] - dates[q["start"]]).days > ps.STALE_DAYS or G["sub"][sid]["close_ff"][e_n] / (q["cost"] / q["shares"]) - 1 < ps.STALE_LOSS)
                               and G["member"][sid].iloc[e_n]),
                           持股=" ".join(f"{sid}({100 * wt:.0f}%)" for wt, sid in w)))
    MO = pd.DataFrame(months); MO.to_csv(RESULTS / "對帳單_正式版_月底水位.csv", index=False, encoding="utf-8-sig")

    # 年報酬與總結
    yr = eq.groupby(eq.index.year).last() * cap
    base = pd.Series({dates[s_n].year - 1: cap})
    rets = pd.concat([base, yr]).pct_change().dropna() * 100
    flows = [cap] + [sched[y] for y in first_day]; fdates = [dates[s_n]] + [dates[first_day[y]] for y in first_day]
    final = eq.iloc[-1] * cap
    closed = tr[tr["出場"].notna()]
    nav = eq / eq.cummax() - 1

    md = [f"# 正式版對帳單（續抱殖利率 4.75%＋停利 12%，最多 5 檔）", "",
          f"期間 {dates[s_n].date()} ～ {dates[-1].date()}；初始 {cap / 1e4:,.0f} 萬" + (f"，追加合計 {sum(sched.values()) / 1e4:,.0f} 萬" if sched else "") + "。",
          f"期末資產 **{final / 1e4:,.0f} 萬**，IRR **{irr(flows, fdates, final, dates[-1]):.1f}%**，最大回撤 {100 * nav.min():.1f}%，"
          f"交易 {len(tr)} 筆（已結案 {len(closed)} 筆，勝率 {100 * (closed['報酬%'] > 0).mean():.0f}%），買賣都隔天開盤，含手續費與證交稅。", "",
          "## 每年資產", "", "| 年 | 年底資產（萬） | 年報酬 |", "|---|---|---|"]
    for y, v in yr.items():
        md.append(f"| {y} | {v / 1e4:,.0f} | {rets.get(y, np.nan):+.1f}% |")
    md += ["", "## 逐筆交易", "", "金額含成本；「現金」「總資產」是這筆成交後的數字（持股以前一日收盤計）。", "",
           "| 日期 | 代號 | 動作 | 價格 | 股數 | 金額（萬） | 說明 | 現金（萬） | 現金% | 庫存水位% | 檔數 | 總資產（萬） | 持股（占比） |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in L.iterrows():
        md.append(f"| {r['日期'].date()} | {r['代號']} {r['名稱']} | {r['動作']} | {'' if np.isnan(r['價格']) else r['價格']} | {r['股數']:,.0f} | {r['金額'] / 1e4:,.1f} | {r['說明']} | {r['現金'] / 1e4:,.0f} | {r['現金pct']} | {r['庫存水位pct']} | {r['持股檔數']} | {r['總資產'] / 1e4:,.0f} | {r['持股']} |")
    md += ["", "## 每月月底庫存水位", "", "| 月底 | 總資產（萬） | 現金（萬） | 現金% | 庫存水位% | 持股檔數 | 佔名額 | 持股（占比） |", "|---|---|---|---|---|---|---|---|"]
    for _, r in MO.iterrows():
        md.append(f"| {r['月底']} | {r['總資產萬']:,} | {r['現金萬']:,} | {r['現金pct']} | {r['庫存水位pct']} | {r['持股檔數']} | {r['佔名額檔數']}/5 | {r['持股']} |")
    md += ["", "## 每年年底持股", ""]
    for y, g in S.groupby("年底", sort=True):
        md += [f"### {y}", "", "| 代號 | 進場 | 股數 | 平均成本 | 收盤 | 市值（萬） | 損益 | 占比 | 加碼次數 |", "|---|---|---|---|---|---|---|---|---|"]
        for _, r in g.iterrows():
            md.append(f"| {r['代號']} {r['名稱']} | {r['進場']} | {r['股數']:,} | {r['平均成本']} | {r['收盤']} | {r['市值'] / 1e4:,.1f} | "
                      f"{'' if r['損益pct'] == '' else f'{r['損益pct']:+.1f}%'} | {r['占比pct']}% | {r['已加碼']} |" if r["代號"] not in ("現金", "合計") else
                      f"| **{r['代號']}** | | | | | **{r['市值'] / 1e4:,.1f}** | | {r['占比pct']}% | |")
        md.append("")
    (RESULTS / "對帳單_正式版.md").write_text("\n".join(md), encoding="utf-8")
    with pd.option_context("display.width", 320, "display.max_rows", 400, "display.max_colwidth", 60, "display.unicode.east_asian_width", True):
        print("\n".join(md[:6]))
        print(L[["日期", "代號", "名稱", "動作", "價格", "股數", "金額", "現金", "總資產"]].to_string(index=False))
    # 核對：帳本最後現金／總資產與引擎一致
    assert abs(L["現金"].iloc[-1] - eq.attrs["cash"] * cap) < 1, "帳本現金與引擎不符"


if __name__ == "__main__":
    main()
