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
      python short_yield_study.py add        # 只跑逆勢加碼一次（漲 5% 加碼）
      python short_yield_study.py gap        # 只跑「距最後回補日不足 N 天不放空」
      python short_yield_study.py flip       # 只跑「大盤轉多且有賺就回補」
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


PREPARED = RESULTS / "short_prepared.pkl"


def prepare(cache=True):
    """每檔：還原價、原始收盤、預估殖利率、技術放空訊號、成分股期間、除息停券。
    cache=True 時存／讀 results/short_prepared.pkl（資料更新後請刪掉它重算）。"""
    if cache and PREPARED.exists():
        return pd.read_pickle(PREPARED)
    out = _prepare()
    if cache:
        RESULTS.mkdir(exist_ok=True)
        pd.to_pickle(out, PREPARED)
    return out


def _prepare():
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
        # 距下一個「最後回補日」的日曆天數（force 標在最後回補日前一天收盤；沒有已知的下一次 → NaN）
        fdates = df.index[force.to_numpy()].values
        if len(fdates):
            pos = np.searchsorted(fdates, df.index.values)
            nxt = fdates[np.minimum(pos, len(fdates) - 1)].astype("datetime64[ns]")
            gap = (nxt - df.index.values).astype("timedelta64[D]").astype(float)
            gap[pos >= len(fdates)] = np.nan
        else:
            gap = np.full(len(df), np.nan)
        days_to_force = pd.Series(gap, index=df.index)
        data[sid] = {
            "days_to_force": days_to_force,
            "df": df, "name": names.get(sid, ""), "raw_close": raw_close,
            "yield": 100 * dps / raw_close,
            "sig": short_entries(df)["任一"].fillna(False),
            "member": member[sid].reindex(df.index).ffill().fillna(False).astype(bool),
            "force": force, "block": block,
            "start": max(UNIVERSE_START, df.index[0] + pd.Timedelta(days=200)),
        }
    return data, dates, regimes, tai


def entry_signal(d, y_th, rname, regimes, min_days_to_force=None):
    sig = d["sig"] & d["member"]
    if min_days_to_force is not None:
        gap = d["days_to_force"]
        sig = sig & ~(gap < min_days_to_force).fillna(False)
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


# ---------- 加碼版放空引擎（每檔獨立） ----------

