"""正式版的鏡像放空：殖利率低 ＋ 利空盤 ＋ 同一套技術訊號反向 ＋ 獲利 5% 回補。

條件（收盤判斷、隔天開盤成交）：
  1. 預估殖利率 < 門檻（試 2.5% / 2% / 1.5%；算法同正式版：近四季 EPS × 近 3 年平均配息率 ÷ 原始收盤；
     年配且已公告未除息用公告值。算不出殖利率的不放空。另跑「不看殖利率」對照）
  2. 利空環境：加權指數 空頭排列（MA5<MA20<MA60）／ 指數<年線 ／ 指數<年線且空頭排列（另跑「不看盤勢」對照）
  3. 技術放空點任一（正式版四個買點各自鏡像）：
     ①超買共振：近 3 日 KD>80／RSI>70／WR>−20／CCI>100 至少 3 個 ＋ KD 死叉 ＋ 收盤在年線之下
     ②爆量長上影線 或 爆量長黑（跌幅 >2%）
     ③近 3 日觸布林上軌 ＋ K>70 死叉
     ④高檔區（近 5 日觸上軌且 K>70）＋ 爆量長上影線／爆量長黑／價創高量縮
  4. 回補：收盤較放空價跌 ≥5% → 隔天開盤回補。不停損；只有斷頭（漲 46%）、除息前強制回補、下市。
     變體：大盤轉多（利空環境消失）隔天開盤回補。
  5. 台股限制同 short_study.py（前日跌 3.5% 不得平盤下空、除息前停券、成本與借券費）。
兩層：
  A. 每檔獨立放空（名目＝權益）→ 148 檔所有交易的每筆期望值、勝率、每檔每年貢獻。
  B. 5 檔組合：每檔名目＝進場時總資產 ÷ 5，最多 5 檔，同日多檔依殖利率低到高挑；算期末資產、IRR、最大回撤，
     與正式版做多（500 萬、IRR 23.9%、回撤 −31%）同期比較。
  C. 停利掃描：<2%／<1.5% × 空頭排列，停利 5／7.5／10／12.5／15%。
用法：python short_yield_study.py            # 全部
      python short_yield_study.py targets    # 只跑停利掃描
      python short_yield_study.py hold       # 只跑持有上限掃描（10～45 個交易日）
輸出：results/short_yield_*.csv、results/short_yield_study.log
"""
import time

import numpy as np
import pandas as pd

from backtest import BUY_COST, RESULTS, ROOT, SELL_COST
from indicators import bollinger, cross_down, kd, overbought_resonance, pv_triggers, setup_zones, sma
from portfolio_study import UNI, dividend_events, eps_table, forward_dividend, load_prices, membership
from short_study import (BORROW_RATE, MARGIN_CALL, SHORT_FEE, UNIVERSE_START, UPTICK_DROP, ex_dividend_blocks,
                         fmt, regime_defs, run_short)

TARGET = 0.05
YIELDS = {"不看殖利率": None, "殖利率<2.5%": 2.5, "殖利率<2%": 2.0, "殖利率<1.5%": 1.5}
REGIMES = {"不看盤勢": None, "指數<年線": "R1 指數<年線", "空頭排列": "R4 空頭排列MA5<20<60", "指數<年線且空頭排列": "R6 指數<年線且空頭排列"}
SLOTS, CAPITAL = 5, 5_000_000


def short_entries(df):
    """正式版四個技術買點的鏡像。回傳 {名稱: 放空訊號}，含「任一」。"""
    t = pv_triggers(df)
    pv_sell = t["wick_sell"] | t["pv_sell"]
    _, _, upper = bollinger(df)
    k, d = kd(df)
    touched = (df["high"] >= upper).astype(int).rolling(3).max().astype(bool)
    _, high_zone, *_ = setup_zones(df)
    ob, _ = overbought_resonance(df, need=3, window=3)
    e = {
        "超買共振＋年線下": ob & (df["close"] < sma(df["close"], 240)),
        "爆量上影線或長黑": pv_sell,
        "觸上軌＋KD>70死叉": touched & cross_down(k, d) & (k > 70),
        "高檔區＋出貨訊號": high_zone & pv_sell,
    }
    e["任一"] = pd.concat(e.values(), axis=1).fillna(False).any(axis=1)
    return e


