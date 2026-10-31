"""個股層級篩選：「20 情境 IRR 標準差 ≤ 2.0」與「每年至少 3 次買點」會刪掉多少檔？刪掉之後池子變好還是變差？

每檔電子股各算：
  單檔 20 情境：只有這一檔、照正式版全部規則，前 7 年 5 個起始日 × 4 種追加 → IRR 中位數、標準差（帳戶層級，含閒置現金）。
  日報酬標準差：2017 年起每日報酬的標準差（%），另一種常見的「標準差」解讀。
  買點：正式版定義（殖利率門檻＋連續 5 年賺錢＋技術買點任一）的訊號日數，按年統計 2017～2025（2026 不足一年）。
    「每年 ≥3」有三種鬆緊：每一年都 ≥3；至少 7 年 ≥3；平均每年 ≥3。
再把各種條件留下的股票當成新池子，跑 20 情境＋後 3 年與正式版並排（含配對統計）。
輸出：results/stock_screen_stocks.csv、results/stock_screen_eval.csv
用法：python stock_screen_study.py
"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

STD_MAX = 2.0
MIN_BUYS = 3
YEARS = list(range(2017, 2026))


def scenario_irr(sub, member, dates, kw, start, cname):
    s_n = dates.get_indexer([pd.Timestamp(start)], method="bfill")[0]
    e_n = dates.get_indexer([rs.IS_END], method="ffill")[0]
    sched = {y: a for y, a in rs.CONTRIBS[cname].items() if dates[s_n].year < y}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in sched}
    contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
    tr, eq = ps.run(sub, member, dates, capital=CAPITAL, contributions=contrib, start_n=s_n, end_n=e_n, **kw)
    flows = [CAPITAL] + list(sched.values())
    fdates = [dates[s_n]] + [dates[first_day[y]] for y in sched]
    return irr(flows, fdates, eq.iloc[-1] * CAPITAL, dates[e_n])


def main():
    po.setup()
    G = rs.G
    dates = G["dates"]
    po.apply(dr.FINAL)
    kw = po.to_kw(dr.FINAL)
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]

    # 正式版 2017-01-03 每檔實際貢獻，用來看篩選會不會刪到贏家
    tr0, _ = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s17, **kw)
    tr0["pnl"] = np.where(tr0["出場"].notna(), tr0["回收"] - tr0["投入"], tr0["市值"] - tr0["投入"]) * CAPITAL / 1e4
    actual = tr0.groupby("代號")["pnl"].sum()

    rows = []
    for sid, d in G["sub"].items():
        sub, mem = {sid: d}, {sid: G["member"][sid]}
        irrs = [scenario_irr(sub, mem, dates, kw, st, c) for st in rs.STARTS for c in rs.CONTRIBS]
        buy_year = pd.Series(d["buy"] & G["member"][sid].values, index=dates).groupby(dates.year).sum()
        by = buy_year.reindex(YEARS).fillna(0).astype(int)
        r = pd.Series(d["close"], index=dates).pct_change()
        r = r[dates >= "2017-01-01"].dropna()
        rows.append({"代號": sid, "名稱": names.get(sid, ""), "20情境IRR中位": np.median(irrs), "20情境IRR標準差": np.std(irrs, ddof=1),
                     "日報酬標準差%": 100 * r.std(), "買點總數": int(by.sum()), "每年平均買點": by.sum() / len(YEARS),
                     "買點≥3的年數": int((by >= MIN_BUYS).sum()), "每年都≥3": bool((by >= MIN_BUYS).all()),
                     "各年買點": " ".join(str(x) for x in by.values), "正式版實際損益萬": actual.get(sid, 0.0)})
        print(f"{sid} {names.get(sid, ''):　<6} IRR標準差 {rows[-1]['20情境IRR標準差']:4.2f}　日σ {rows[-1]['日報酬標準差%']:4.2f}　"
              f"各年買點 {rows[-1]['各年買點']}", flush=True)
    st = pd.DataFrame(rows)
    st["過:IRR標準差≤2"] = st["20情境IRR標準差"] <= STD_MAX
    st["過:日σ≤2"] = st["日報酬標準差%"] <= STD_MAX
    st["過:每年都≥3"] = st["每年都≥3"]
    st["過:7年以上≥3"] = st["買點≥3的年數"] >= 7
    st["過:平均≥3"] = st["每年平均買點"] >= MIN_BUYS
    st.round(3).to_csv(RESULTS / "stock_screen_stocks.csv", index=False, encoding="utf-8-sig")

    conds = {"正式版（75 檔）": st["代號"].notna(),
             "IRR標準差≤2": st["過:IRR標準差≤2"], "日σ≤2": st["過:日σ≤2"],
             "每年都≥3買點": st["過:每年都≥3"], "7年以上≥3買點": st["過:7年以上≥3"], "平均每年≥3買點": st["過:平均≥3"],
             "IRR標準差≤2 且 每年都≥3": st["過:IRR標準差≤2"] & st["過:每年都≥3"],
             "IRR標準差≤2 且 7年以上≥3": st["過:IRR標準差≤2"] & st["過:7年以上≥3"],
             "IRR標準差≤2 且 平均≥3": st["過:IRR標準差≤2"] & st["過:平均≥3"]}
    print("\n各條件留下幾檔、刪掉的檔在正式版 2017-01-03 路徑上的實際損益：")
    summ = []
    for k, m in conds.items():
        cut = st[~m]
        summ.append({"條件": k, "留下": int(m.sum()), "刪掉": int((~m).sum()), "刪掉者實際損益萬": cut["正式版實際損益萬"].sum(),
                     "刪掉的前幾名": "、".join(f"{r.名稱}{r.正式版實際損益萬:+.0f}" for r in cut.sort_values("正式版實際損益萬", ascending=False).head(5).itertuples())})
    summ = pd.DataFrame(summ)
    with pd.option_context("display.width", 300, "display.max_colwidth", 80, "display.unicode.east_asian_width", True):
        print(summ.round(0).to_string(index=False))

    # 留下的股票當新池子，跑 20 情境＋後 3 年
    base_sub, base_mem = dict(G["sub"]), dict(G["member"])
    key = po._applied["buy"]
    results = {}
    po.CONFIGS["正式版"] = dr.FINAL
    for k, m in conds.items():
        keep = set(st.loc[m, "代號"])
        if len(keep) == 0 or (len(keep) == len(st) and k != "正式版（75 檔）"):
            continue
        G["sub"].clear(); G["sub"].update({s: v for s, v in base_sub.items() if s in keep})
        G["member"].clear(); G["member"].update({s: v for s, v in base_mem.items() if s in keep})
        po._applied["buy"] = key
        po.CONFIGS[k] = dr.FINAL
        results[k] = k
    names_eval = list(results)
    G["sub"].clear(); G["sub"].update(base_sub); G["member"].clear(); G["member"].update(base_mem)
    # evaluate 需要在同一個 G 上跑所有版本；改成每個條件各跑一次（基準放第一個，配對相對正式版）
    out = {}
    for k in names_eval:
        keep = set(st.loc[conds[k], "代號"])
        G["sub"].clear(); G["sub"].update({s: v for s, v in base_sub.items() if s in keep})
        G["member"].clear(); G["member"].update({s: v for s, v in base_mem.items() if s in keep})
        po._applied["buy"] = key
        m = po.evaluate([k], f"screen_{len(out)}").loc[k]
        out[k] = m
        print(f"  {k}（{len(keep)} 檔）完成", flush=True)
    G["sub"].clear(); G["sub"].update(base_sub); G["member"].clear(); G["member"].update(base_mem)
    po._applied["buy"] = key
    ev = pd.DataFrame(out).T
    # 配對改成相對正式版：用各自的 is/oos runs 檔重算
    base_is = pd.read_csv(RESULTS / "param_opt_screen_0_is_runs.csv"); base_oos = pd.read_csv(RESULTS / "param_opt_screen_0_oos_runs.csv")
    for i, k in enumerate(names_eval):
        cur_is = pd.read_csv(RESULTS / f"param_opt_screen_{i}_is_runs.csv"); cur_oos = pd.read_csv(RESULTS / f"param_opt_screen_{i}_oos_runs.csv")
        for df_b, df_c, keys, pre in ((base_is, cur_is, ["起始", "追加"], "前7年"), (base_oos, cur_oos, ["驗證", "起始", "追加"], "後3年")):
            dd = (df_c.set_index(keys)["IRR"] - df_b.set_index(keys)["IRR"]).dropna().values
            ev.loc[k, f"{pre}配對"] = f"{int((dd > 0.05).sum())}/{int((np.abs(dd) <= 0.05).sum())}/{int((dd < -0.05).sum())}"
            ev.loc[k, f"{pre}配對中位差"] = float(np.median(dd)); ev.loc[k, f"{pre}配對最差"] = float(dd.min())
    ev["檔數"] = [int(conds[k].sum()) for k in names_eval]
    show = ["檔數"] + po.SHOW + ["超過2年比例"] + po.SHOW_PAIR
    ev[show].round(2).to_csv(RESULTS / "stock_screen_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.unicode.east_asian_width", True):
        print("\n留下的股票當池子，20 情境＋後 3 年（IRR％，配對相對正式版）")
        print(ev[show].round(1).to_string())


if __name__ == "__main__":
    main()
