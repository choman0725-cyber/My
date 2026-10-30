"""正式版每日執行程式：殖利率法＋技術買點，續抱殖利率 4.75%、停利 12%，單一帳戶最多 5 檔。

做法：用正式規則從起始日把歷史重跑到最新資料日，得到「目前應有的持股與現金」，再加一個虛擬的下一個交易日
讓引擎做決策，差異就是明天開盤要執行的買進／加碼／賣出（引擎的決策都以前一天收盤為準、隔天開盤成交）。

用法：
  python daily_run.py                                    # 500 萬、2017-01 起、不追加
  python daily_run.py --capital 5000000 --start 2024-01-02 --contrib 2025:1000000,2026:1000000
  python daily_run.py --asof 2026-06-30                  # 假裝今天是 2026-06-30（回看當時的建議）
資料更新：data/universe/prices/*.csv、eps_all.csv、dividend_all.csv 更新後先重跑
  python portfolio_electronics.py 以重建 results/portfolio_prepared.pkl，再執行本程式。
"""
import argparse
import copy

import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import ROOT, SELL_COST

FINAL = {**po.BASE_A, "hold_yield": 4.75, "target": 0.12}
RULE_TEXT = """正式規則（單一帳戶，最多 5 檔，只做多，買賣都隔天開盤）
  選股：當天屬於 0050 或 0056 成分股的電子股（排除電信、川湖）
  買進：預估殖利率 >= 5%（近四季 EPS × 近 3 年平均配息率；年配且已公告未除息用公告值）
        且技術買點任一：多指標超賣共振／爆量長下影線或爆量長紅／布林下軌＋KD 低檔金叉／低檔區＋價量
        同日多檔依殖利率高到低挑；每檔額度＝當時總資產 ÷ 5，首買額度 50%
  加碼：收盤曾跌到首買價 -15% / -30% 後，出現爆量下影線或長紅且收盤仍低於首買價，加碼額度 30% / 20%
        持有每滿半年仍虧損、出現同樣訊號且收盤低於平均成本，再加碼額度 20%
  賣出：收盤較平均成本獲利 >= 12% 且預估殖利率 < 4.75%（算不出殖利率視同 < 4.75%）
        近四季 EPS 合計轉負：隔天賣；被移出成分股後：出現爆量上影線／長黑且不賠錢就賣
  名額：虧損超過 30% 或持有超過 1 年的部位不佔 5 檔名額；被移出成分股的部位也不佔
  不停損、無持有期限、無冷卻期"""