def prepare():
    """每檔：還原價、原始收盤、預估殖利率、技術放空訊號、成分股期間、除息停券。"""
    cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
    taiex = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")
    dates = taiex.index[taiex.index >= pd.Timestamp("2015-01-01")]
    member = membership(cons, dates)
    eps_all = pd.read_csv(UNI / "eps_all.csv")
    div_all = pd.read_csv(UNI / "dividend_all.csv")
    res_all = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    res_all["date"] = pd.to_datetime(res_all["date"])
    regimes, tai = regime_defs(dates)
    names = cons.drop_duplicates("stock_id").set_index("stock_id")["name"]
    data = {}
    for sid in sorted(set(cons["stock_id"])):
        loaded = load_prices(sid)
        if loaded is None or len(loaded[0]) < 300 or sid not in member:
            continue
        df, raw_close = loaded
        df = df[df.index >= pd.Timestamp("2015-01-01")]
        raw_close = raw_close.reindex(df.index)
        if df.index[-1] < UNIVERSE_START + pd.Timedelta(days=200):
            continue
        dps = forward_dividend(df.index, eps_table(eps_all, sid), dividend_events(div_all, sid, res_all))
        ex_dates = res_all.loc[(res_all["stock_id"] == sid) & res_all["stock_or_cache_dividend"].astype(str).str.contains("息|權"), "date"]
        force, block = ex_dividend_blocks(df.index, ex_dates.tolist())
        data[sid] = {
            "df": df, "name": names.get(sid, ""),
            "yield": 100 * dps / raw_close,
            "sig": short_entries(df)["任一"].fillna(False),
            "member": member[sid].reindex(df.index).ffill().fillna(False).astype(bool),
            "force": force, "block": block,
            "start": max(UNIVERSE_START, df.index[0] + pd.Timedelta(days=200)),
        }
    return data, dates, regimes, tai


def entry_signal(d, y_th, rname, regimes):
    sig = d["sig"] & d["member"]
    if y_th is not None:
        sig = sig & (d["yield"] < y_th)
    if rname is not None:
        sig = sig & regimes[rname].reindex(d["df"].index).ffill().fillna(False).astype(bool)
    return sig


def cover_signal(d, rname, regimes, flip):
    idx = d["df"].index
    if flip and rname is not None:
        return ~regimes[rname].reindex(idx).ffill().fillna(False).astype(bool)
    return pd.Series(False, index=idx)


# ---------- A. 每檔獨立 ----------

def per_trade(data, regimes, log):
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    trades = []
    for sid, d in data.items():
        for yname, y_th in YIELDS.items():
            for rname_s, rname in REGIMES.items():
                sig = entry_signal(d, y_th, rname, regimes)
                if not sig.any():
                    continue
                for flip in (False, True):
                    if flip and rname is None:
                        continue
                    t, _ = run_short(d["df"], sig, cover_signal(d, rname, regimes, flip), d["start"], d["df"].index[-1],
                                     tp=TARGET, force=d["force"], block=d["block"])
                    if len(t):
                        trades.append(t.assign(stock_id=sid, 殖利率=yname, 盤勢=rname_s, 轉多就補="是" if flip else "否"))
    T = pd.concat(trades, ignore_index=True)
    T.to_csv(RESULTS / "short_yield_trades.csv", index=False, encoding="utf-8-sig")

    def agg(g):
        r = g["return"]
        wins, losses = r[r > 0], r[r <= 0]
        return pd.Series({"筆數": len(r), "檔數": g["stock_id"].nunique(), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                          "平均獲利%": 100 * wins.mean() if len(wins) else 0, "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                          "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                          "平均天數": g["days"].mean(), "每檔每年貢獻%": 100 * r.sum() / g["stock_id"].nunique() / years,
                          "斷頭筆數": int((g["reason"] == "斷頭").sum())})

    S = T.groupby(["殖利率", "盤勢", "轉多就補"], sort=False).apply(agg, include_groups=False).round(2)
    S.to_csv(RESULTS / "short_yield_summary.csv", encoding="utf-8-sig")
    log(f"\n【A. 每檔獨立放空（獲利 5% 回補、不停損），{len(data)} 檔，{UNIVERSE_START:%Y-%m-%d} 起 {years:.1f} 年】\n" + fmt(S))
    log("\n每筆期望值%（列＝殖利率門檻，欄＝盤勢｜轉多就補）：\n"
        + fmt(S["每筆期望值%"].unstack(["盤勢", "轉多就補"]).round(2)))
    log("\n筆數：\n" + fmt(S["筆數"].unstack(["盤勢", "轉多就補"]).astype("Int64")))
    sub = T[(T["盤勢"] == "指數<年線且空頭排列") & (T["轉多就補"] == "是")]
    log("\n回補原因（指數<年線且空頭排列、轉多就補，各殖利率門檻）：\n"
        + fmt(sub.groupby(["殖利率", "reason"]).agg(筆數=("return", "size"), 每筆pct=("return", lambda x: round(100 * x.mean(), 2))).unstack("reason")))
    return T


