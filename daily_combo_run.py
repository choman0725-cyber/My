"""做多為主、閒錢放空的每日執行程式：先列做多正式版明天的動作，再列「用多頭閒錢」的放空動作。

原則（COMBO_RULES.md）：
  1. 做多正式版（FINAL_RULES.md）照常執行，決策完全不看放空。
  2. 放空規則用 SHORT_RULES.md 進取版（殖利率 <2%＋大盤空頭排列＋乖離 −10%～+1%＋鏡像技術放空點；跌 5% 回補、
     大盤轉多且賺 2% 連兩日回補；不停損），訊號、制度、成本全部沿用 short_strategy.py。
  3. 放空只能用多頭的閒錢：閒錢 ＝ 多頭現金 ＋ 放空累計損益 − 總資產 × 20%（預留兩筆多頭首買）。
     每筆放空名目 ＝ 總資產 ÷ 10；閒錢不夠付一筆名目的 90% 保證金就不放空（不縮小、不排隊）；最多 5 檔；多頭持有中的股票不放空。
  4. 多頭明天要買股而現金不夠維持保證金 → 同一天開盤先回補放空（浮虧最大的先）。20 情境回測裡沒發生過。

做法同 daily_run.py：用規則從起始日重跑到最新資料日得到目前的多頭持股、現金與空單，再加一個虛擬交易日讓兩個引擎做決策，
差異就是明天開盤要做的事。
用法：python daily_combo_run.py [--capital 5000000] [--start 2017-01-03] [--contrib 2025:1000000,2026:1000000] [--asof 2026-06-30]
資料更新：先依 daily_run.py 的說明重建 results/portfolio_prepared.pkl。
"""
import argparse

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
import short_combo_study as sc
import short_strategy as ss
from backtest import ROOT

SIZE, RESERVE, SHRINK = 0.10, 0.20, False


