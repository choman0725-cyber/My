"""成長股（台積電、鴻海、台達電）vs 聯發科：EPS 成長、配息、殖利率的關係，找出每檔自己的「中值」，
看用「殖利率相對自己的中值」能不能在目前策略下進出這類殖利率到不了 5% 的股票。

三層：
  一、逐年關係表：EPS、EPS 年增、現金股利、配息率、隔年均價本益比、實際殖利率、模型預估殖利率中位。
  二、個股自己的中值：每日「預估殖利率 ÷ 該股過去 3 年（750 日）殖利率中位數」＝相對殖利率倍數（只用當天以前）。
      買點＝倍數 ≥ k（k 1.25／1.5）且技術買點任一且通過 5 年賺錢；事件統計（一年內達 +12%、報酬、MAE）＋
      單檔模擬（正式版規則，續抱門檻改成「自己的 3 年中位數」：殖利率仍高於自己的中值就續抱）。
  三、接進正式版：池內「過去 3 年殖利率中位數 < 4%」的股票（成長股）改用相對規則（買 倍數 ≥ k、續抱 自己的中值），
      其他股票照正式版；跑 20 情境＋後 3 年＋配對＋500 萬，看會不會傷到主策略。
用法：python growth_yield_study.py
輸出：results/growth_yield_yearly.csv、growth_yield_events.csv、growth_yield_trades.csv、growth_yield_eval.csv、growth_yield_money.csv
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
from stock_fit import paired_from_files

FOCUS = ["2330", "2317", "2308", "2454"]
KS = (1.25, 1.5)
WINDOW, MIN_OBS = 750, 250
GROWTH_MED = 4.0          # 過去 3 年殖利率中位數低於此值的股票視為「成長股」，改用相對規則
CLUSTER_GAP, HORIZON = 20, 250
START = pd.Timestamp("2017-01-03")


def yearly_table(sids, names, G, dates):
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv"); div_all = pd.read_csv(ps.UNI / "dividend_all.csv"); res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv")
    rows = []
    for sid in sids:
        e = ps.eps_table(eps_all, sid); annual = e.groupby("fy")["eps"].agg(["sum", "size"]); annual = annual[annual["size"] == 4]["sum"]
        cash = ps.dividend_events(div_all, sid, res_all).groupby("fy")["cash"].sum()
        px = pd.read_csv(ps.UNI / "prices" / f"{sid}.csv", parse_dates=["date"]).set_index("date")["close"]
        y = pd.Series(G["sub"][sid]["yield"], index=dates)
        for fy in range(2016, 2026):
            if fy not in annual.index:
                continue
            p1 = px[px.index.year == fy + 1]; yy = y[y.index.year == fy + 1]
            prev = annual.get(fy - 1, np.nan)
            rows.append(dict(股票=names[sid], 年度=fy, EPS=round(annual[fy], 2), EPS年增pct=round(100 * (annual[fy] / prev - 1), 0) if prev and prev > 0 else np.nan,
                             現金股利=round(cash.get(fy, np.nan), 2), 配息率pct=round(100 * cash.get(fy, np.nan) / annual[fy], 0) if annual[fy] > 0 else np.nan,
                             隔年均價=round(p1.mean(), 0) if len(p1) else np.nan, 本益比=round(p1.mean() / annual[fy], 1) if len(p1) and annual[fy] > 0 else np.nan,
                             實際殖利率pct=round(100 * cash.get(fy, np.nan) / p1.mean(), 2) if len(p1) else np.nan,
                             模型預估殖利率中位pct=round(yy.median(), 2) if len(yy) else np.nan))
    return pd.DataFrame(rows)


def relative_ratio(G, dates):
    """每檔：相對殖利率倍數陣列、3 年中位數陣列。"""
    out = {}
    for sid, d in G["sub"].items():
        y = pd.Series(d["yield"], index=dates)
        med = y.rolling(WINDOW, min_periods=MIN_OBS).median().shift(1)
        out[sid] = ((y / med).values, med.values)
    return out


def events_for(d, buy, dates, s_n):
    idx = [i for i in np.flatnonzero(buy) if i >= s_n and i + 1 < len(buy) and not np.isnan(d["open"][i + 1])]
    starts, last = [], -10 ** 9
    for i in idx:
        if i - last >= CLUSTER_GAP:
            starts.append(i)
        last = i
    rows = []
    for i in starts:
        entry = d["open"][i + 1]; path = d["close_ff"][i + 1: i + 1 + HORIZON] / entry - 1
        hit = np.flatnonzero(path >= 0.12)
        rows.append(dict(訊號日=dates[i], 進場價=round(entry, 1), 一年內達標=bool(len(hit)) if len(path) >= HORIZON else np.nan,
                         達標天數=hit[0] if len(hit) else np.nan, 一年報酬pct=round(100 * path[-1], 1) if len(path) >= HORIZON else np.nan,
                         MAE=round(100 * path.min(), 1) if len(path) else np.nan))
    return pd.DataFrame(rows, columns=["訊號日", "進場價", "一年內達標", "達標天數", "一年報酬pct", "MAE"])


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    s_n = dates.get_indexer([START], method="bfill")[0]
    thr = po.buy_threshold(dr.FINAL)
    sig = G["sig"][po.ENTRIES[dr.FINAL["entry"]]]
    prof = {sid: ps.profit_years_flag(d.get("annual_eps"), dates, dr.FINAL["profit_years"]) for sid, d in G["sub"].items()}

    # 一、逐年關係
    yt = yearly_table(FOCUS, names, G, dates)
    yt.to_csv(RESULTS / "growth_yield_yearly.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        for sid in FOCUS:
            print(f"\n== {names[sid]} 逐年"); print(yt[yt["股票"] == names[sid]].drop(columns="股票").to_string(index=False))

    # 二、個股自己的中值
    R = relative_ratio(G, dates)
    p = len(dates) - 1
    print("\n== 今天的狀態")
    for sid in FOCUS:
        d = G["sub"][sid]; ratio, med = R[sid]
        y = d["yield"][p]
        print(f"  {names[sid]}: 殖利率 {y:.2f}%，自己 3 年中位 {med[p]:.2f}%，倍數 {ratio[p]:.2f}，2017 起倍數 ≥1.25 的天數 {int(np.nansum(ratio[s_n:] >= 1.25))}、≥1.5 {int(np.nansum(ratio[s_n:] >= 1.5))}（共 {p - s_n + 1} 天）")
    ev_rows, tr_rows = [], []
    for sid in FOCUS:
        d = G["sub"][sid]; ratio, med = R[sid]
        for k in KS:
            buy = sig[sid] & (np.nan_to_num(ratio, nan=0) >= k) & prof[sid]
            ev = events_for(d, buy, dates, s_n); ev["股票"] = names[sid]; ev["k"] = k; ev_rows.append(ev)
            d2 = dict(d); d2["buy"] = buy; d2["hy_rel"] = med
            kw2 = {**kw, "hold_yield": "hy_rel"}
            tr, eq = ps.run({sid: d2}, {sid: pd.Series(True, index=dates)}, dates, capital=CAPITAL, start_n=s_n, **kw2)
            tr["股票"] = names[sid]; tr["k"] = k; tr_rows.append(tr)
            closed = tr[tr["出場"].notna()]
            full = ev[ev["一年內達標"].notna()]
            print(f"  {names[sid]} k={k}: 買點叢集 {len(ev)}，一年內達標 {100 * full['一年內達標'].mean():.0f}%（{len(full)} 件），MAE 中位 {ev['MAE'].median():.1f}%；"
                  f"單檔模擬 {len(tr)} 筆、勝率 {100 * (closed['報酬%'] > 0).mean() if len(closed) else float('nan'):.0f}%、平均報酬 {closed['報酬%'].mean() if len(closed) else float('nan'):.1f}%、"
                  f"持有中位 {int(((tr['出場'].fillna(dates[-1]) - tr['進場']).dt.days).median()) if len(tr) else 0} 天", flush=True)
    E = pd.concat(ev_rows, ignore_index=True); E.to_csv(RESULTS / "growth_yield_events.csv", index=False, encoding="utf-8-sig")
    T = pd.concat(tr_rows, ignore_index=True); T.to_csv(RESULTS / "growth_yield_trades.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.unicode.east_asian_width", True):
        print("\n== 單檔模擬逐筆（k=1.25）"); print(T[T["k"] == 1.25][["股票", "進場", "出場", "原因", "報酬%", "持有日"]].round(1).to_string(index=False))

    # 三、接進正式版：成長股（3 年殖利率中位 < 4%）改用相對規則
    orig = {sid: d["buy"].copy() for sid, d in G["sub"].items()}
    key = po._applied["buy"]
    results, money = {}, {}
    def run_variant(name, tag, k=None):
        for sid, d in G["sub"].items():
            ratio, med = R[sid]
            if k is None:
                d["buy"] = orig[sid]; d["hy_rel"] = np.full(len(dates), dr.FINAL["hold_yield"])
            else:
                growth = np.nan_to_num(med, nan=99) < GROWTH_MED
                rel_buy = sig[sid] & (np.nan_to_num(ratio, nan=0) >= k) & prof[sid]
                d["buy"] = np.where(growth, rel_buy, orig[sid])
                d["hy_rel"] = np.where(growth, med, dr.FINAL["hold_yield"])
        po._applied["buy"] = key
        po.CONFIGS[name] = dr.FINAL
        rs.RULES[name] = {**kw, "hold_yield": "hy_rel"}
        m = po.evaluate([name], tag).loc[name]
        rs.RULES[name] = {**kw, "hold_yield": "hy_rel"}       # evaluate 會重設 RULES，確保後續 money 用同一套
        if tag != "gy_A":
            for k_, v in paired_from_files("gy_A", tag).items():
                m[k_] = v
        results[name] = m
        kw2 = {**kw, "hold_yield": "hy_rel"}
        for sname, s in (("2016-12-28", 1), ("2017-01-03", s_n)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw2)
            g = tr[tr["代號"].isin([sid for sid in G["sub"] if np.nan_to_num(R[sid][1], nan=99)[s_n:].mean() < GROWTH_MED])]
            money[(name, sname)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                        回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 成長股筆數=len(g))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    # evaluate() 內部用 to_kw(CONFIGS[n]) 重設 RULES → 這裡改成直接覆寫 rs.RULES 後呼叫，需繞過：
    _to_kw = po.to_kw
    po.to_kw = lambda cfg: {**_to_kw(cfg), "hold_yield": "hy_rel"}
    try:
        run_variant("A 正式版", "gy_A")
        for k in KS:
            run_variant(f"正式版＋成長股相對規則 k={k}", f"gy_{str(k).replace('.', '')}", k)
    finally:
        po.to_kw = _to_kw
        for sid, d in G["sub"].items():
            d["buy"] = orig[sid]; d.pop("hy_rel", None)
        po._applied["buy"] = key
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / "growth_yield_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "growth_yield_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.unicode.east_asian_width", True):
        print("\n== 接進正式版：20 情境＋後 3 年（配對相對 A）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())
    # 成長股名單（2017 起 3 年中位平均 < 4%）
    gl = sorted([f"{sid}{names[sid]}" for sid in G["sub"] if np.nan_to_num(R[sid][1], nan=99)[s_n:].mean() < GROWTH_MED])
    print("\n池內被視為成長股（3 年殖利率中位平均 < 4%）：", "、".join(gl))


if __name__ == "__main__":
    main()
