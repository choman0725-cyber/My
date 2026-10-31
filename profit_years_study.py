"""買進濾網「公司連續 N 年有賺錢」會不會排擠現有股票？

定義：在買進日，最近 N 個「已公布完整會計年度」（Q4 法定期限 3/31 後才算已知）的年度 EPS（四季合計）全部 > 0。
資料從 2015 年開始，2017～2019 年只看得到 2～4 個完整年度，所以分兩種：
  寬鬆：已知年度（最多 N 年）全部 > 0，至少 1 個年度（2017-01 只知道 2015 年）—— 可以從 2017 年起跑、與正式版並排比較。
  嚴格：必須真的有 N 個已知年度且全部 > 0 —— 2020-03-31 前沒有任何股票符合，只用來看 2020 年後擋掉哪些交易。
輸出：
  results/profit_years_<N>_stocks.csv   每檔哪些年度 EPS ≤ 0、寬鬆／嚴格版各有多少天可買
  results/profit_years_<N>_trades.csv   正式版 2017-01-03 起 60 筆交易，各在進場日是否會被擋
  results/profit_years_<N>_eval.csv     20 情境＋後 3 年：正式版 vs 加濾網
  results/profit_years_<N>_money.csv    500 萬試算
用法：python profit_years_study.py [N]（預設 5）
"""
import sys

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
START = pd.Timestamp("2017-01-03")


def profit_flags(sid, eps_all, dates, n):
    """回傳 (寬鬆旗標, 嚴格旗標, 虧損年度清單)。"""
    e = ps.eps_table(eps_all, sid)
    annual = e.groupby("fy")["eps"].agg(["sum", "size"])
    annual = annual[annual["size"] == 4]["sum"]
    loose = np.zeros(len(dates), bool)
    strict = np.zeros(len(dates), bool)
    known_from = {fy: pd.Timestamp(fy + 1, 3, 31) for fy in annual.index}
    for i, t in enumerate(dates):
        known = [fy for fy in annual.index if known_from[fy] <= t]
        last = sorted(known)[-n:]
        if len(last) >= 1 and all(annual[fy] > 0 for fy in last):
            loose[i] = True
            if len(last) >= n:
                strict[i] = True
    return loose, strict, [int(fy) for fy in annual.index if annual[fy] <= 0]


def money(sub, member, dates, kw, start=START):
    s_n = dates.get_indexer([start], method="bfill")[0]
    tr, eq = ps.run(sub, member, dates, capital=CAPITAL, start_n=s_n, **kw)
    eq = eq * CAPITAL
    return {"期末萬": eq.iloc[-1] / 1e4, "IRR%": irr([CAPITAL], [dates[s_n]], eq.iloc[-1], dates[-1]),
            "回撤%": 100 * (eq / eq.cummax() - 1).min(), "筆數": len(tr)}, tr