def run_short_add(df, short, cover, start, end, tp=TARGET, first=1.0, add_at=None, add_frac=0.0, max_days=None,
                  force=None, block=None):
    """同 short_study.run_short，但支援一次逆勢加碼：收盤較首空價漲 add_at 後，隔天開盤加碼 add_frac×權益。
    停利、斷頭都以「平均放空價」計。首空名目＝first×權益。"""
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    dates = df.index
    o, c = df["open"].values, df["close"].values
    short = short.reindex(dates).fillna(False).to_numpy(dtype=bool)
    cover = cover.reindex(dates).fillna(False).to_numpy(dtype=bool)
    force = force.reindex(dates).fillna(False).to_numpy(dtype=bool) if force is not None else np.zeros(len(df), bool)
    block = block.reindex(dates).fillna(False).to_numpy(dtype=bool) if block is not None else np.zeros(len(df), bool)
    chg = df["close"].pct_change().to_numpy()
    trades, equity, eq, pos = [], [], 1.0, None
    for n, i in enumerate(idx):
        if n > 0:
            prev = idx[n - 1]
            if pos is None:
                ok = short[prev] and not block[i]
                if ok and chg[prev] <= UPTICK_DROP and o[i] < c[prev]:
                    ok = False
                if ok:
                    N = first * eq / o[i]
                    pos = {"i0": i, "p0": o[i], "legs": [(i, o[i], N)], "N": N, "eq0": eq, "exit": None, "pending_add": False, "added": False}
            elif pos["exit"]:
                px = o[i]
                pnl = sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - px * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (dates[i] - dates[ik]).days / 365
                          for ik, pk, Nk in pos["legs"])
                eq = max(pos["eq0"] + pnl, 1e-9)
                avg = sum(pk * Nk for _, pk, Nk in pos["legs"]) / pos["N"]
                trades.append((dates[pos["i0"]], pos["p0"], avg, dates[i], px, eq / pos["eq0"] - 1, i - pos["i0"], pos["exit"], int(pos["added"])))
                pos = None
            elif pos["pending_add"] and not block[i]:
                N2 = add_frac * pos["eq0"] / o[i]
                pos["legs"].append((i, o[i], N2)); pos["N"] += N2; pos["added"] = True; pos["pending_add"] = False
        if pos is not None:
            pnl = sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - c[i] * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (dates[i] - dates[ik]).days / 365
                      for ik, pk, Nk in pos["legs"])
            avg = sum(pk * Nk for _, pk, Nk in pos["legs"]) / pos["N"]
            ret = c[i] / avg - 1
            reason = None
            if cover[i]:
                reason = "訊號"
            if max_days is not None and i - pos["i0"] + 1 >= max_days:
                reason = "到期"
            if ret <= -tp:
                reason = "停利"
            if ret >= MARGIN_CALL:
                reason = "斷頭"
            if force[i]:
                reason = "強制回補"
            pos["exit"] = reason
            if add_at is not None and not pos["added"] and reason is None and c[i] / pos["p0"] - 1 >= add_at:
                pos["pending_add"] = True
            equity.append(max(pos["eq0"] + pnl, 1e-9))
        else:
            equity.append(eq)
    if pos is not None:
        i = idx[-1]
        pnl = sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - c[i] * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (dates[i] - dates[ik]).days / 365
                  for ik, pk, Nk in pos["legs"])
        eq = max(pos["eq0"] + pnl, 1e-9)
        avg = sum(pk * Nk for _, pk, Nk in pos["legs"]) / pos["N"]
        trades.append((dates[pos["i0"]], pos["p0"], avg, dates[i], c[i], eq / pos["eq0"] - 1, i - pos["i0"], "期末", int(pos["added"])))
        equity[-1] = eq
    T = pd.DataFrame(trades, columns=["entry_date", "entry_price", "avg_price", "exit_date", "exit_price", "return", "bars", "reason", "added"])
    T["days"] = (pd.to_datetime(T["exit_date"]) - pd.to_datetime(T["entry_date"])).dt.days
    return T, pd.Series(equity, index=dates[idx])


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

