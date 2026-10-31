"""用 EPS 成長率決定每檔「合理殖利率」，買進看殖利率 ≥ 合理殖利率 × k，續抱看殖利率 ≥ 合理殖利率，合理殖利率每天跟著 EPS 變化。

成長率 g：近四季 EPS 合計 ÷ 一年前的近四季 EPS 合計 − 1（兩者都要 > 0 才算；用法定公布期限後才視為已知；EPS 先換成同一股數基準）。
    可選平滑：取最近 4 個季度公布點的 g 平均（smooth=4），避免單季跳動。
合理殖利率 req（%）兩種映射，都夾在 [lo, hi]：
    線性 L：req = 5 − β × g            （β＝5 → 成長 50% 要求 2.5%、衰退 30% 要求 6.5%）
    比例 R：req = 5 ÷ (1 + g)^a         （a＝1 → 成長 100% 要求 2.5%、衰退 50% 要求 10%）
    g 算不出來（EPS 轉負或沒有一年前資料）→ req = 5%（回到正式版門檻）。
買進：預估殖利率 ≥ req × k 且技術買點任一且通過 5 年賺錢；續抱：殖利率 ≥ req（停利 12% 不變）；其他規則同正式版。
每個版本跑 20 情境＋後 3 年＋與 A 的配對＋500 萬。另附事件層級：買點事件按 g 分組的一年內達標率。
用法：python eps_growth_yield_study.py
輸出：results/eps_growth_yield_eval.csv、_money.csv、_events.csv、_today.csv"""
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

BASE, LO, HI = 5.0, 1.5, 8.0
VARIANTS = [  # (名稱, 映射, 參數, k, smooth)
    ("L β=5 k=1.0", "L", 5.0, 1.0, 1), ("L β=5 k=1.25", "L", 5.0, 1.25, 1), ("L β=3 k=1.25", "L", 3.0, 1.25, 1),
    ("R a=1 k=1.0", "R", 1.0, 1.0, 1), ("R a=1 k=1.25", "R", 1.0, 1.25, 1), ("R a=0.5 k=1.25", "R", 0.5, 1.25, 1),
    ("L β=5 k=1.25 平滑4季", "L", 5.0, 1.25, 4), ("R a=1 k=1.25 平滑4季", "R", 1.0, 1.25, 4),
]
FOCUS = ["2330", "2317", "2308", "2454"]
CLUSTER_GAP, HORIZON = 20, 250


def growth_series(G, dates, smooth):
    """每檔每日 g（近四季 EPS 年增率，公布後才知道，smooth 個公布點平均）。"""
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv"); div_all = pd.read_csv(ps.UNI / "dividend_all.csv"); res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv")
    share_all = ps.load_share_events()
    out = {}
    for sid in G["sub"]:
        _, raw_close = ps.load_prices(sid)
        e, _, _ = ps.fundamentals_on_share_basis(sid, raw_close, eps_all, div_all, res_all, share_all)
        if len(e) < 8:
            out[sid] = np.full(len(dates), np.nan); continue
        ttm = e["eps"].rolling(4).sum()
        prev = ttm.shift(4)
        g = pd.Series(np.where((ttm > 0) & (prev > 0), ttm / prev - 1, np.nan), index=e["published"])
        g = g.groupby(level=0).last()
        if smooth > 1:
            g = g.rolling(smooth, min_periods=1).mean()
        out[sid] = g.reindex(dates.union(g.index)).ffill().reindex(dates).values
    return out