def main():
    po.setup()
    G = rs.G
    dates = G["dates"]
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv")
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    po.apply(dr.FINAL)
    kw = po.to_kw(dr.FINAL)

    flags, rows = {}, []
    for sid, d in G["sub"].items():
        loose, strict, bad = profit_flags(sid, eps_all, dates, N)
        flags[sid] = (loose, strict)
        buy = d["buy"]
        rows.append({"代號": sid, "名稱": names.get(sid, ""), "虧損年度": " ".join(map(str, bad)),
                     "正式版買點日數": int(buy.sum()), "寬鬆版剩餘買點": int((buy & loose).sum()),
                     "嚴格版剩餘買點": int((buy & strict).sum()),
                     "嚴格版2020後剩餘買點": int((buy & strict)[dates >= "2020-03-31"].sum()),
                     "正式版2020後買點": int(buy[dates >= "2020-03-31"].sum())})
    st = pd.DataFrame(rows)
    st.to_csv(RESULTS / f"profit_years_{N}_stocks.csv", index=False, encoding="utf-8-sig")

    # 正式版 60 筆交易逐筆檢查
    m0, tr0 = money(G["sub"], G["member"], dates, kw)
    tr0 = tr0.copy()
    tr0["名稱"] = tr0["代號"].map(names)
    tr0["損益萬"] = np.where(tr0["出場"].notna(), tr0["回收"] - tr0["投入"], tr0["市值"] - tr0["投入"]) * CAPITAL / 1e4
    sig_n = dates.get_indexer(tr0["進場"]) - 1          # 訊號日＝進場前一個交易日
    tr0["寬鬆版可買"] = [flags[s][0][n] for s, n in zip(tr0["代號"], sig_n)]
    tr0["嚴格版可買"] = [flags[s][1][n] for s, n in zip(tr0["代號"], sig_n)]
    tr0["已知完整年度數"] = [sum(1 for fy in ps.eps_table(eps_all, s).groupby("fy")["eps"].size().pipe(lambda x: x[x == 4]).index
                             if pd.Timestamp(fy + 1, 3, 31) <= dates[n]) for s, n in zip(tr0["代號"], sig_n)]
    tr0[["代號", "名稱", "進場", "出場", "原因", "報酬%", "持有日", "損益萬", "已知完整年度數", "寬鬆版可買", "嚴格版可買"]] \
        .to_csv(RESULTS / f"profit_years_{N}_trades.csv", index=False, encoding="utf-8-sig", float_format="%.2f")

    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.unicode.east_asian_width", True):
        print(f"濾網：最近 {N} 個已知完整年度 EPS 全部 > 0\n")
        print("有虧損年度的股票：")
        print(st[st["虧損年度"] != ""][["代號", "名稱", "虧損年度", "正式版買點日數", "寬鬆版剩餘買點", "嚴格版剩餘買點"]].to_string(index=False))
        blocked = tr0[~tr0["寬鬆版可買"]]
        print(f"\n正式版 2017-01-03 起 {len(tr0)} 筆交易，寬鬆版會擋掉 {len(blocked)} 筆（損益合計 {blocked['損益萬'].sum():.0f} 萬）：")
        print(blocked[["代號", "名稱", "進場", "出場", "報酬%", "持有日", "損益萬", "已知完整年度數"]].round(1).to_string(index=False))
        b2 = tr0[(tr0["進場"] >= "2020-03-31") & ~tr0["嚴格版可買"]]
        print(f"\n2020-03-31 後的 {int((tr0['進場'] >= '2020-03-31').sum())} 筆交易，嚴格版會擋掉 {len(b2)} 筆（損益合計 {b2['損益萬'].sum():.0f} 萬）：")
        print(b2[["代號", "名稱", "進場", "出場", "報酬%", "持有日", "損益萬"]].round(1).to_string(index=False))
        held = tr0[tr0["出場"].isna()]
        print("\n目前持股在進場日是否符合：")
        print(held[["代號", "名稱", "進場", "已知完整年度數", "寬鬆版可買", "嚴格版可買"]].to_string(index=False))

    # 20 情境＋後 3 年：正式版 vs 寬鬆版濾網（同一行程內先跑基準，再改 buy 陣列）
    po.CONFIGS["正式版"] = dr.FINAL
    base = po.evaluate(["正式版"], "profit_years_base").loc["正式版"]
    key = po._applied["buy"]
    orig = {sid: d["buy"].copy() for sid, d in G["sub"].items()}
    for sid, d in G["sub"].items():
        d["buy"] = orig[sid] & flags[sid][0]
    po._applied["buy"] = key                      # 讓工作行程沿用改過的 buy，不重算
    name = f"＋連續{N}年賺錢（寬鬆）"
    po.CONFIGS[name] = dr.FINAL
    var = po.evaluate([name], "profit_years_loose").loc[name]
    m1, _ = money(G["sub"], G["member"], dates, kw)
    m1b, _ = money(G["sub"], G["member"], dates, kw, start=dates[1])
    for sid, d in G["sub"].items():
        d["buy"] = orig[sid]
    m0b, _ = money(G["sub"], G["member"], dates, kw, start=dates[1])

    show = ["前7年", "前7年最差10", "前7年標準差", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "最長持有", "超過2年比例"]
    ev = pd.DataFrame({"正式版": base, name: var}).T[show]
    mo = pd.DataFrame({"正式版 2017-01-03": m0, f"{name} 2017-01-03": m1, "正式版 2016-12-28": m0b, f"{name} 2016-12-28": m1b}).T
    ev.round(2).to_csv(RESULTS / f"profit_years_{N}_eval.csv", encoding="utf-8-sig")
    mo.round(2).to_csv(RESULTS / f"profit_years_{N}_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（IRR％）")
        print(ev.round(1).to_string())
        print("\n500 萬不追加")
        print(mo.round(1).to_string())


if __name__ == "__main__":
    main()