# ---------- B. 5 檔組合 ----------

def run_portfolio(data, dates, regimes, y_th, rname, flip, capital=CAPITAL, slots=SLOTS, target=TARGET, max_days=None):
    """名目＝進場時總資產 ÷ slots；最多 slots 檔；同日多檔依殖利率低到高。回傳 (交易, 每日權益)。"""
    span = dates[dates >= UNIVERSE_START]
    arr = {}
    for sid, d in data.items():
        df = d["df"].reindex(span)
        sig = entry_signal(d, y_th, rname, regimes).reindex(span).fillna(False).to_numpy(dtype=bool)
        cov = cover_signal(d, rname, regimes, flip).reindex(span).fillna(False).to_numpy(dtype=bool)
        last = d["df"].index[-1]
        arr[sid] = {"open": df["open"].to_numpy(), "close": df["close"].to_numpy(), "close_ff": df["close"].ffill().to_numpy(),
                    "sig": sig, "cover": cov, "force": d["force"].reindex(span).fillna(False).to_numpy(dtype=bool),
                    "block": d["block"].reindex(span).fillna(False).to_numpy(dtype=bool),
                    "yield": d["yield"].reindex(span).to_numpy(), "chg": df["close"].pct_change().to_numpy(),
                    "delist_n": span.get_indexer([last])[0] if last < span[-1] - pd.Timedelta(days=10) else len(span) + 5,
                    "start_n": span.searchsorted(d["start"])}
    eq, pos, trades, equity = 1.0, {}, [], []
    for n in range(len(span)):
        if n > 0:
            # 1. 出場（前一天收盤決定）
            for sid in list(pos):
                p = pos[sid]
                if p["exit"] is None:
                    continue
                a = arr[sid]
                px = a["open"][n] if not np.isnan(a["open"][n]) else a["close_ff"][n - 1]
                days = (span[n] - span[p["n0"]]).days
                pnl = p["proceeds"] - p["N"] * px * (1 + BUY_COST) - p["N"] * p["p0"] * BORROW_RATE * days / 365
                eq += pnl
                trades.append((sid, data[sid]["name"], span[p["n0"]], p["p0"], span[n], px, pnl * capital, pnl / p["notional"], days, p["exit"]))
                del pos[sid]
            # 2. 進場（前一天收盤訊號；依殖利率低到高）
            cands = []
            for sid, a in arr.items():
                if sid in pos or n < a["start_n"] or n >= a["delist_n"] or not a["sig"][n - 1] or a["block"][n]:
                    continue
                if np.isnan(a["open"][n]) or (a["chg"][n - 1] <= UPTICK_DROP and a["open"][n] < a["close"][n - 1]):
                    continue
                cands.append((a["yield"][n - 1] if not np.isnan(a["yield"][n - 1]) else 99, sid))
            for _, sid in sorted(cands)[: max(0, slots - len(pos))]:
                a = arr[sid]
                notional = eq / slots
                N = notional / a["open"][n]
                pos[sid] = {"n0": n, "p0": a["open"][n], "N": N, "notional": notional,
                            "proceeds": N * a["open"][n] * (1 - SELL_COST - SHORT_FEE), "exit": None}
        # 3. 收盤：評價與決策
        mark = eq
        for sid, p in pos.items():
            a = arr[sid]
            c = a["close_ff"][n]
            days = (span[n] - span[p["n0"]]).days
            mark += p["proceeds"] - p["N"] * c * (1 + BUY_COST) - p["N"] * p["p0"] * BORROW_RATE * days / 365
            ret = c / p["p0"] - 1
            reason = None
            if a["cover"][n]:
                reason = "轉多回補"
            if max_days is not None and n - p["n0"] + 1 >= max_days:
                reason = f"滿{max_days}日"
            if ret <= -target:
                reason = f"獲利{100 * target:g}%"
            if ret >= MARGIN_CALL:
                reason = "斷頭"
            if a["force"][n]:
                reason = "強制回補"
            if n + 1 >= a["delist_n"]:
                reason = "下市"
            p["exit"] = reason
        equity.append(max(mark, 1e-9))
    # 期末
    n = len(span) - 1
    for sid, p in pos.items():
        a = arr[sid]
        c = a["close_ff"][n]
        days = (span[n] - span[p["n0"]]).days
        pnl = p["proceeds"] - p["N"] * c * (1 + BUY_COST) - p["N"] * p["p0"] * BORROW_RATE * days / 365
        eq += pnl
        trades.append((sid, data[sid]["name"], span[p["n0"]], p["p0"], span[n], c, pnl * capital, pnl / p["notional"], days, "期末"))
    equity[-1] = max(eq, 1e-9)
    T = pd.DataFrame(trades, columns=["代號", "名稱", "進場", "放空價", "出場", "回補價", "損益元", "報酬率", "天數", "原因"])
    return T, pd.Series(equity, index=span)


