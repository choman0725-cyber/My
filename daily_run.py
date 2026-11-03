"""正式版每日執行程式：殖利率法＋技術買點，續抱殖利率 4.75%、停利 12%，單一帳戶最多 5 檔。

做法：用正式規則從起始日把歷史重跑到最新資料日，得到「目前應有的持股與現金」，再加一個虛擬的下一個交易日
讓引擎做決策，差異就是明天開盤要執行的買進／加碼／賣出（引擎的決策都以前一天收盤為準、隔天開盤成交）。

用法：
  python daily_run.py                                    # 500 萬、2017-01 起、不追加
  python daily_run.py --capital 5000000 --start 2024-01-02 --contrib 2025:1000000,2026:1000000
  python daily_run.py --asof 2026-06-30                  # 假裝今天是 2026-06-30（回看當時的建議）
  python daily_run.py --capital 13780000 --start 2026-10-16 --monthly 100000 --monthly-from 2026-12   # 每月第一個交易日追加 10 萬
  python daily_run.py --holdings my_holdings.csv --cash 11575363   # 從實際持股起算（只算明天要做的事；檔案格式見 load_holdings）
正式版設定在 rules_live.py（本檔的 FINAL 就是它）；研究用 rules_research.py，兩邊分開（2026-11-02）。
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

from rules_live import FINAL, FINAL_3, FINAL_SW18, RULE_TEXT   # 正式版設定只放 rules_live.py；研究程式讀 rules_research.py


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


def monthly_contrib(dates, s_n, amount, capital, start_month, last_is_fake=False):
    """每月第一個交易日開盤前追加 amount（起跑日當天不算）。last_is_fake：最後一天是虛擬的「下一個交易日」，月份用下一個營業日判斷。"""
    per = list(dates.to_period("M"))
    if last_is_fake:
        per[-1] = (dates[-2] + pd.offsets.BDay(1)).to_period("M")
    m0 = pd.Period(start_month, "M") if start_month else per[s_n]
    return {i: amount / capital for i in range(s_n + 1, len(dates)) if per[i] >= m0 and per[i] != per[i - 1]}


def load_holdings(path, cash, G):
    """讀實際持股 CSV，換成引擎部位格式（金額以 capital＝現金＋持股成本 為 1）。
    欄位：代號、進場日、股數、成本（含手續費總金額）；選填：首買價、加碼次數（跌深加碼已做幾次）、定期加碼次數、額度（進場當時總資產÷5）、
    名額（這個部位當成幾檔，預設 1；設 2 時佔 2 個名額，額度欄請填 2 檔份）。
    推算：首買價預設＝成本÷股數；額度預設＝成本 ÷（訊號日首買比例＋已做的跌深加碼比例）；
    最低價、已跌破的加碼階數、是否曾移出成分股、是否曾達停利門檻由進場後的歷史價格推算。"""
    h = pd.read_csv(path, dtype={"代號": str})
    dates, last = G["dates"], len(G["dates"]) - 1
    capital = cash + float(h["成本"].sum())
    pos = {}
    for _, r in h.iterrows():
        sid = r["代號"]
        if sid not in G["sub"]:
            raise SystemExit(f"{sid} 不在股票池（{len(G['sub'])} 檔），引擎無法處理")
        d = G["sub"][sid]
        st = dates.get_indexer([pd.Timestamp(r["進場日"])], method="bfill")[0]
        cost, shares = float(r["成本"]), float(r["股數"])
        first = float(r["首買價"]) if "首買價" in h and pd.notna(r["首買價"]) else cost / shares
        adds = int(r["加碼次數"]) if "加碼次數" in h and pd.notna(r["加碼次數"]) else 0
        fr = d["first_frac"][st - 1] if "first_frac" in d else FINAL["first"]
        budget = float(r["額度"]) if "額度" in h and pd.notna(r["額度"]) else cost / (fr + sum(ps.ADDS[:adds]))
        cmin = np.nanmin(d["close_ff"][st:last + 1])
        pos[sid] = {"start": st, "first": first, "shares": shares / capital, "cost": cost / capital, "budget": budget / capital,
                    "adds": adds, "hit": sum(cmin / first - 1 <= x for x in ps.ADD_STEPS), "low": np.nanmin(d["low"][st:last + 1]),
                    "removed": not G["member"][sid].iloc[st:last + 1].all(), "zone": None,
                    "tp_hit": bool(np.nanmax(d["close_ff"][st:last + 1]) * shares / cost - 1 >= FINAL["target"]),
                    "time_adds": int(r["定期加碼次數"]) if "定期加碼次數" in h and pd.notna(r["定期加碼次數"]) else 0,
                    "slots": int(r["名額"]) if "名額" in h and pd.notna(r["名額"]) else 1}
    return capital, pos, cash / capital


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--start", default="2017-01-03")
    ap.add_argument("--contrib", default="", help="每年追加，例如 2018:500000,2019:500000")
    ap.add_argument("--asof", default=None, help="只用到這天為止的資料")
    ap.add_argument("--holdings", default=None, help="實際持股 CSV：從實際持股起算，只算明天要做的事（格式見 load_holdings）")
    ap.add_argument("--cash", type=float, default=None, help="搭配 --holdings：目前可用現金（元）")
    ap.add_argument("--monthly", type=float, default=0, help="每月追加金額（每月第一個交易日開盤前），例如 100000")
    ap.add_argument("--monthly-from", default=None, help="每月追加從這個月開始，例如 2026-12（預設起跑當月的下個月份起）")
    ap.add_argument("--slots3", action="store_true", help="3 檔版：同時最多 3 檔、每檔額度＝總資產 ÷ 3、首買 65%%（見 FINAL_3）")
    ap.add_argument("--switch18", action="store_true", help="備案：換股 18%%（見 FINAL_SW18）")
    a = ap.parse_args()
    global FINAL
    if a.switch18:
        FINAL = {**FINAL, **FINAL_SW18}
        print("【備案 換股 18%】名額滿時，持股賺 ≥18%（非長期殖利率偏低股）且信心 ≥3 新買點的預期肉多 10 個百分點以上 → 隔天換股")
    if a.slots3:
        FINAL = {**FINAL, **FINAL_3}
        print("【3 檔版】同時最多 3 檔（套牢、被剔除也佔名額）、每檔額度＝總資產 ÷ 3、首買 65%（信心 ≥3 首買 80%）")

    po.setup(live=True); G = rs.G                   # 每日程式用最新資料；回測（po.setup()）截到 rules_research.BACKTEST_END
    if a.asof:
        rs.truncate(a.asof); po._mk.clear()
    po.apply(FINAL); kw = po.to_kw(FINAL)
    dates = G["dates"]
    if a.holdings:
        if a.cash is None:
            raise SystemExit("--holdings 需要搭配 --cash（目前可用現金）")
        a.capital, init_pos, init_cash = load_holdings(a.holdings, a.cash, G)
        a.start = str(dates[-1].date())
    s_n = dates.get_indexer([pd.Timestamp(a.start)], method="bfill")[0]
    sched = {int(y): float(v) for y, v in (x.split(":") for x in a.contrib.split(",") if x)}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched if (dates.year == y).any()}
    contrib = {first_day[y]: sched[y] / a.capital for y in first_day} or None

    # 1. 跑到最新資料日 → 目前狀態
    if a.monthly:
        mc, contrib = monthly_contrib(dates, s_n, a.monthly, a.capital, a.monthly_from), contrib or {}
        contrib = {k: contrib.get(k, 0) + mc.get(k, 0) for k in set(contrib) | set(mc)} or None
    if a.holdings:      # 實際持股＝今天收盤後的狀態，不重跑歷史
        pos0, cash0 = init_pos, init_cash
        value = (cash0 + sum(q["shares"] * G["sub"][s_]["close_ff"][-1] for s_, q in pos0.items())) * a.capital
    else:
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=a.capital, contributions=contrib, start_n=s_n, **kw)
        pos0, cash0 = eq.attrs["positions"], eq.attrs["cash"]
        value = eq.iloc[-1] * a.capital
    # 2. 加虛擬日再跑 → 明天的動作
    dates2, sub2, member2 = extend_one_day(G)
    contrib2 = contrib
    if a.monthly:
        m2 = monthly_contrib(dates2, s_n, a.monthly, a.capital, a.monthly_from, last_is_fake=True)
        if len(dates2) - 1 in m2:
            contrib2 = {**(contrib or {}), len(dates2) - 1: m2[len(dates2) - 1]}
    if a.holdings:      # 只跑虛擬的下一個交易日
        tr2, eq2 = ps.run(sub2, member2, dates2, capital=a.capital, contributions=contrib2, start_n=len(dates2) - 1,
                          init_positions=pos0, init_cash=cash0, **kw)
    else:
        tr2, eq2 = ps.run(sub2, member2, dates2, capital=a.capital, contributions=contrib2, start_n=s_n, **kw)
    pos1, cash1 = eq2.attrs["positions"], eq2.attrs["cash"]

    names = pd.read_csv(ROOT / "data" / "universe" / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"]
    last = dates[-1]; p = len(dates) - 1
    print(RULE_TEXT if not a.slots3 else RULE_TEXT.replace("最多 5 檔", "最多 3 檔").replace("÷ 5", "÷ 3")
          .replace("首買額度 50%", "首買額度 65%").replace("不佔 5 檔名額；被移出成分股的部位也不佔", "也佔名額（同時最多 3 檔，含套牢、被移出成分股的部位）"))
    print(f"\n資料最後日期：{last.date()}　" + (f"實際持股（{a.holdings}）＋現金 {a.cash / 1e4:,.0f} 萬" if a.holdings else
          f"起始 {dates[s_n].date()}　投入 {a.capital / 1e4:,.0f} 萬")
          + (f"＋追加 {sum(sched.values()) / 1e4:,.0f} 萬" if sched else "")
          + (f"＋每月 {a.monthly / 1e4:,.0f} 萬（{a.monthly_from or '起跑次月'} 起，至今已入 {len(monthly_contrib(dates, s_n, a.monthly, a.capital, a.monthly_from)) * a.monthly / 1e4:,.0f} 萬）" if a.monthly else ""))
    print(f"目前總資產 {value / 1e4:,.0f} 萬（現金 {cash0 * a.capital / 1e4:,.0f} 萬，{100 * cash0 * a.capital / value:.0f}%）")
    med, sd, cnt = po.market_stats("all"); thr = po.buy_threshold(FINAL)
    print(f"今日全成分股預估殖利率中位數 {med[p]:.2f}%（{cnt[p]} 檔有預估值，標準差 {sd[p]:.2f}）→ 買進門檻 {thr[p]:.2f}%")

    print("\n【目前持股】")
    rows = []
    for sid, q in pos0.items():
        d = G["sub"][sid]; px = d["close_ff"][p]; avg = q["cost"] / q["shares"]
        gain = px / avg - 1; y = d["yield"][p]
        status = []
        hy_ = d["hy_rel"][p] if "hy_rel" in d else FINAL["hold_yield"]          # 這檔今天的續抱門檻（偏低股＝自己中位，其餘 4.75%）
        if gain >= FINAL["target"]:
            status.append(f"已達 12%，等殖利率 < {hy_:.2f}%" if (not np.isnan(y) and not np.isnan(hy_) and y >= hy_) else "達賣出條件")
        elif gain >= FINAL["target"] - 0.03 and not np.isnan(y) and not np.isnan(hy_) and y < hy_ + 0.3:
            status.append("接近賣點")       # 2026-11-03 使用者：損益離 12% 不到 3 點、殖利率離續抱線不到 0.3
        # 賣出要兩個條件同時成立：停利價＝平均成本×1.12；續抱線價＝殖利率剛好跌到門檻的價位（股利不變時）
        tp_price = round(avg * (1 + FINAL["target"]), 1)
        hy_price = round(px * y / hy_, 1) if (not np.isnan(y) and not np.isnan(hy_) and hy_ > 0) else None
        if q["removed"] or not G["member"][sid].iloc[p]:
            status.append("已移出成分股")
        held = (last - dates[q["start"]]).days
        if held > ps.STALE_DAYS or gain < ps.STALE_LOSS:
            status.append("不佔名額")
        if np.isnan(d["close"][p]):
            status.append("最新一天無報價，引擎暫不處理")
        rows.append(dict(代號=sid, 名稱=names.get(sid, ""), 進場=dates[q["start"]].date(), 持有日=held, 股數=round(q["shares"] * a.capital),
                         平均成本=round(avg, 1), 現價=px, 損益pct=round(100 * gain, 1), 市值萬=round(q["shares"] * px * a.capital / 1e4, 1),
                         預估殖利率=None if np.isnan(y) else round(y, 2), 已加碼=q["adds"], 定期加碼=q.get("time_adds", 0), 補足=q.get("topups", 0),
                         首買價=round(q["first"], 1), 距首買pct=round(100 * (px / q["first"] - 1), 1),
                         停利價=tp_price, 續抱線=None if np.isnan(hy_) else round(hy_, 2), 續抱線價=hy_price, 狀態="；".join(status)))
    hold = pd.DataFrame(rows)
    with pd.option_context("display.width", 300, "display.max_columns", 30, "display.unicode.east_asian_width", True):
        print(hold.to_string(index=False) if len(hold) else "（無）")
    if pos0:
        import scenario_text as sc
        print("\n【持股劇本：每檔接下來什麼情況會賣、會加碼、何時不佔名額（規則換算成價位，隔天開盤執行）】")
        for sid, q in pos0.items():
            print(sc.holding_script(sid, names.get(sid, ""), q, G["sub"][sid], p, dates, a.capital, FINAL,
                                    time_add_days=FINAL.get("time_add_days", 182), time_add_amount=FINAL.get("time_add_amount", 0.20)))

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
                if q1.get("topups", 0) > q0.get("topups", 0):
                    why = "買點再現補足（賺錢部位補到當天額度）"
                else:
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

    print(f"\n【觀察名單：殖利率達門檻（一般股 {thr[p]:.2f}%；長期殖利率偏低股＝自己 3 年中位×1.25）且在成分股內、未持有（等技術買點；「近5年有虧損」的不會買）】")
    watch = []
    for sid, d in G["sub"].items():
        y = d["yield"][p]
        growth = bool(d.get("growth_flag", np.zeros(len(dates), bool))[p])
        gate = d["own_median"][p] * FINAL["growth_rel"][0] if growth and FINAL.get("growth_rel") else thr[p]
        if sid in pos0 or np.isnan(y) or np.isnan(gate) or y < gate or not G["member"][sid].iloc[p]:
            continue
        ok = ps.profit_years_flag(d.get("annual_eps"), dates, FINAL["profit_years"])[p] if FINAL.get("profit_years") else True
        watch.append(dict(代號=sid, 名稱=names.get(sid, ""), 收盤=d["close_ff"][p], 預估殖利率=round(y, 2),
                          殖利率偏低股="是" if growth else "", 自己中位=round(d["own_median"][p], 2) if "own_median" in d and not np.isnan(d["own_median"][p]) else None,
                          倍數=round(d["own_ratio"][p], 2) if "own_ratio" in d and not np.isnan(d["own_ratio"][p]) else None,
                          信心=int(d["conf_score"][p]) if "conf_score" in d else None,
                          首買=f"{d['first_frac'][p]:.0%}" if "first_frac" in d else f"{FINAL['first']:.0%}",
                          近5年有虧損="" if ok else "是", 今日買訊="是" if d["buy"][p] else "", 接近買點="是" if d["near_near1"][p] else ""))
    w = pd.DataFrame(watch).sort_values("預估殖利率", ascending=False) if watch else pd.DataFrame()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(w.to_string(index=False) if len(w) else "（無）")
    if len(w):
        import scenario_text as sc
        print("\n【觀察名單劇本：每檔還差什麼才會出現買訊（殖利率門檻價＋六種技術買點的具體條件）】")
        for r in w.itertuples():
            sid = r.代號; d = G["sub"][sid]
            df_, _ = ps.load_prices(sid); df_ = df_[df_.index <= last]
            growth = bool(d.get("growth_flag", np.zeros(len(dates), bool))[p])
            gate = d["own_median"][p] * FINAL["growth_rel"][0] if growth and FINAL.get("growth_rel") else thr[p]
            print(sc.watch_script(sid, names.get(sid, ""), df_, d["yield"][p], gate, growth, d["own_median"][p] if "own_median" in d else np.nan, thr[p]))


if __name__ == "__main__":
    main()