def run_portfolio(data, dates, regimes, y_th, rname, flip, capital=CAPITAL, slots=SLOTS, target=TARGET, max_days=None,
                  first=1.0, add_at=None, add_frac=0.0, min_days_to_force=None, flip_gain=None):
    """flip_gain 不為 None 時：盤勢轉多且放空獲利 >= flip_gain 就回補（原因「轉多有賺」）；flip=True 則是轉多一律回補。"""
    """名目＝進場時總資產 ÷ slots；最多 slots 檔；同日多檔依殖利率低到高。回傳 (交易, 每日權益)。"""
    span = dates[dates >= UNIVERSE_START]
    arr = {}
    for sid, d in data.items():
        df = d["df"].reindex(span)
        sig = entry_signal(d, y_th, rname, regimes, min_days_to_force).reindex(span).fillna(False).to_numpy(dtype=bool)
        cov = cover_signal(d, rname, regimes, flip).reindex(span).fillna(False).to_numpy(dtype=bool)
        bull = cover_signal(d, rname, regimes, True).reindex(span).fillna(False).to_numpy(dtype=bool)
        last = d["df"].index[-1]
        arr[sid] = {"open": df["open"].to_numpy(), "close": df["close"].to_numpy(), "close_ff": df["close"].ffill().to_numpy(),
                    "sig": sig, "cover": cov, "force": d["force"].reindex(span).fillna(False).to_numpy(dtype=bool),
                    "block": d["block"].reindex(span).fillna(False).to_numpy(dtype=bool),
                    "bull": bull, "yield": d["yield"].reindex(span).to_numpy(), "chg": df["close"].pct_change().to_numpy(),
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
                pnl = sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - px * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (span[n] - span[nk]).days / 365
                          for nk, pk, Nk in p["legs"])
                eq += pnl
                trades.append((sid, data[sid]["name"], span[p["n0"]], p["p0"], span[n], px, pnl * capital, pnl / p["notional"], days,
                               p["exit"] + ("（已加碼）" if len(p["legs"]) > 1 else "")))
                del pos[sid]
            # 1b. 加碼（前一天收盤較首空價漲 add_at；名目 add_frac×進場時總資產）
            for sid, p in pos.items():
                a = arr[sid]
                if p.get("pending_add") and not a["block"][n] and not np.isnan(a["open"][n]):
                    N2 = add_frac * p["eq_entry"] / a["open"][n]
                    p["legs"].append((n, a["open"][n], N2)); p["N"] += N2; p["notional"] += add_frac * p["eq_entry"]
                    p["pending_add"] = False
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
                notional = first * eq / slots
                N = notional / a["open"][n]
                pos[sid] = {"n0": n, "p0": a["open"][n], "N": N, "notional": notional, "legs": [(n, a["open"][n], N)],
                            "eq_entry": eq / slots, "exit": None, "pending_add": False}
        # 3. 收盤：評價與決策
        mark = eq
        for sid, p in pos.items():
            a = arr[sid]
            c = a["close_ff"][n]
            mark += sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - c * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (span[n] - span[nk]).days / 365
                        for nk, pk, Nk in p["legs"])
            avg = sum(pk * Nk for _, pk, Nk in p["legs"]) / p["N"]
            ret = c / avg - 1
            reason = None
            if a["cover"][n]:
                reason = "轉多回補"
            if flip_gain is not None and a["bull"][n] and -ret >= flip_gain:
                reason = "轉多有賺"
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
            if add_at is not None and len(p["legs"]) == 1 and reason is None and c / p["p0"] - 1 >= add_at:
                p["pending_add"] = True
        equity.append(max(mark, 1e-9))
    # 期末
    n = len(span) - 1
    for sid, p in pos.items():
        a = arr[sid]
        c = a["close_ff"][n]
        days = (span[n] - span[p["n0"]]).days
        pnl = sum(Nk * (pk * (1 - SELL_COST - SHORT_FEE) - c * (1 + BUY_COST)) - Nk * pk * BORROW_RATE * (span[n] - span[nk]).days / 365
                  for nk, pk, Nk in p["legs"])
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


# ---------- E. 逆勢加碼一次 ----------

ADD_SCHEMES = {"不加碼（首空100%）": (1.0, None, 0.0), "首空50%＋漲5%加碼50%": (0.5, 0.05, 0.5),
               "首空100%＋漲5%加碼100%": (1.0, 0.05, 1.0)}