def required_yield(g, form, param):
    g = np.asarray(g, dtype=float)
    if form == "L":
        req = BASE - param * g
    else:
        req = BASE / np.power(np.clip(1 + g, 0.05, None), param)
    req = np.clip(req, LO, HI)
    return np.where(np.isnan(g), BASE, req)


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    s_n = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sig = G["sig"][po.ENTRIES[dr.FINAL["entry"]]]
    prof = {sid: ps.profit_years_flag(d.get("annual_eps"), dates, dr.FINAL["profit_years"]) for sid, d in G["sub"].items()}
    orig = {sid: d["buy"].copy() for sid, d in G["sub"].items()}
    key = po._applied["buy"]
    Gs = {1: growth_series(G, dates, 1), 4: growth_series(G, dates, 4)}

    # 今天四檔的 g 與合理殖利率
    p = len(dates) - 1
    today = []
    for sid in FOCUS + ["2382", "2376", "3034"]:
        g = Gs[1][sid][p]; y = G["sub"][sid]["yield"][p]
        today.append(dict(股票=names[sid], 今日殖利率=round(y, 2), EPS年增pct=round(100 * g, 0) if not np.isnan(g) else np.nan,
                          合理殖利率L5=round(float(required_yield([g], "L", 5.0)[0]), 2), 合理殖利率R1=round(float(required_yield([g], "R", 1.0)[0]), 2),
                          倍數L5=round(y / required_yield([g], "L", 5.0)[0], 2), 倍數R1=round(y / required_yield([g], "R", 1.0)[0], 2)))
    today = pd.DataFrame(today); today.to_csv(RESULTS / "eps_growth_yield_today.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(f"今天（{dates[p].date()}）："); print(today.to_string(index=False))

    # 事件層級：正式版買點（A 的 buy）按 g 分組的達標率，看成長率有沒有預測力
    rows = []
    for sid, d in G["sub"].items():
        idx = [i for i in np.flatnonzero(orig[sid] & G["member"][sid].values) if i >= s_n and i + 1 < len(dates) and not np.isnan(d["open"][i + 1])]
        starts, last = [], -10 ** 9
        for i in idx:
            if i - last >= CLUSTER_GAP:
                starts.append(i)
            last = i
        for i in starts:
            path = d["close_ff"][i + 1: i + 1 + HORIZON] / d["open"][i + 1] - 1
            if len(path) < HORIZON:
                continue
            rows.append(dict(代號=sid, 訊號日=dates[i], g=Gs[1][sid][i], 達標=bool((path >= 0.12).any()), 一年報酬=100 * path[-1]))
    ev = pd.DataFrame(rows); ev["g組"] = pd.cut(ev["g"], [-np.inf, -0.3, -0.1, 0.1, 0.3, 0.6, np.inf], labels=["<−30%", "−30～−10%", "−10～10%", "10～30%", "30～60%", ">60%"])
    ev.to_csv(RESULTS / "eps_growth_yield_events.csv", index=False, encoding="utf-8-sig", float_format="%.3f")
    bk = ev.groupby("g組", observed=True).agg(事件=("達標", "size"), 達標率=("達標", "mean"), 一年報酬中位=("一年報酬", "median")); bk["達標率"] *= 100
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print("\n正式版買點按「買進時 EPS 年增率」分組（一年內達 +12%）："); print(bk.round(1).to_string())
        print("g 算不出來（NaN）的事件：", int(ev["g"].isna().sum()))

    # 組合層級
    results, money = {}, {}
    _to_kw = po.to_kw
    po.to_kw = lambda cfg: {**_to_kw(cfg), "hold_yield": "hy_req"}
    def run(name, tag, form=None, param=None, k=1.0, smooth=1):
        for sid, d in G["sub"].items():
            if form is None:
                d["buy"] = orig[sid]; d["hy_req"] = np.full(len(dates), dr.FINAL["hold_yield"])
            else:
                req = required_yield(Gs[smooth][sid], form, param)
                d["buy"] = sig[sid] & (np.nan_to_num(d["yield"], nan=-1) >= req * k) & prof[sid]
                d["hy_req"] = req
        po._applied["buy"] = key
        po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], tag).loc[name]
        if tag != "eg_A":
            for k_, v in paired_from_files("eg_A", tag).items():
                m[k_] = v
        results[name] = m
        kw2 = {**kw, "hold_yield": "hy_req"}
        for sname, s in (("2016-12-28", 1), ("2017-01-03", s_n)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw2)
            money[(name, sname)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                        回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 資金使用率=round(eq.attrs.get("資金使用率%", np.nan), 0))
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}　最差10 {m['最差10最小']:.2f}　σ {m['標準差平均']:.2f}　配對 {m.get('前7年配對', '')} / {m.get('後3年配對', '')}", flush=True)
    try:
        run("A 正式版", "eg_A")
        for i, (name, form, param, k, smooth) in enumerate(VARIANTS):
            run(name, f"eg_{i}", form, param, k, smooth)
    finally:
        po.to_kw = _to_kw
        for sid, d in G["sub"].items():
            d["buy"] = orig[sid]; d.pop("hy_req", None)
        po._applied["buy"] = key
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / "eps_growth_yield_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "eps_growth_yield_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 A）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