def extend_short_data(S, dates2):
    """放空資料加一個虛擬日：開盤＝最後收盤，訊號 False，制度日期沿用。"""
    A2 = {}
    for sid, a in S["A"].items():
        b = {}
        for k, v in a.items():
            if isinstance(v, np.ndarray) and len(v) == len(dates2) - 1:
                if v.dtype == bool:
                    b[k] = np.append(v, v[-1] if k in ("block",) else False)
                elif k == "open":
                    b[k] = np.append(v, a["close_ff"][-1])
                elif k in ("close", "close_ff"):
                    b[k] = np.append(v, a["close_ff"][-1])
                else:
                    b[k] = np.append(v, v[-1])
            else:
                b[k] = v
        A2[sid] = b
    return {"dates": dates2, "A": A2, "bear": np.append(S["bear"], S["bear"][-1])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--start", default="2017-01-03")
    ap.add_argument("--contrib", default="")
    ap.add_argument("--asof", default=None)
    a = ap.parse_args()
    cap = a.capital

    sc.setup(); G = rs.G
    if a.asof:
        cut = pd.Timestamp(a.asof); keep = G["dates"] <= cut; n_keep = int(keep.sum())
        G["dates"] = G["dates"][keep]
        for sid, d in G["sub"].items():
            for k, v in list(d.items()):
                if isinstance(v, np.ndarray) and len(v) == len(keep):
                    d[k] = v[:n_keep]
            d["last_n"] = min(d["last_n"], n_keep + 1) if d["last_n"] <= n_keep else n_keep + 1
        G["member"] = {k: v.iloc[:n_keep] for k, v in G["member"].items()}
        G["sig"] = {e: {sid: v[:n_keep] for sid, v in m.items()} for e, m in G["sig"].items()}
        po._mk.clear(); po.apply(dr.FINAL)
        for sid, x in sc.S["A"].items():
            for k, v in list(x.items()):
                if isinstance(v, np.ndarray) and len(v) == len(keep):
                    x[k] = v[:n_keep]
            x["delist_n"] = min(x["delist_n"], n_keep + 1) if x["delist_n"] <= n_keep else n_keep + 1
        sc.S["dates"] = G["dates"]; sc.S["bear"] = sc.S["bear"][:n_keep]
        sc.si.S.update(dates=G["dates"], N=n_keep)
    dates = G["dates"]
    sched = {int(y): float(v) for y, v in (x.split(":") for x in a.contrib.split(",") if x)}
    names = pd.read_csv(ROOT / "data" / "universe" / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]

    # 1. 跑到最新資料日：多頭狀態 ＋ 空單狀態
    L = sc.long_path(a.start, sched)
    T, comb, _ = sc.simulate(L, "idle", size=SIZE, reserve=RESERVE, shrink=SHRINK)
    p = len(dates) - 1
    long_pos = {sid: q for sid, q in ps.run(G["sub"], G["member"], dates, capital=cap, contributions=L["contrib"] or None,
                                           start_n=L["s_n"], **po.to_kw(dr.FINAL))[1].attrs["positions"].items()}
    open_shorts = T[T["原因"] == "持有中"]
    closed = T[T["原因"] != "持有中"]
    realized = closed["損益"].sum()
    mtm = open_shorts["損益"].sum()
    assets = comb.iloc[-1]
    long_cash = L["cash"][p]
    idle = long_cash + realized + mtm - RESERVE * assets

    # 2. 虛擬日：多頭與放空都做一次決策
    dates2, sub2, member2 = dr.extend_one_day(G)
    G_backup = dict(G); G.update(dates=dates2, sub=sub2, member=member2)
    S_backup = dict(sc.S); sc.S.update(extend_short_data(S_backup, dates2)); sc.si.S.update(dates=dates2, N=len(dates2))
    L2 = sc.long_path(a.start, sched)
    T2, comb2, _ = sc.simulate(L2, "idle", size=SIZE, reserve=RESERVE, shrink=SHRINK)
    long_pos2 = ps.run(sub2, member2, dates2, capital=cap, contributions=L2["contrib"] or None, start_n=L2["s_n"], **po.to_kw(dr.FINAL))[1].attrs["positions"]
    G.update(G_backup); sc.S.update(S_backup); sc.si.S.update(dates=dates, N=len(dates))
    shorts2 = T2[T2["原因"] == "持有中"]
    fake = dates2[-1]

    med, sd, cnt = po.market_stats("all"); thr = po.buy_threshold(dr.FINAL)
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    tai = tai[tai.index <= dates[-1]]
    bear, bias_ok, bias = ss.market_state(tai)
    print(dr.RULE_TEXT)
    print("放空（附加）：SHORT_RULES.md 進取版，只用多頭閒錢；閒錢＝多頭現金＋放空累計損益−總資產×20%；每筆名目＝總資產÷10，閒錢不夠就不空；最多 5 檔")
    print(f"\n資料最後日期：{dates[-1].date()}　起始 {dates[L['s_n']].date()}　投入 {cap / 1e4:,.0f} 萬" + (f"＋追加 {sum(sched.values()) / 1e4:,.0f} 萬" if sched else ""))
    print(f"多頭資產 {L['eq'][p] * cap / 1e4:,.0f} 萬（現金 {long_cash * cap / 1e4:,.0f} 萬）；放空累計已實現 {realized * cap / 1e4:+,.1f} 萬、未實現 {mtm * cap / 1e4:+,.1f} 萬；合併總資產 {assets * cap / 1e4:,.0f} 萬")
    print(f"放空可用閒錢 {max(idle, 0) * cap / 1e4:,.0f} 萬（一筆放空名目 {assets * SIZE * cap / 1e4:,.0f} 萬需保證金 {assets * SIZE * 0.9 * cap / 1e4:,.0f} 萬）→ "
          + ("可以新放空" if idle >= assets * SIZE * 0.9 else "閒錢不足，不新放空"))
    print(f"今日全成分股預估殖利率中位數 {med[p]:.2f}% → 多頭買進門檻 {thr[p]:.2f}%；加權指數 {tai.iloc[-1]:,.0f}，"
          f"{'空頭排列' if bear.iloc[-1] else '非空頭排列'}，對月線乖離 {bias.iloc[-1]:+.1f}% → {'可以新放空' if (bear.iloc[-1] and bias_ok.iloc[-1]) else '放空環境不成立'}")

    pd.set_option("display.width", 300); pd.set_option("display.unicode.east_asian_width", True); pd.set_option("display.max_rows", 200)
    print("\n【目前多頭持股】")
    rows = []
    for sid, q in long_pos.items():
        d = G["sub"][sid]; px = d["close_ff"][p]; avg = q["cost"] / q["shares"]; y = d["yield"][p]
        rows.append(dict(代號=sid, 名稱=names.get(sid, ""), 進場=dates[q["start"]].date(), 股數=round(q["shares"] * cap), 平均成本=round(avg, 1), 現價=px,
                         損益pct=round(100 * (px / avg - 1), 1), 市值萬=round(q["shares"] * px * cap / 1e4, 1), 預估殖利率=None if np.isnan(y) else round(y, 2)))
    print(pd.DataFrame(rows).to_string(index=False) if rows else "（無）")
    print("\n【目前空單】")
    if len(open_shorts):
        o = open_shorts.copy()
        o["名目萬"] = (o["名目"] * cap / 1e4).round(1); o["浮動損益萬"] = (o["損益"] * cap / 1e4).round(1); o["獲利%"] = (100 * o["報酬率"]).round(1)
        o["進場"] = pd.to_datetime(o["進場"]).dt.date
        print(o[["代號", "名稱", "進場", "放空價", "回補價", "天數", "名目萬", "獲利%", "浮動損益萬"]].rename(columns={"回補價": "現價"}).to_string(index=False))
    else:
        print("（無）")

    print(f"\n【明天（{dates[-1].date()} 之後第一個交易日）開盤要做的事】")
    acts = ["— 做多（優先）—"]
    for sid in long_pos:
        if sid not in long_pos2:
            acts.append(f"賣出 {sid} {names.get(sid, '')}：全部 {round(long_pos[sid]['shares'] * cap)} 股")
        elif long_pos2[sid]["shares"] > long_pos[sid]["shares"] + 1e-12:
            acts.append(f"加碼 {sid} {names.get(sid, '')}：約 {(long_pos2[sid]['cost'] - long_pos[sid]['cost']) * cap / 1e4:,.1f} 萬")
    for sid in long_pos2:
        if sid not in long_pos:
            acts.append(f"買進 {sid} {names.get(sid, '')}：約 {long_pos2[sid]['cost'] * cap / 1e4:,.1f} 萬（預估殖利率 {G['sub'][sid]['yield'][p]:.2f}%）")
    if len(acts) == 1:
        acts.append("沒有動作")
    acts.append("— 放空（只用閒錢）—")
    cur = set(open_shorts["代號"]); nxt = set(shorts2["代號"])
    for _, r in T2[(T2["出場"] == fake)].iterrows():
        acts.append(f"回補 {r['代號']} {r['名稱']}：全部，原因「{r['原因']}」，獲利 {100 * r['報酬率']:+.1f}%（{r['損益'] * cap / 1e4:+,.1f} 萬）")
    for _, r in shorts2[~shorts2["代號"].isin(cur)].iterrows():
        acts.append(f"放空 {r['代號']} {r['名稱']}：名目約 {r['名目'] * cap / 1e4:,.1f} 萬（預估殖利率 {sc.S['A'][r['代號']]['yield'][p]:.2f}%，停利目標＝放空價 ×0.95）")
    if acts[-1] == "— 放空（只用閒錢）—":
        acts.append("沒有動作")
    print("\n".join(acts))
    T.to_csv(ps.RESULTS / "daily_combo_short_trades.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