def add_scan(data, dates, regimes, log, combos=(("殖利率<2%", "空頭排列"), ("殖利率<1.5%", "空頭排列")), caps=(None, 20)):
    """停利 5%（以平均放空價計）、不轉多就補、不停損；逆勢加碼一次 × 持有上限。"""
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    rows, prow, all_t = {}, {}, []
    for yname, rname_s in combos:
        y_th, rname = YIELDS[yname], REGIMES[rname_s]
        for sname, (first, add_at, add_frac) in ADD_SCHEMES.items():
            for md in caps:
                hname = "無上限" if md is None else f"{md}日"
                tr = []
                for sid, d in data.items():
                    sig = entry_signal(d, y_th, rname, regimes)
                    if not sig.any():
                        continue
                    t, _ = run_short_add(d["df"], sig, cover_signal(d, rname, regimes, False), d["start"], d["df"].index[-1],
                                         tp=TARGET, first=first, add_at=add_at, add_frac=add_frac, max_days=md, force=d["force"], block=d["block"])
                    if len(t):
                        tr.append(t.assign(stock_id=sid))
                T = pd.concat(tr, ignore_index=True)
                r = T["return"]  # 以權益計：首空 50% 的報酬率是對整個 1/5 名目
                wins, losses = r[r > 0], r[r <= 0]
                T["年"] = T["entry_date"].dt.year
                key = (yname, sname, hname)
                rows[key] = {
                    "筆數": len(r), "加碼筆數": int(T["added"].sum()), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                    "平均獲利%": 100 * wins.mean(), "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                    "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                    "平均天數": T["days"].mean(), "停利／到期／強制／斷頭": "／".join(str(int((T["reason"] == k).sum())) for k in ("停利", "到期", "強制回補", "斷頭")),
                    "加碼那些勝率%": 100 * (T[T["added"] == 1]["return"] > 0).mean() if T["added"].any() else np.nan,
                    "加碼那些每筆%": 100 * T[T["added"] == 1]["return"].mean() if T["added"].any() else np.nan,
                    "最差一筆%": 100 * r.min(), "每檔每年貢獻%": 100 * r.sum() / T["stock_id"].nunique() / years,
                    "前段每筆%": 100 * T[T["年"] <= 2023]["return"].mean(), "後段每筆%": 100 * T[T["年"] >= 2024]["return"].mean(),
                }
                all_t.append(T.assign(殖利率=yname, 加碼=sname, 持有上限=hname))
                P, eq = run_portfolio(data, dates, regimes, y_th, rname, False, target=TARGET, max_days=md, first=first, add_at=add_at, add_frac=add_frac)
                yrs = (eq.index[-1] - eq.index[0]).days / 365.25
                prow[key] = {
                    "筆數": len(P), "加碼筆數": int(P["原因"].str.contains("已加碼").sum()), "勝率%": 100 * (P["報酬率"] > 0).mean(),
                    "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / yrs) - 1),
                    "最大回撤%": 100 * (eq / eq.cummax() - 1).min(), "斷頭": int(P["原因"].str.startswith("斷頭").sum()),
                    "最差一筆萬": P["損益元"].min() / 1e4, "總損益萬": P["損益元"].sum() / 1e4,
                }
    S = pd.DataFrame(rows).T
    S.index.names = ["殖利率", "加碼", "持有上限"]
    num = [c for c in S.columns if c != "停利／到期／強制／斷頭"]
    S[num] = S[num].astype(float).round(2)
    S.to_csv(RESULTS / "short_yield_add.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_add_trades.csv", index=False, encoding="utf-8-sig")
    PP = pd.DataFrame(prow).T.astype(float).round(1)
    PP.index.names = ["殖利率", "加碼", "持有上限"]
    PP.to_csv(RESULTS / "short_yield_add_portfolio.csv", encoding="utf-8-sig")
    log("\n【E. 逆勢加碼一次（收盤較首空價漲 5% → 隔天開盤加碼；停利 5% 以平均放空價計）｜每檔獨立，報酬率以整個名目計】\n" + fmt(S))
    log("\n【E. 逆勢加碼一次｜5 檔組合（500 萬；首空 50% 時每檔首空名目＝總資產 1/10）】\n" + fmt(PP))
    return S, PP


# ---------- F. 距最後回補日不足 N 天不放空 ----------

GAPS = (None, 15, 30, 45, 60)