def portfolio(data, dates, regimes, log):
    rows, all_t = {}, []
    for yname, y_th in YIELDS.items():
        for rname_s, rname in REGIMES.items():
            for flip in (False, True):
                if flip and rname is None:
                    continue
                T, eq = run_portfolio(data, dates, regimes, y_th, rname, flip)
                years = (eq.index[-1] - eq.index[0]).days / 365.25
                peak = eq.cummax()
                held = pd.Series(0, index=eq.index)
                for a, b in zip(T["進場"], T["出場"]):
                    held[(held.index >= a) & (held.index < b)] += 1
                rows[(yname, rname_s, "是" if flip else "否")] = {
                    "筆數": len(T), "勝率%": 100 * (T["報酬率"] > 0).mean() if len(T) else np.nan,
                    "每筆%": 100 * T["報酬率"].mean() if len(T) else np.nan,
                    "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / years) - 1),
                    "最大回撤%": 100 * (eq / peak - 1).min(), "平均持有檔數": held.mean(), "有部位時間%": 100 * (held > 0).mean(),
                    "斷頭": int((T["原因"] == "斷頭").sum()), "最差一筆萬": T["損益元"].min() / 1e4 if len(T) else 0,
                }
                all_t.append(T.assign(殖利率=yname, 盤勢=rname_s, 轉多就補="是" if flip else "否"))
    P = pd.DataFrame(rows).T
    P.index.names = ["殖利率", "盤勢", "轉多就補"]
    P.round(1).to_csv(RESULTS / "short_yield_portfolio.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_portfolio_trades.csv", index=False, encoding="utf-8-sig")
    log(f"\n【B. 5 檔組合（500 萬、每檔名目 1/5、同日依殖利率低到高挑、獲利 5% 回補、不停損）"
        f"｜對照：正式版做多同期 500 萬 → 4,104 萬、IRR 23.9%、回撤 −31%】\n" + fmt(P.astype(float).round(1)))
    return P


# ---------- C. 停利掃描 ----------

TARGETS = (0.05, 0.075, 0.10, 0.125, 0.15)


