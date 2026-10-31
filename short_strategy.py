"""進取版放空策略（正式程式）：殖利率 <2% ＋ 大盤空頭排列 ＋ 鏡像技術放空點，獲利 5% 回補。

規則（全部以收盤判斷、隔天開盤成交；細節與理由見 SHORT_RULES.md）
  範圍    當天屬於 0050 或 0056 成分股的全部股票（data/universe/constituents.csv）
  放空    同時成立：
          1. 預估殖利率 < 2%（近四季 EPS × 近 3 年平均配息率 ÷ 原始收盤；年配且已公告未除息用公告值；算不出的不空）
          2. 利空環境：加權指數 MA5 < MA20 < MA60，且指數對 MA20 乖離介於 −10% ～ +1%
          3. 技術放空點任一：①超買共振（KD>80／RSI>70／WR>−20／CCI>100 三日內 ≥3 個）＋KD 死叉＋收盤在年線下
                              ②爆量（>1.5 倍 20 日均量）長上影線 或 爆量長黑（跌幅 >2%）
                              ③三日內觸布林上軌 ＋ K>70 死叉
                              ④高檔區（五日內觸上軌且 K>70）＋ 爆量長上影線／爆量長黑／價創高量縮
          4. 距該股下一個除權息「最後回補日」≥ 30 個日曆天（未公告的不受限）；停券期間不空
          5. 前一日跌幅 ≥3.5% 的股票，隔天開盤低於前收就放棄（平盤下不得放空）
  部位    最多 5 檔，每檔名目 = 放空當時權益 ÷ 5，一次放足、不加碼；同日多檔依殖利率低到高挑
  回補    1. 收盤較放空價跌 ≥ 5%
          2. 大盤空頭排列消失 且 收盤較放空價跌 ≥ 2%，連續兩個收盤成立
          3. 除權息最後回補日（制度）；股價較放空價漲 ≥ 46%（維持率 130% 斷頭）；下市
  不做    不停損、不設持有期限、不加碼、轉多但獲利不到 2% 不回補
  成本    放空賣出 0.1425% ＋ 證交稅 0.3% ＋ 融券手續費 0.08%；回補 0.1425%；借券費 2%／年；回測用還原價（等同放空者賠付股利）

用法
  python short_strategy.py                          # 500 萬、2017-01-03 起回測到最新資料日，並列出明天該做的事
  python short_strategy.py --capital 3000000
  python short_strategy.py --asof 2025-04-09        # 假裝今天是這一天
  python short_strategy.py --no-cache               # 資料更新後重算殖利率（或直接刪 results/short_strategy_prepared.pkl）
輸出
  results/short_strategy_trades.csv（逐筆）、results/short_strategy_equity.csv（每日權益）
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import BUY_COST, RESULTS, ROOT, SELL_COST
from indicators import bollinger, cci_line, cross_down, kd, pv_triggers, rsi, setup_zones, sma, williams_r
from portfolio_study import UNI, dividend_events, eps_table, forward_dividend, load_prices, membership

# ---------- 規則常數 ----------
MAX_YIELD = 2.0            # 預估殖利率 < 2%
BIAS_LO, BIAS_HI = -10.0, 1.0  # 指數對 MA20 乖離區間（%）
TARGET = 0.05              # 停利：跌 5%
FLIP_GAIN, FLIP_CONFIRM = 0.02, 2  # 大盤轉多且賺 2%，連續 2 個收盤
MIN_DAYS_TO_FORCE = 30     # 距最後回補日 ≥30 個日曆天才空
FORCE_COVER_BEFORE = 5     # 最後回補日 = 除權息日前 5 個交易日
MARGIN_CALL = 0.46         # 漲 46% 斷頭
UPTICK_DROP = -0.035       # 前日跌 3.5% → 不得平盤下放空
SLOTS = 5
SHORT_FEE, BORROW_RATE = 0.0008, 0.02
START = pd.Timestamp("2017-01-03")
WARMUP_DAYS = 200          # 每檔上市後至少 200 天才納入
CACHE = RESULTS / "short_strategy_prepared.pkl"


# ---------- 訊號 ----------

def short_signal(df):
    """正式版四個技術買點的鏡像，任一成立。回傳布林 Series。"""
    c, k = df["close"], None
    k, d = kd(df)
    t = pv_triggers(df)
    pv_sell = t["wick_sell"] | t["pv_sell"]
    _, _, upper = bollinger(df)
    touched_upper = (df["high"] >= upper).astype(int).rolling(3).max().astype(bool)
    _, high_zone, *_ = setup_zones(df)
    recent = lambda cond: cond.fillna(False).astype(int).rolling(3).max().astype(bool)
    n_overbought = sum(recent(x).astype(int) for x in (k > 80, rsi(c) > 70, williams_r(df) > -20, cci_line(df) > 100))
    resonance = (n_overbought >= 3) & cross_down(k, d) & (c < sma(c, 240))
    sig = resonance | pv_sell | (touched_upper & cross_down(k, d) & (k > 70)) | (high_zone & pv_sell)
    return sig.fillna(False)


def market_state(tai):
    """加權指數：空頭排列、乖離是否在區間內。"""
    ma5, ma20, ma60 = (sma(tai, n) for n in (5, 20, 60))
    bear = (ma5 < ma20) & (ma20 < ma60)
    bias = (tai / ma20 - 1) * 100
    return bear, (bias >= BIAS_LO) & (bias <= BIAS_HI), bias


def ex_dividend_schedule(index, ex_dates):
    """回傳 (最後回補日前一天收盤要回補, 停券期, 距下一個最後回補日的日曆天數)。"""
    force = pd.Series(False, index=index)
    block = pd.Series(False, index=index)
    pos = index.searchsorted(pd.DatetimeIndex(ex_dates))
    for p in pos:
        last = p - FORCE_COVER_BEFORE
        if last - 1 < 0 or p > len(index):
            continue
        force.iloc[last - 1] = True
        block.iloc[max(last - 1, 0):p] = True
    fdates = index[force.to_numpy()].values
    if len(fdates):
        k = np.searchsorted(fdates, index.values)
        nxt = fdates[np.minimum(k, len(fdates) - 1)].astype("datetime64[ns]")
        gap = (nxt - index.values).astype("timedelta64[D]").astype(float)
        gap[k >= len(fdates)] = np.nan
    else:
        gap = np.full(len(index), np.nan)
    return force, block, pd.Series(gap, index=index)


# ---------- 資料 ----------

def prepare(use_cache=True):
    if use_cache and CACHE.exists():
        return pd.read_pickle(CACHE)
    cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    dates = tai.index[tai.index >= pd.Timestamp("2015-01-01")]
    tai = tai.reindex(dates)
    member = membership(cons, dates)
    eps_all = pd.read_csv(UNI / "eps_all.csv")
    div_all = pd.read_csv(UNI / "dividend_all.csv")
    res_all = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    res_all["date"] = pd.to_datetime(res_all["date"])
    names = cons.drop_duplicates("stock_id").set_index("stock_id")["name"]
    stocks = {}
    for sid in sorted(set(cons["stock_id"])):
        loaded = load_prices(sid)
        if loaded is None or len(loaded[0]) < 300 or sid not in member:
            continue
        df, raw_close = loaded
        df = df[df.index >= pd.Timestamp("2015-01-01")]
        if df.index[-1] < START + pd.Timedelta(days=WARMUP_DAYS):
            continue
        dps = forward_dividend(df.index, eps_table(eps_all, sid), dividend_events(div_all, sid, res_all))
        ex_dates = res_all.loc[(res_all["stock_id"] == sid) & res_all["stock_or_cache_dividend"].astype(str).str.contains("息|權"), "date"]
        force, block, gap = ex_dividend_schedule(df.index, ex_dates.tolist())
        stocks[sid] = {
            "name": names.get(sid, ""), "df": df, "raw_close": raw_close.reindex(df.index),
            "yield": 100 * dps / raw_close.reindex(df.index), "signal": short_signal(df),
            "member": member[sid].reindex(df.index).ffill().fillna(False).astype(bool),
            "force": force, "block": block, "days_to_force": gap,
            "first_ok": df.index[0] + pd.Timedelta(days=WARMUP_DAYS),
        }
    out = {"stocks": stocks, "dates": dates, "taiex": tai}
    RESULTS.mkdir(exist_ok=True)
    pd.to_pickle(out, CACHE)
    return out


def truncate(data, asof):
    cut = pd.Timestamp(asof)
    dates = data["dates"][data["dates"] <= cut]
    stocks = {}
    for sid, s in data["stocks"].items():
        keep = s["df"].index <= cut
        if keep.sum() < 250:
            continue
        s2 = dict(s)
        for k in ("df", "raw_close", "yield", "signal", "member", "force", "block", "days_to_force"):
            s2[k] = s[k][keep]
        stocks[sid] = s2
    return {"stocks": stocks, "dates": dates, "taiex": data["taiex"].reindex(dates)}


# ---------- 回測引擎 ----------

def run(data, capital=5_000_000, start=START):
    """回傳 (逐筆, 每日權益, 目前空單)。權益以 1.0 起算，乘 capital 得金額。"""
    dates = data["dates"][data["dates"] >= start]
    bear, bias_ok, _ = market_state(data["taiex"])
    bear = bear.reindex(dates).fillna(False).to_numpy(dtype=bool)
    bias_ok = bias_ok.reindex(dates).fillna(False).to_numpy(dtype=bool)
    A = {}
    for sid, s in data["stocks"].items():
        df = s["df"].reindex(dates)
        y = s["yield"].reindex(dates).to_numpy()
        gap = s["days_to_force"].reindex(dates).to_numpy()
        last = s["df"].index[-1]
        A[sid] = {
            "open": df["open"].to_numpy(), "close": df["close"].to_numpy(), "close_ff": df["close"].ffill().to_numpy(),
            "chg": df["close"].pct_change().to_numpy(), "yield": y,
            "entry": (s["signal"].reindex(dates).fillna(False).to_numpy(dtype=bool)
                      & s["member"].reindex(dates).fillna(False).to_numpy(dtype=bool)
                      & (y < MAX_YIELD) & bear & bias_ok & ~(gap < MIN_DAYS_TO_FORCE)),
            "force": s["force"].reindex(dates).fillna(False).to_numpy(dtype=bool),
            "block": s["block"].reindex(dates).fillna(False).to_numpy(dtype=bool),
            "start_n": dates.searchsorted(max(start, s["first_ok"])),
            "delist_n": dates.get_indexer([last])[0] if last < dates[-1] - pd.Timedelta(days=10) else len(dates) + 5,
        }

    def pnl(p, px, n):
        days = (dates[n] - dates[p["n0"]]).days
        return p["N"] * (p["p0"] * (1 - SELL_COST - SHORT_FEE) - px * (1 + BUY_COST)) - p["N"] * p["p0"] * BORROW_RATE * days / 365

    eq, pos, trades, equity = 1.0, {}, [], []
    for n in range(len(dates)):
        if n > 0:
            # 1. 前一天收盤決定的回補，今天開盤成交
            for sid in list(pos):
                p = pos[sid]
                if p["exit"] is None:
                    continue
                a = A[sid]
                px = a["open"][n] if not np.isnan(a["open"][n]) else a["close_ff"][n - 1]
                g = pnl(p, px, n)
                eq += g
                trades.append(dict(代號=sid, 名稱=data["stocks"][sid]["name"], 進場=dates[p["n0"]], 放空價=p["p0"], 出場=dates[n], 回補價=px,
                                   天數=(dates[n] - dates[p["n0"]]).days, 報酬率=g / p["notional"], 損益元=g * capital, 原因=p["exit"]))
                del pos[sid]
            # 2. 前一天收盤的放空訊號，今天開盤放空（依殖利率低到高，補滿空位）
            cands = []
            for sid, a in A.items():
                if sid in pos or n < a["start_n"] or n >= a["delist_n"] or not a["entry"][n - 1] or a["block"][n]:
                    continue
                if np.isnan(a["open"][n]) or (a["chg"][n - 1] <= UPTICK_DROP and a["open"][n] < a["close"][n - 1]):
                    continue
                cands.append((a["yield"][n - 1], sid))
            for _, sid in sorted(cands)[:max(0, SLOTS - len(pos))]:
                a = A[sid]
                notional = eq / SLOTS
                pos[sid] = {"n0": n, "p0": a["open"][n], "N": notional / a["open"][n], "notional": notional, "exit": None, "streak": 0}
        # 3. 今天收盤：評價、決定明天的回補
        mark = eq
        for sid, p in pos.items():
            a = A[sid]
            c = a["close_ff"][n]
            mark += pnl(p, c, n)
            gain = 1 - c / p["p0"]
            p["streak"] = p["streak"] + 1 if (not bear[n] and gain >= FLIP_GAIN) else 0
            reason = None
            if p["streak"] >= FLIP_CONFIRM:
                reason = "轉多有賺"
            if gain >= TARGET:
                reason = "獲利5%"
            if -gain >= MARGIN_CALL:
                reason = "斷頭"
            if a["force"][n]:
                reason = "強制回補"
            if n + 1 >= a["delist_n"]:
                reason = "下市"
            p["exit"] = reason
        equity.append(max(mark, 1e-9))

    open_positions = []
    n = len(dates) - 1
    for sid, p in pos.items():
        a = A[sid]
        c = a["close_ff"][n]
        open_positions.append(dict(代號=sid, 名稱=data["stocks"][sid]["name"], 進場=dates[p["n0"]], 放空價=p["p0"], 名目元=p["notional"] * capital,
                                   目前獲利=1 - c / p["p0"], 浮動損益元=pnl(p, c, n) * capital, 明天=p["exit"] or "", 轉多連續日=p["streak"]))
    T = pd.DataFrame(trades)
    return T, pd.Series(equity, index=dates), pd.DataFrame(open_positions)


# ---------- 報告 ----------

def summarize(T, eq, capital):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    held = pd.Series(0, index=eq.index)
    for a, b in zip(T["進場"], T["出場"]):
        held[(held.index >= a) & (held.index < b)] += 1
    return {
        "筆數": len(T), "勝率%": round(100 * (T["報酬率"] > 0).mean(), 1), "每筆平均%": round(100 * T["報酬率"].mean(), 2),
        "最小一筆%": round(100 * T["報酬率"].min(), 2), "最大一筆%": round(100 * T["報酬率"].max(), 2),
        "持有中位天數": T["天數"].median(), "期末資產萬": round(eq.iloc[-1] * capital / 1e4), "總損益萬": round(T["損益元"].sum() / 1e4, 1),
        "IRR%": round(100 * (eq.iloc[-1] ** (1 / years) - 1), 1), "最大回撤%": round(100 * (eq / eq.cummax() - 1).min(), 1),
        "有部位時間%": round(100 * (held > 0).mean(), 1), "檔數": T["代號"].nunique(),
        "回補原因": T["原因"].value_counts().to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--start", default=str(START.date()))
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    data = prepare(use_cache=not a.no_cache)
    if a.asof:
        data = truncate(data, a.asof)
    T, eq, openpos = run(data, a.capital, pd.Timestamp(a.start))
    dates, tai = data["dates"], data["taiex"]
    last = dates[-1]
    bear, bias_ok, bias = market_state(tai)
    ma5, ma20, ma60 = (sma(tai, n).iloc[-1] for n in (5, 20, 60))
    pd.set_option("display.width", 250); pd.set_option("display.unicode.east_asian_width", True); pd.set_option("display.max_rows", 500)

    print(__doc__.split("用法")[0].rstrip())
    print(f"\n{'=' * 100}\n【回測 {eq.index[0].date()} ~ {last.date()}，投入 {a.capital / 1e4:,.0f} 萬】")
    s = summarize(T, eq, a.capital)
    for k, v in s.items():
        print(f"  {k}：{v}")
    T2 = T.assign(年=T["進場"].dt.year, 損益萬=T["損益元"] / 1e4)
    print("\n逐年：\n" + T2.groupby("年").agg(筆數=("報酬率", "size"), 勝率=("報酬率", lambda x: round(100 * (x > 0).mean())), 損益萬=("損益萬", "sum")).round(1).T.to_string())
    show = T.copy()
    show["放空價"] = show["放空價"].round(2); show["回補價"] = show["回補價"].round(2)
    show["報酬%"] = (100 * show["報酬率"]).round(1); show["損益萬"] = (show["損益元"] / 1e4).round(1)
    show["進場"] = show["進場"].dt.date; show["出場"] = show["出場"].dt.date
    print("\n逐筆（價格為還原價）：\n" + show[["代號", "名稱", "進場", "放空價", "出場", "回補價", "天數", "報酬%", "損益萬", "原因"]].to_string(index=False))
    T.to_csv(RESULTS / "short_strategy_trades.csv", index=False, encoding="utf-8-sig")
    (eq * a.capital).rename("equity").to_csv(RESULTS / "short_strategy_equity.csv", encoding="utf-8-sig")

    print(f"\n{'=' * 100}\n【{last.date()} 收盤狀態】總資產 {eq.iloc[-1] * a.capital / 1e4:,.0f} 萬")
    today_bear, today_ok, today_bias = bool(bear.iloc[-1]), bool(bias_ok.iloc[-1]), bias.iloc[-1]
    why = ("空頭排列成立、乖離在區間內 → 可以新放空" if today_bear and today_ok else
           "非空頭排列 → 不新放空" if not today_bear else f"空頭排列成立但乖離 {today_bias:+.1f}% 超出 −10%～+1% → 不新放空")
    print(f"加權指數 {tai.iloc[-1]:,.0f}：MA5 {ma5:,.0f}／MA20 {ma20:,.0f}／MA60 {ma60:,.0f}，對月線乖離 {today_bias:+.1f}%。{why}")

    print("\n【目前空單】")
    acts = []
    if openpos.empty:
        print("（無）")
    for _, r in openpos.iterrows():
        s_ = data["stocks"][r["代號"]]
        raw = s_["raw_close"].iloc[-1]
        target_raw = raw * (1 - TARGET) / (1 - r["目前獲利"])
        if r["明天"]:
            status = f"明天開盤回補（{r['明天']}）"
            acts.append(f"回補 {r['代號']} {r['名稱']}：全部，原因「{r['明天']}」，目前獲利 {100 * r['目前獲利']:+.1f}%")
        elif not today_bear and r["轉多連續日"] == 1:
            status = f"大盤轉多且已賺 {100 * r['目前獲利']:.1f}%（連續第 1 天），明天收盤若仍成立就回補"
        elif not today_bear:
            status = f"大盤轉多但獲利 {100 * r['目前獲利']:+.1f}% 不到 2%，續抱"
        else:
            status = "續抱"
        print(f"  {r['代號']} {r['名稱']}：{r['進場'].date()} 放空，{(last - r['進場']).days} 天，名目 {r['名目元'] / 1e4:,.1f} 萬，"
              f"目前獲利 {100 * r['目前獲利']:+.1f}%（{r['浮動損益元'] / 1e4:+,.1f} 萬）；停利價位：原始收盤 ≤ 約 {target_raw:.1f}。{status}")

    print(f"\n【明天（{last.date()} 之後第一個交易日）開盤要做的事】")
    held = set(openpos["代號"]) if len(openpos) else set()
    if today_bear and today_ok:
        cands = []
        for sid, s_ in data["stocks"].items():
            if sid in held or s_["df"].index[-1] != last:
                continue
            y, gap = s_["yield"].iloc[-1], s_["days_to_force"].iloc[-1]
            if not (s_["member"].iloc[-1] and s_["signal"].iloc[-1] and not np.isnan(y) and y < MAX_YIELD):
                continue
            if s_["block"].iloc[-1] or (not np.isnan(gap) and gap < MIN_DAYS_TO_FORCE):
                continue
            chg = s_["df"]["close"].pct_change().iloc[-1]
            cands.append((y, sid, s_["name"], s_["raw_close"].iloc[-1], chg))
        slots = SLOTS - len(held)
        for y, sid, name, raw, chg in sorted(cands)[:max(slots, 0)]:
            note = "；昨日跌幅 ≥3.5%，開盤低於昨收就放棄" if chg <= UPTICK_DROP else ""
            acts.append(f"放空 {sid} {name}：名目約 {eq.iloc[-1] * a.capital / SLOTS / 1e4:,.1f} 萬（預估殖利率 {y:.2f}%，收盤 {raw:.1f}，停利目標約 {raw * (1 - TARGET):.1f}）{note}")
        if len(cands) > max(slots, 0):
            acts.append(f"（另有 {len(cands) - max(slots, 0)} 檔符合但沒有空位）")
    print("\n".join(acts) if acts else "沒有動作")

    print(f"\n【觀察名單：成分股中殖利率 < {MAX_YIELD:g}%、未放空】")
    rows = []
    for sid, s_ in data["stocks"].items():
        if sid in held or s_["df"].index[-1] != last:
            continue
        y = s_["yield"].iloc[-1]
        if not s_["member"].iloc[-1] or np.isnan(y) or y >= MAX_YIELD:
            continue
        gap = s_["days_to_force"].iloc[-1]
        rows.append(dict(代號=sid, 名稱=s_["name"], 收盤=round(s_["raw_close"].iloc[-1], 1), 預估殖利率=round(y, 2),
                         今日放空訊號="是" if s_["signal"].iloc[-1] else "", 停券中="是" if s_["block"].iloc[-1] else "",
                         距最後回補日="—" if np.isnan(gap) else f"{int(gap)}天" + ("（不足30天）" if gap < MIN_DAYS_TO_FORCE else "")))
    w = pd.DataFrame(rows).sort_values("預估殖利率") if rows else pd.DataFrame()
    print(w.to_string(index=False) if len(w) else "（無）")


if __name__ == "__main__":
    main()