def gap_scan(data, dates, regimes, log, combos=(("殖利率<1.5%", "空頭排列"), ("殖利率<2%", "空頭排列"))):
    """停利 5%、不轉多就補、不停損、不加碼、無上限；進場時距下一個除權息最後回補日不足 N 個日曆天就不放空。"""
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    rows, prow, all_t = {}, {}, []
    for yname, rname_s in combos:
        y_th, rname = YIELDS[yname], REGIMES[rname_s]
        for g in GAPS:
            gname = "不限" if g is None else f"≥{g}天"
            tr = []
            for sid, d in data.items():
                sig = entry_signal(d, y_th, rname, regimes, g)
                if not sig.any():
                    continue
                t, _ = run_short(d["df"], sig, cover_signal(d, rname, regimes, False), d["start"], d["df"].index[-1],
                                 tp=TARGET, force=d["force"], block=d["block"])
                if len(t):
                    t = t.assign(stock_id=sid)
                    t["距最後回補日"] = d["days_to_force"].reindex(t["entry_date"]).to_numpy()
                    tr.append(t)
            T = pd.concat(tr, ignore_index=True)
            r = T["return"]
            wins, losses = r[r > 0], r[r <= 0]
            T["年"] = T["entry_date"].dt.year
            key = (yname, gname)
            rows[key] = {
                "筆數": len(r), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                "平均獲利%": 100 * wins.mean(), "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                "平均天數": T["days"].mean(), "停利／強制回補／斷頭": "／".join(str(int((T["reason"] == k).sum())) for k in ("停利", "強制回補", "斷頭")),
                "強制回補那些每筆%": 100 * T[T["reason"] == "強制回補"]["return"].mean() if (T["reason"] == "強制回補").any() else np.nan,
                "最差一筆%": 100 * r.min(), "每檔每年貢獻%": 100 * r.sum() / T["stock_id"].nunique() / years,
                "前段每筆%": 100 * T[T["年"] <= 2023]["return"].mean(), "後段每筆%": 100 * T[T["年"] >= 2024]["return"].mean(),
            }
            all_t.append(T.assign(殖利率=yname, 距回補日門檻=gname))
            P, eq = run_portfolio(data, dates, regimes, y_th, rname, False, target=TARGET, min_days_to_force=g)
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            prow[key] = {
                "筆數": len(P), "勝率%": 100 * (P["報酬率"] > 0).mean(), "每筆%": 100 * P["報酬率"].mean(),
                "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / yrs) - 1),
                "最大回撤%": 100 * (eq / eq.cummax() - 1).min(), "強制回補筆數": int(P["原因"].str.startswith("強制回補").sum()),
                "斷頭": int(P["原因"].str.startswith("斷頭").sum()), "最差一筆萬": P["損益元"].min() / 1e4, "總損益萬": P["損益元"].sum() / 1e4,
            }
    S = pd.DataFrame(rows).T
    S.index.names = ["殖利率", "距最後回補日"]
    num = [c for c in S.columns if c != "停利／強制回補／斷頭"]
    S[num] = S[num].astype(float).round(2)
    S.to_csv(RESULTS / "short_yield_gap.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_gap_trades.csv", index=False, encoding="utf-8-sig")
    PP = pd.DataFrame(prow).T.astype(float).round(1)
    PP.index.names = ["殖利率", "距最後回補日"]
    PP.to_csv(RESULTS / "short_yield_gap_portfolio.csv", encoding="utf-8-sig")
    log("\n【F. 距下一個除權息最後回補日不足 N 個日曆天就不放空｜每檔獨立】\n" + fmt(S))
    log("\n【F. 距最後回補日門檻｜5 檔組合（500 萬）】\n" + fmt(PP))
    return S, PP


# ---------- G. 大盤轉多且有賺就回補 ----------

FLIP_GAINS = (None, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03)