def extend_one_day(G):
    """複製一份資料，在最後加一個虛擬交易日（開盤＝最後收盤），讓引擎對最新收盤做出決策。"""
    dates = G["dates"]
    fake = dates[-1] + pd.Timedelta(days=1)
    dates2 = dates.append(pd.DatetimeIndex([fake]))
    sub2 = {}
    for sid, d in G["sub"].items():
        d2 = {}
        for k, v in d.items():
            if isinstance(v, np.ndarray) and len(v) == len(dates):
                if v.dtype == bool:
                    d2[k] = np.append(v, False)
                elif k == "open":
                    d2[k] = np.append(v, d["close_ff"][-1])
                elif k in ("close", "close_ff", "low", "yield"):
                    d2[k] = np.append(v, v[-1] if k != "close" else d["close_ff"][-1])
                else:
                    d2[k] = np.append(v, v[-1])
            else:
                d2[k] = v
        sub2[sid] = d2
    member2 = {k: pd.concat([v, pd.Series([v.iloc[-1]], index=[fake])]) for k, v in G["member"].items()}
    return dates2, sub2, member2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--start", default="2017-01-03")
    ap.add_argument("--contrib", default="", help="每年追加，例如 2018:500000,2019:500000")
    ap.add_argument("--asof", default=None, help="只用到這天為止的資料")
    a = ap.parse_args()

    po.setup(); G = rs.G
    if a.asof:
        cut = pd.Timestamp(a.asof)
        keep = G["dates"] <= cut
        n_keep = int(keep.sum())
        G["dates"] = G["dates"][keep]
        for sid, d in G["sub"].items():
            for k, v in list(d.items()):
                if isinstance(v, np.ndarray) and len(v) == len(keep):
                    d[k] = v[:n_keep]
            d["last_n"] = min(d["last_n"], n_keep + 1) if d["last_n"] <= n_keep else n_keep + 1
        G["member"] = {k: v.iloc[:n_keep] for k, v in G["member"].items()}
        G["sig"] = {e: {sid: v[:n_keep] for sid, v in m.items()} for e, m in G["sig"].items()}
    po.apply(FINAL); kw = po.to_kw(FINAL)
    dates = G["dates"]
    s_n = dates.get_indexer([pd.Timestamp(a.start)], method="bfill")[0]
    sched = {int(y): float(v) for y, v in (x.split(":") for x in a.contrib.split(",") if x)}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched if (dates.year == y).any()}
    contrib = {first_day[y]: sched[y] / a.capital for y in first_day} or None

    # 1. 跑到最新資料日 → 目前狀態
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=a.capital, contributions=contrib, start_n=s_n, **kw)
    pos0, cash0 = eq.attrs["positions"], eq.attrs["cash"]
    # 2. 加虛擬日再跑 → 明天的動作
    dates2, sub2, member2 = extend_one_day(G)
    tr2, eq2 = ps.run(sub2, member2, dates2, capital=a.capital, contributions=contrib, start_n=s_n, **kw)
    pos1, cash1 = eq2.attrs["positions"], eq2.attrs["cash"]

    names = pd.read_csv(ROOT / "data" / "universe" / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]
    last = dates[-1]; p = len(dates) - 1
    value = eq.iloc[-1] * a.capital
    print(RULE_TEXT)
    print(f"\n資料最後日期：{last.date()}　起始 {dates[s_n].date()}　投入 {a.capital / 1e4:,.0f} 萬"
          + (f"＋追加 {sum(sched.values()) / 1e4:,.0f} 萬" if sched else ""))
    print(f"目前總資產 {value / 1e4:,.0f} 萬（現金 {cash0 * a.capital / 1e4:,.0f} 萬，{100 * cash0 * a.capital / value:.0f}%）")

    print("\n【目前持股】")
    rows = []
    for sid, q in pos0.items():
        d = G["sub"][sid]; px = d["close_ff"][p]; avg = q["cost"] / q["shares"]
        gain = px / avg - 1; y = d["yield"][p]
        status = []
        if gain >= FINAL["target"]:
            status.append("已達 12%，等殖利率 < 4.75%" if (not np.isnan(y) and y >= FINAL["hold_yield"]) else "達賣出條件")
        if q["removed"] or not G["member"][sid].iloc[p]:
            status.append("已移出成分股")
        held = (last - dates[q["start"]]).days
        if held > ps.STALE_DAYS or gain < ps.STALE_LOSS:
            status.append("不佔名額")
        if np.isnan(d["close"][p]):
            status.append("最新一天無報價，引擎暫不處理")
        rows.append(dict(代號=sid, 名稱=names.get(sid, ""), 進場=dates[q["start"]].date(), 持有日=held, 股數=round(q["shares"] * a.capital),
                         平均成本=round(avg, 1), 現價=px, 損益pct=round(100 * gain, 1), 市值萬=round(q["shares"] * px * a.capital / 1e4, 1),
                         預估殖利率=None if np.isnan(y) else round(y, 2), 已加碼=q["adds"], 定期加碼=q.get("time_adds", 0),
                         首買價=round(q["first"], 1), 距首買pct=round(100 * (px / q["first"] - 1), 1), 狀態="；".join(status)))
    hold = pd.DataFrame(rows)
    with pd.option_context("display.width", 300, "display.max_columns", 30, "display.unicode.east_asian_width", True):
        print(hold.to_string(index=False) if len(hold) else "（無）")

    print(f"\n【明天（{last.date()} 之後第一個交易日）開盤要做的事】")
    acts = []
    for sid in pos0:
        if sid not in pos1:
            r = tr2[(tr2["代號"] == sid) & (tr2["出場"] == dates2[-1])].iloc[-1]
            acts.append(f"賣出 {sid} {names.get(sid, '')}：全部 {round(pos0[sid]['shares'] * a.capital)} 股，原因「{r['原因']}」")
        else:
            q0, q1 = pos0[sid], pos1[sid]
            if q1["shares"] > q0["shares"] + 1e-12:
                amt = (q1["cost"] - q0["cost"]) * a.capital
                why = "定期加碼" if q1.get("time_adds", 0) > q0.get("time_adds", 0) else f"第 {q1['adds']} 次加碼"
                acts.append(f"加碼 {sid} {names.get(sid, '')}：約 {amt / 1e4:,.1f} 萬（{why}）")
    for sid in pos1:
        if sid not in pos0:
            acts.append(f"買進 {sid} {names.get(sid, '')}：約 {pos1[sid]['cost'] * a.capital / 1e4:,.1f} 萬"
                        f"（預估殖利率 {G['sub'][sid]['yield'][p]:.2f}%）")
    print("\n".join(acts) if acts else "沒有動作")
    stale = [sid for sid in pos0 if np.isnan(G["sub"][sid]["close"][p])]
    if stale:
        print(f"注意：{', '.join(stale)} 在 {last.date()} 沒有報價資料，引擎會等資料補齊後才判斷賣出／加碼。")
    print(f"執行後現金約 {cash1 * a.capital / 1e4:,.0f} 萬")

    print("\n【觀察名單：殖利率 >= 5% 且在成分股內、未持有（等技術買點）】")
    watch = []
    for sid, d in G["sub"].items():
        y = d["yield"][p]
        if sid in pos0 or np.isnan(y) or y < 5.0 or not G["member"][sid].iloc[p]:
            continue
        watch.append(dict(代號=sid, 名稱=names.get(sid, ""), 收盤=d["close_ff"][p], 預估殖利率=round(y, 2),
                          今日買訊="是" if d["buy"][p] else "", 接近買點="是" if d["near_near1"][p] else ""))
    w = pd.DataFrame(watch).sort_values("預估殖利率", ascending=False) if watch else pd.DataFrame()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(w.to_string(index=False) if len(w) else "（無）")


if __name__ == "__main__":
    main()