def target_scan(data, dates, regimes, log, combos=(("殖利率<2%", "空頭排列"), ("殖利率<1.5%", "空頭排列"))):
    """固定殖利率門檻 × 空頭排列、不轉多就補，掃停利 5～15%。"""
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    rows, prow, all_t = {}, {}, []
    for yname, rname_s in combos:
        y_th, rname = YIELDS[yname], REGIMES[rname_s]
        for tp in TARGETS:
            tr = []
            for sid, d in data.items():
                sig = entry_signal(d, y_th, rname, regimes)
                if not sig.any():
                    continue
                t, _ = run_short(d["df"], sig, cover_signal(d, rname, regimes, False), d["start"], d["df"].index[-1],
                                 tp=tp, force=d["force"], block=d["block"])
                if len(t):
                    tr.append(t.assign(stock_id=sid))
            T = pd.concat(tr, ignore_index=True)
            r = T["return"]
            wins, losses = r[r > 0], r[r <= 0]
            T["年"] = T["entry_date"].dt.year
            rows[(yname, f"{100 * tp:g}%")] = {
                "筆數": len(r), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(), "每筆中位%": 100 * r.median(),
                "平均獲利%": 100 * wins.mean(), "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                "平均天數": T["days"].mean(), "停利筆數": int((T["reason"] == "停利").sum()),
                "強制回補筆數": int((T["reason"] == "強制回補").sum()), "斷頭筆數": int((T["reason"] == "斷頭").sum()),
                "最差一筆%": 100 * r.min(), "每檔每年貢獻%": 100 * r.sum() / T["stock_id"].nunique() / years,
                "前段每筆%": 100 * T[T["年"] <= 2023]["return"].mean(), "後段每筆%": 100 * T[T["年"] >= 2024]["return"].mean(),
            }
            all_t.append(T.assign(殖利率=yname, 盤勢=rname_s, 停利=f"{100 * tp:g}%"))
            P, eq = run_portfolio(data, dates, regimes, y_th, rname, False, target=tp)
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            prow[(yname, f"{100 * tp:g}%")] = {
                "筆數": len(P), "勝率%": 100 * (P["報酬率"] > 0).mean(), "每筆%": 100 * P["報酬率"].mean(),
                "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / yrs) - 1),
                "最大回撤%": 100 * (eq / eq.cummax() - 1).min(), "斷頭": int((P["原因"] == "斷頭").sum()),
                "最差一筆萬": P["損益元"].min() / 1e4, "最好一筆萬": P["損益元"].max() / 1e4,
                "總損益萬": P["損益元"].sum() / 1e4,
            }
    S = pd.DataFrame(rows).T.astype(float).round(2)
    S.index.names = ["殖利率", "停利"]
    S.to_csv(RESULTS / "short_yield_targets.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_targets_trades.csv", index=False, encoding="utf-8-sig")
    PP = pd.DataFrame(prow).T.astype(float).round(1)
    PP.index.names = ["殖利率", "停利"]
    PP.to_csv(RESULTS / "short_yield_targets_portfolio.csv", encoding="utf-8-sig")
    log("\n【C. 停利掃描：空頭排列、不轉多就補、不停損｜每檔獨立】\n" + fmt(S))
    log("\n【C. 停利掃描｜5 檔組合（500 萬）】\n" + fmt(PP))
    return S, PP


# ---------- D. 持有上限掃描 ----------

HOLDS = (None, 10, 15, 20, 30, 45)