def flip_scan(data, dates, regimes, log, combos=(("殖利率<1.5%", "空頭排列"), ("殖利率<2%", "空頭排列")), min_gap=30):
    """停利 5%、不停損、不加碼、距最後回補日 ≥30 天；加「大盤空頭排列消失且放空獲利 ≥ X% 就回補」。"""
    years = (max(d["df"].index[-1] for d in data.values()) - UNIVERSE_START).days / 365.25
    rows, prow, all_t = {}, {}, []
    for yname, rname_s in combos:
        y_th, rname = YIELDS[yname], REGIMES[rname_s]
        for fg in FLIP_GAINS:
            fname = "不看轉多" if fg is None else f"轉多且賺≥{100 * fg:g}%"
            tr = []
            for sid, d in data.items():
                sig = entry_signal(d, y_th, rname, regimes, min_gap)
                if not sig.any():
                    continue
                bull = cover_signal(d, rname, regimes, True)
                t, _ = run_short(d["df"], sig, cover_signal(d, rname, regimes, False), d["start"], d["df"].index[-1],
                                 tp=TARGET, force=d["force"], block=d["block"],
                                 flip=bull if fg is not None else None, flip_gain=fg if fg is not None else 0.0)
                if len(t):
                    tr.append(t.assign(stock_id=sid))
            T = pd.concat(tr, ignore_index=True)
            r = T["return"]
            wins, losses = r[r > 0], r[r <= 0]
            T["年"] = T["entry_date"].dt.year
            key = (yname, fname)
            rows[key] = {
                "筆數": len(r), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                "平均獲利%": 100 * wins.mean(), "平均虧損%": 100 * losses.mean() if len(losses) else 0,
                "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.inf,
                "平均天數": T["days"].mean(),
                "停利／轉多有賺／強制回補／斷頭": "／".join(str(int((T["reason"] == k).sum())) for k in ("停利", "轉多有賺", "強制回補", "斷頭")),
                "轉多有賺那些每筆%": 100 * T[T["reason"] == "轉多有賺"]["return"].mean() if (T["reason"] == "轉多有賺").any() else np.nan,
                "最差一筆%": 100 * r.min(), "每檔每年貢獻%": 100 * r.sum() / T["stock_id"].nunique() / years,
                "前段每筆%": 100 * T[T["年"] <= 2023]["return"].mean(), "後段每筆%": 100 * T[T["年"] >= 2024]["return"].mean(),
            }
            all_t.append(T.assign(殖利率=yname, 轉多回補=fname))
            P, eq = run_portfolio(data, dates, regimes, y_th, rname, False, target=TARGET, min_days_to_force=min_gap, flip_gain=fg)
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            prow[key] = {
                "筆數": len(P), "勝率%": 100 * (P["報酬率"] > 0).mean(), "每筆%": 100 * P["報酬率"].mean(),
                "期末萬": eq.iloc[-1] * CAPITAL / 1e4, "IRR%": 100 * (eq.iloc[-1] ** (1 / yrs) - 1),
                "最大回撤%": 100 * (eq / eq.cummax() - 1).min(), "強制回補": int(P["原因"].str.startswith("強制回補").sum()),
                "斷頭": int(P["原因"].str.startswith("斷頭").sum()), "最差一筆萬": P["損益元"].min() / 1e4, "總損益萬": P["損益元"].sum() / 1e4,
            }
            all_t[-1] = all_t[-1].assign(組合筆數=len(P))
    S = pd.DataFrame(rows).T
    S.index.names = ["殖利率", "轉多回補"]
    num = [c for c in S.columns if c != "停利／轉多有賺／強制回補／斷頭"]
    S[num] = S[num].astype(float).round(2)
    S.to_csv(RESULTS / "short_yield_flip.csv", encoding="utf-8-sig")
    pd.concat(all_t).to_csv(RESULTS / "short_yield_flip_trades.csv", index=False, encoding="utf-8-sig")
    PP = pd.DataFrame(prow).T.astype(float).round(1)
    PP.index.names = ["殖利率", "轉多回補"]
    PP.to_csv(RESULTS / "short_yield_flip_portfolio.csv", encoding="utf-8-sig")
    log("\n【G. 大盤空頭排列消失且放空獲利 ≥X% 就回補（停利 5%、距最後回補日 ≥30 天）｜每檔獨立】\n" + fmt(S))
    log("\n【G.｜5 檔組合（500 萬）】\n" + fmt(PP))
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
    if "flip" in argv:
        flip_scan(data, dates, regimes, log)
        (RESULTS / "short_yield_flip.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    if "gap" in argv:
        gap_scan(data, dates, regimes, log)
        (RESULTS / "short_yield_gap.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    if "add" in argv:
        add_scan(data, dates, regimes, log)
        (RESULTS / "short_yield_add.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
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
    add_scan(data, dates, regimes, log)
    gap_scan(data, dates, regimes, log)
    flip_scan(data, dates, regimes, log)
    log(f"\n總耗時 {time.time() - t0:.0f} 秒")
    (RESULTS / "short_yield_study.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
