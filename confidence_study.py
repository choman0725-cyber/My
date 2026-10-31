"""訊號信心分級：信心高 → 首買 0.8（備案 C）、信心中 → 首買 0.5（正式版 A）、信心低 → 略過、讓名額給順位下一檔。

信心值只用「訊號當天以前」就知道的資訊（沒有前視），六個因子相加（範圍 −1～7）：
  F1 便宜程度：預估殖利率 − 買進門檻  ≥ 1.0 → 2；≥ 0.5 → 1；否則 0
  F2 訊號共振：三種基本技術買點（多指標共振、價量引線、布林KD）近 3 日內同時成立 ≥ 2 種 → 1
  F3 基本面：近兩季單季 EPS 沒有連續年減（引擎 bad 旗標為 False）→ 1
  F4 大盤：加權指數收盤在 200 日均線之上 → 1
  F5 個股過去紀錄（擴張視窗）：這檔過去的買點事件（訊號日 ≥ 250 個交易日前、結果已知）一年內達 +12% 的比例，
       事件 ≥ 3 個且 ≥ 75% → 1；事件 ≥ 3 個且 < 50% → −1；否則 0
  F6 回檔深度：收盤距 250 日高點 −15%～−40% 之間 → 1（有跌但不是崩盤）
分級：信心 ≥ hi → 首買 0.8；lo < 信心 < hi → 首買 0.5；信心 ≤ lo → 不買（引擎自然選殖利率次高的下一檔）。
hi、lo 掃一個小網格，每個版本跑 20 情境＋後 3 年＋與 A 的配對，並做 500 萬試算；另附事件層級的診斷：
各信心分數的買點事件數、一年內達標率、一年報酬中位、MAE，分前 7 年／後 3 年，看信心值到底有沒有預測力。

用法：python confidence_study.py            # 第一版因子
      python confidence_study.py v2         # 第二版因子（factors_v2，使用者 2026-10-31 定義），輸出檔加 _v2
      python confidence_study.py v3         # 第三版：第二版去掉 F2、F3，F5 反向（急漲急跌 → +1），保留 F1、F4、F6，總分 0～7，輸出檔加 _v3
      python confidence_study.py v3b        # 第三版因子、只分級不略過（≥hi 首買 0.8，其餘 0.5）
輸出：results/confidence_events.csv（每個買點事件的因子與結果）、confidence_buckets.csv、confidence_eval.csv、confidence_money.csv
"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

CLUSTER_GAP, HORIZON = 20, 250
GRID = [(hi, lo) for hi in (4, 5, 6) for lo in (0, 1, 2)]
HI_FRAC, MID_FRAC = 0.8, 0.5
BASE_TYPES = ["共振（目前版本）", "價量引線", "布林KD"]


def rolling_max_bool(a, w):
    s = pd.Series(a.astype(int))
    return s.rolling(w, min_periods=1).max().astype(bool).values


def factors(G, dates, thr):
    """回傳 {sid: (score 陣列, 因子 DataFrame)}。"""
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    ma200 = tx.rolling(200).mean()
    bull = (tx > ma200).reindex(dates).fillna(False).values
    out = {}
    for sid, d in G["sub"].items():
        y = d["yield"]
        f1 = np.where(np.nan_to_num(y - thr, nan=-9) >= 1.0, 2, np.where(np.nan_to_num(y - thr, nan=-9) >= 0.5, 1, 0))
        cnt = sum(rolling_max_bool(G["sig"][k][sid], 3).astype(int) for k in BASE_TYPES)
        f2 = (cnt >= 2).astype(int)
        f3 = (~d["bad"]).astype(int)
        f4 = bull.astype(int)
        c = pd.Series(d["close_ff"], index=dates)
        hi250 = c.rolling(250, min_periods=60).max()
        dd = (c / hi250 - 1).values
        f6 = ((dd <= -0.15) & (dd >= -0.40)).astype(int)
        # F5：擴張視窗的個股買點紀錄
        buy = d["buy"]
        idx = [i for i in np.flatnonzero(buy) if i + 1 < len(buy) and not np.isnan(d["open"][i + 1])]
        starts, last = [], -10 ** 9
        for i in idx:
            if i - last >= CLUSTER_GAP:
                starts.append(i)
            last = i
        starts = np.array(starts, dtype=int)
        hits = np.array([bool((d["close_ff"][i + 1: i + 1 + HORIZON] / d["open"][i + 1] - 1 >= 0.12).any()) for i in starts], dtype=int)
        f5 = np.zeros(len(dates), int)
        if len(starts):
            cum_h = np.cumsum(hits)
            for p in range(len(dates)):
                k = np.searchsorted(starts, p - HORIZON, side="right")      # 訊號日 ≤ p−250 的事件數
                if k >= 3:
                    rate = cum_h[k - 1] / k
                    f5[p] = 1 if rate >= 0.75 else (-1 if rate < 0.5 else 0)
        score = f1 + f2 + f3 + f4 + f5 + f6
        out[sid] = (score, pd.DataFrame({"F1便宜": f1, "F2共振": f2, "F3基本面": f3, "F4大盤": f4, "F5紀錄": f5, "F6回檔": f6}, index=dates),
                    starts, hits)
    return out


def factors_v2(G, dates, thr):
    """第二版（使用者 2026-10-31 定義）：
    F1 今日殖利率 ÷ 該股過去 3 年（750 日，至少 250 日有值）殖利率中位數：≥1.5 → 2；≥1.25 → 1；否則 0
    F2、F3 同第一版
    F4 大盤：收盤在 200 日線上 → 1；前 5 個交易日內有放量（量 > 20 日均量 1.5 倍）→ +1；放量日帶長下影線（wick_buy）→ +1
    F5 該股過去 20 個交易日有急漲或急跌（單日 |漲跌| ≥ 7%，或 20 日累計 |漲跌| ≥ 15%）→ −1
    F6 收盤距 60 日高點 −15%～−40% → 1
    另回傳 急漲20／急跌20 旗標供診斷。"""
    from indicators import pv_triggers, wick_conditions, sma
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")
    tx = tx[tx["volume"] > 0]
    above = (tx["close"] > tx["close"].rolling(200).mean())
    vol_up = wick_conditions(tx)["vol_up"]
    wick = pv_triggers(tx)["wick_buy"]
    vol5 = vol_up.astype(int).rolling(5, min_periods=1).max().astype(bool)
    wick5 = wick.astype(int).rolling(5, min_periods=1).max().astype(bool)
    f4_all = (above.astype(int) + vol5.astype(int) + wick5.astype(int)).reindex(dates).fillna(0).astype(int).values
    out = {}
    for sid, d in G["sub"].items():
        y = pd.Series(d["yield"], index=dates)
        med = y.rolling(750, min_periods=250).median().shift(1)
        ratio = (y / med).values
        f1 = np.where(np.nan_to_num(ratio, nan=0) >= 1.5, 2, np.where(np.nan_to_num(ratio, nan=0) >= 1.25, 1, 0))
        cnt = sum(rolling_max_bool(G["sig"][k][sid], 3).astype(int) for k in BASE_TYPES)
        f2 = (cnt >= 2).astype(int)
        f3 = (~d["bad"]).astype(int)
        f4 = f4_all
        c = pd.Series(d["close_ff"], index=dates)
        r1 = c.pct_change()
        r20 = c / c.shift(20) - 1
        up = ((r1 >= 0.07).astype(int).rolling(20, min_periods=1).max().astype(bool) | (r20 >= 0.15)).fillna(False).values
        dn = ((r1 <= -0.07).astype(int).rolling(20, min_periods=1).max().astype(bool) | (r20 <= -0.15)).fillna(False).values
        f5 = -(up | dn).astype(int)
        hi60 = c.rolling(60, min_periods=20).max()
        dd = (c / hi60 - 1).values
        f6 = ((dd <= -0.15) & (dd >= -0.40)).astype(int)
        buy = d["buy"]
        idx = [i for i in np.flatnonzero(buy) if i + 1 < len(buy) and not np.isnan(d["open"][i + 1])]
        starts, last = [], -10 ** 9
        for i in idx:
            if i - last >= CLUSTER_GAP:
                starts.append(i)
            last = i
        starts = np.array(starts, dtype=int)
        hits = np.array([bool((d["close_ff"][i + 1: i + 1 + HORIZON] / d["open"][i + 1] - 1 >= 0.12).any()) for i in starts], dtype=int)
        score = f1 + f2 + f3 + f4 + f5 + f6
        fdf = pd.DataFrame({"F1相對殖利率": f1, "F2共振": f2, "F3基本面": f3, "F4大盤": f4, "F5急漲跌": f5, "F6回檔60": f6,
                            "急漲20": up.astype(int), "急跌20": dn.astype(int), "殖利率倍數": np.round(ratio, 2)}, index=dates)
        out[sid] = (score, fdf, starts, hits)
    return out


def money(sub, member, dates, kw, start):
    s_n = dates.get_indexer([start], method="bfill")[0]
    tr, eq = ps.run(sub, member, dates, capital=CAPITAL, start_n=s_n, **kw)
    closed = tr[tr["出場"].notna()]
    return {"期末萬": round(eq.iloc[-1] * CAPITAL / 1e4), "IRR%": round(irr([CAPITAL], [dates[s_n]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
            "回撤%": round(100 * (eq / eq.cummax() - 1).min(), 1), "筆數": len(tr),
            "勝率%": round(100 * (closed["報酬%"] > 0).mean(), 0) if len(closed) else np.nan,
            "資金使用率%": round(eq.attrs.get("資金使用率%", np.nan), 0)}


def main(version="v1"):
    po.setup()
    G = rs.G
    dates = G["dates"]
    po.apply(dr.FINAL)
    kw = po.to_kw(dr.FINAL)
    thr = po.buy_threshold(dr.FINAL)
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    F = factors_v2(G, dates, thr) if version in ("v2", "v3", "v3b") else factors(G, dates, thr)
    if version in ("v3", "v3b"):
        # 第三版（使用者 2026-10-31 更正）：移除 F2、F3；F5 反向（近 20 日有急漲急跌 → +1）；保留 F1、F4、F6。總分 0～7
        for sid, (score, fdf, starts, hits) in list(F.items()):
            fdf = fdf.rename(columns={"F2共振": "x2共振", "F3基本面": "x3基本面", "F5急漲跌": "F5急漲跌+"})
            fdf["F5急漲跌+"] = -fdf["F5急漲跌+"]
            F[sid] = (fdf[["F1相對殖利率", "F4大盤", "F5急漲跌+", "F6回檔60"]].sum(axis=1).values, fdf, starts, hits)
    grid = [(4, 0), (4, 1), (5, 0), (5, 1), (6, 0)] if version == "v3" else GRID
    if version == "v3b":          # 第三版因子、只分級不略過：信心 ≥ hi 首買 0.8，其餘 0.5
        grid = [(2, -1), (3, -1), (4, -1), (5, -1)]
    sfx = "" if version == "v1" else f"_{version}"
    FCOLS = [c for c in F[next(iter(F))][1].columns if c.startswith("F")]

    # 事件層級診斷：每個買點事件（成分股內、2017 起）的信心分數與結果
    rows = []
    for sid, (score, fdf, starts, hits) in F.items():
        d = G["sub"][sid]
        for i, h in zip(starts, hits):
            if dates[i] < pd.Timestamp("2017-01-01") or not G["member"][sid].iloc[i]:
                continue
            path = d["close_ff"][i + 1: i + 1 + HORIZON] / d["open"][i + 1] - 1
            rows.append({"代號": sid, "名稱": names.get(sid, ""), "訊號日": dates[i], "信心": int(score[i]), **fdf.iloc[i].to_dict(),
                         "一年內達標": bool(h) if len(path) >= HORIZON else np.nan,
                         "一年報酬%": 100 * path[-1] if len(path) >= HORIZON else np.nan, "MAE%": 100 * path.min() if len(path) else np.nan,
                         "段": "前7年" if dates[i] <= rs.IS_END else "後3年"})
    ev = pd.DataFrame(rows)
    ev.to_csv(RESULTS / f"confidence_events{sfx}.csv", index=False, encoding="utf-8-sig", float_format="%.2f")
    full = ev[ev["一年內達標"].notna()]
    bk = full.groupby(["段", "信心"]).agg(事件=("代號", "size"), 達標率=("一年內達標", "mean"), 一年報酬中位=("一年報酬%", "median"), MAE中位=("MAE%", "median"))
    bk["達標率"] = 100 * bk["達標率"]
    bk.round(1).to_csv(RESULTS / f"confidence_buckets{sfx}.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print("事件層級：信心分數 vs 一年內達 +12% 比例（只算結果已知的事件）")
        print(bk.round(1).to_string())
        corr = full[FCOLS + ["信心"]].apply(lambda c: full["一年內達標"].astype(float).corr(c.astype(float)))
        print("\n各因子與「一年內達標」的相關係數：", corr.round(3).to_dict())
        for c in FCOLS:
            print(f"  {c} 各值達標率%：", (100 * full.groupby(c)["一年內達標"].mean()).round(0).to_dict(), "事件數", full.groupby(c).size().to_dict())
        if "急漲20" in full.columns:
            g = full.groupby(["急漲20", "急跌20"]).agg(事件=("代號", "size"), 達標率=("一年內達標", "mean"), 一年報酬中位=("一年報酬%", "median"), MAE中位=("MAE%", "median"))
            g["達標率"] = 100 * g["達標率"]; print("\n急漲／急跌拆開看（0/0＝都沒有）："); print(g.round(1).to_string())

    # 組合層級：A、C、信心分級
    orig = {sid: G["sub"][sid]["buy"].copy() for sid in G["sub"]}
    key = po._applied["buy"]
    results, cash = {}, {}
    def run_variant(name, tag, frac_of, mask_of):
        for sid, d in G["sub"].items():
            sc = F[sid][0]
            d["first_frac"] = frac_of(sc)
            d["buy"] = orig[sid] & mask_of(sc)
        po._applied["buy"] = key
        po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], tag).loc[name]
        if not tag.endswith("_A"):
            for k_, v in paired_from_files(f"conf{sfx}_A", tag).items():
                m[k_] = v
        results[name] = m
        cash[name] = {f"{pd.Timestamp(s).date()} 起": money(G["sub"], G["member"], dates, kw, s) for s in (dates[1], pd.Timestamp("2017-01-03"))}
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    run_variant("A 全部首買0.5", f"conf{sfx}_A", lambda sc: np.full(len(sc), MID_FRAC), lambda sc: np.ones(len(sc), bool))
    run_variant("C 全部首買0.8", f"conf{sfx}_C", lambda sc: np.full(len(sc), HI_FRAC), lambda sc: np.ones(len(sc), bool))
    for hi, lo in grid:
        run_variant(f"信心 ≥{hi} 走C、≤{lo} 略過" if lo >= 0 else f"信心 ≥{hi} 走C、其餘走A（不略過）", f"conf{sfx}_{hi}_{lo}",
                    lambda sc, hi=hi: np.where(sc >= hi, HI_FRAC, MID_FRAC), lambda sc, lo=lo: sc > lo)
    for sid, d in G["sub"].items():
        d["buy"] = orig[sid]; d.pop("first_frac", None)
    po._applied["buy"] = key
    out = pd.DataFrame(results).T
    show = ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"]
    show = [c for c in show if c in out.columns]
    mon = pd.DataFrame({(n, s): v for n, dd in cash.items() for s, v in dd.items()}).T
    out[show].round(2).to_csv(RESULTS / f"confidence_eval{sfx}.csv", encoding="utf-8-sig")
    mon.to_csv(RESULTS / f"confidence_money{sfx}.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對 A）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())

    # 今日觀察名單的信心值
    p = len(dates) - 1
    today = []
    for sid, d in G["sub"].items():
        y = d["yield"][p]
        if np.isnan(y) or y < thr[p] or not G["member"][sid].iloc[p]:
            continue
        sc, fdf = F[sid][0], F[sid][1]
        today.append({"代號": sid, "名稱": names.get(sid, ""), "殖利率": round(y, 2), "信心": int(sc[p]), **fdf.iloc[p].to_dict(),
                      "今日買訊": bool(orig[sid][p])})
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(f"\n今日（{dates[p].date()}）殖利率達門檻的池內股票與信心值：")
        print(pd.DataFrame(today).sort_values("信心", ascending=False).to_string(index=False) if today else "（無）")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "v1")