def hold_scan(data, dates, regimes, log,
              combos=(("殖利率<2%", "空頭排列", 0.05), ("殖利率<2%", "空頭排列", 0.10), ("殖利率<1.5%", "空頭排列", 0.05))):
    """固定殖利率 × 空頭排列 × 停利，掃持有上限（交易日；到期隔天開盤回補）。"""
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    rows, prow, all_t = {}, {}, []
    for yname, rname_s, tp in combos:
        y_th, rname = YIELDS[yname], REGIMES[rname_s]
        for md in HOLDS:
            hname = "無上限" if md is None else f"{md}日"
            tr = []
            for sid, d in data.items():
                sig = entry_signal(d, y_th, rname, regimes)
                if not sig.any():
                    continue
                t, _ = run_short(d["df"], sig, cover_signal(d, rname, regimes, False), d["start"], d["df"].index[-1],
                                 tp=tp, max_days=md, force=d["force"], block=d["block"])
                if len(t):
                    tr.append(t.assign(stock_id=sid))
            T = pd.concat(tr, ignore_index=True)
            r = T["return"]
            wins, losses = r[r > 0], r[r <= 0]
            T["年"] = T["entry_date"].dt.year
            key = (yname, f"停利{100 * tp:g}%", hname)
            rows[key] = {
                "筆數": len(r), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                "平均獲利%": 100 * wins.mean(), "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                "平均天數": T["days"].mean(), "停利筆數": int((T["reason"] == "停利").sum()), "到期筆數": int((T["reason"] == "到期").sum()),
                "到期每筆%": 100 * T[T["reason"] == "到期"]["return"].mean() if (T["reason"] == "到期").any() else np.nan,
                "強制回補筆數": int((T["reason"] == "強制回補").sum()), "斷頭筆數": int((T["reason"] == "斷頭").sum()),
                "最差一筆%": 100 * r.min(), "每檔每年貢獻%": 100 * r.sum() / T["stock_id"].nunique() / years,
                "前段每筆%": 100 * T[T["年"] <= 2023]["return"].mean(), "後段每筆%": 100 * T[T["年"] >= 2024]["return"].mean(),
            }
            all_t.append(T.assign(殖利率=yname, 停利=f"{100 * tp:g}%", 持有上限=hname))
            P, eq = run_portfolio(data, dates, regimes, y_th, rname, False, target=tp, max_days=md)
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            prow[key] = {
                "筆數": len(P), "勝率%": 100 * (P["報酬率"] > 0).mean(), "每筆%": 100 * P["報酬率"].mean(),
                "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / yrs) - 1),
                "最大回撤%": 100 * (eq / eq.cummax() - 1).min(), "斷頭": int((P["原因"] == "斷頭").sum()),
                "最差一筆萬": P["損益元"].min() / 1e4, "總損益萬": P["損益元"].sum() / 1e4,
            }
    S = pd.DataFrame(rows).T.astype(float).round(2)
    S.index.names = ["殖利率", "停利", "持有上限"]
    S.to_csv(RESULTS / "short_yield_hold.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_hold_trades.csv", index=False, encoding="utf-8-sig")
    PP = pd.DataFrame(prow).T.astype(float).round(1)
    PP.index.names = ["殖利率", "停利", "持有上限"]
    PP.to_csv(RESULTS / "short_yield_hold_portfolio.csv", encoding="utf-8-sig")
    log("\n【D. 持有上限掃描（交易日，到期隔天開盤回補）：空頭排列、不轉多就補、不停損｜每檔獨立】\n" + fmt(S))
    log("\n【D. 持有上限掃描｜5 檔組合（500 萬）】\n" + fmt(PP))
    return S, PP


def main(argv=()):
    t0 = time.time()
    lines = []

    def log(s=""):
        print(s)
        lines.append(str(s))

    data, dates, regimes, tai = prepare()
    log(f"資料準備完成：{len(data)} 檔，{time.time() - t0:.0f} 秒")
    # 殖利率門檻下有多少候選
    span = dates[dates >= UNIVERSE_START]
    cnt = {}
    for yname, y_th in YIELDS.items():
        if y_th is None:
            continue
        ok = sum(((d["yield"] < y_th) & d["member"]).reindex(span).fillna(False).astype(int) for d in data.values())
        cnt[yname] = {"平均每天符合檔數": ok.mean(), "最少": ok.min(), "最多": ok.max()}
    log("\n各殖利率門檻下，成分股中符合的檔數（每天）：\n" + fmt(pd.DataFrame(cnt).T.round(1)))
    if "hold" in argv:
        hold_scan(data, dates, regimes, log)
        (RESULTS / "short_yield_hold.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    if "targets" in argv:
        target_scan(data, dates, regimes, log)
        (RESULTS / "short_yield_targets.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    per_trade(data, regimes, log)
    portfolio(data, dates, regimes, log)
    target_scan(data, dates, regimes, log)
    hold_scan(data, dates, regimes, log)
    log(f"\n總耗時 {time.time() - t0:.0f} 秒")
    (RESULTS / "short_yield_study.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
