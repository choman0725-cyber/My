"""技術面做空研究：放空版回測引擎 ＋ 單檔（2382）樣本內外 ＋ 0050／0056 歷年成分股股票池。

放空規則（台股融券／借券賣出）：
- 收盤出現放空訊號 → 隔天開盤放空；出現回補訊號（或停損／停利／到期／強制回補）→ 隔天開盤回補。
- 同時只有一筆、名目金額＝進場時的權益（不開槓桿；融券保證金 90% 其實可放大 1.1 倍，這裡不算）。
- 成本：放空賣出 0.1425% ＋ 證交稅 0.3% ＋ 融券手續費 0.08%；回補買進 0.1425%；借券費 2%／年按日計。
- 斷頭：融券保證金 90%，維持率 130%；股價較放空價漲 46% 以上，收盤即視為被斷頭，隔天開盤回補（永遠開啟）。
- 股利：回測用還原價，除息缺口已被抹平，等於放空者「賠付股利」（實務上融券要補股利給出借人），方向正確。
- 台股限制（可開關）：
  1. 前一日跌幅 >= 3.5% 的股票，隔天不得在平盤以下放空 → 開盤低於前收就不進場。
  2. 除權息前強制回補：最後回補日約在除權息日前 5 個交易日，之後到除權息日前不能新放空（停券）。
     股東會前也要回補，但沒有股東會日期資料，這裡沒算（會再少掉每年 4～6 月約一個半月的放空機會）。
  3. 全市場禁止平盤下放空的時期（2008、2020-03、2022-10 等）沒有另外模擬。

三層研究：
  一、2382 單檔：既有 40 多個技術策略「賣出訊號當放空、買進訊號當回補」，加 10 個放空專用策略（S 系列），
      比較樣本內（前 7 年）／樣本外；同一組訊號「做多 vs 做空」並列。
  二、出場變體：訊號回補／＋停損 10%／停損 10% 最多 60 日／停利 15% 停損 10% 最多 120 日／移動停損 8%。
  三、股票池：149 檔成分股（在成分股期間才放空）2017-01 起，彙總每筆報酬、勝率、賺賠比、年化貢獻，
      再按大盤位置（加權指數在年線上／下、是否空頭排列）拆開看放空什麼時候才有用。
  四、先判多空盤：10 種加權指數空頭盤定義，先看定義本身（期間占比、期間內指數報酬、放空 0050），再看
      「只在空頭盤內放空個股、轉多就回補或照訊號回補、多頭盤完全不做」。
用法：python short_study.py            # 全部
      python short_study.py 2382 7     # 只跑單檔
      python short_study.py regime     # 只跑多空盤
輸出：results/short_*.csv、results/short_tech_study.log（run_all.sh 會接）
"""
import sys
import time

import numpy as np
import pandas as pd

from backtest import BUY_COST, RESULTS, ROOT, SELL_COST, WARMUP, load, run as run_long
from indicators import (KD_BOLLINGER_STRATEGIES, KD_MACD_STRATEGIES, KD_PV_STRATEGIES, MACD_KD_STRATEGIES,
                        SHORT_STRATEGIES, STRATEGIES, WICK_STRATEGIES, ZONE_PV_STRATEGIES, bear_alignment, sma)
from portfolio_study import UNI, load_prices, membership

SHORT_FEE = 0.0008        # 融券手續費（成交金額的 0.08%）
BORROW_RATE = 0.02        # 借券費年率
UPTICK_DROP = -0.035      # 前日跌幅達此值，隔日不得平盤下放空
FORCE_COVER_BEFORE = 5    # 除權息日前第幾個交易日為最後回補日（之後停券）
MARGIN_CALL = 0.46        # 融券保證金 90%＋賣出款 100%，維持率跌到 130% 時被斷頭：190/130 − 1 ≈ 股價漲 46%
UNIVERSE_START = pd.Timestamp("2017-01-03")

EXIT_VARIANTS = {
    "訊號回補（只有斷頭保護）": {},
    "訊號＋停損10%": {"stop": 0.10},
    "停損10%最多60日": {"stop": 0.10, "max_days": 60, "use_signal": False},
    "停利15%停損10%最多120日": {"stop": 0.10, "tp": 0.15, "max_days": 120, "use_signal": False},
    "訊號＋移動停損8%": {"trail": 0.08},
}
COLS = ["交易次數", "勝率%", "每筆期望值%", "賺賠比", "年化%", "最大回撤%", "持股時間%", "平均持有天數"]


# ---------- 訊號集合 ----------

def reversed_strategies():
    """既有多頭策略（去重）：賣出訊號 → 放空，買進訊號 → 回補。"""
    seen, out = set(), {}
    for group in (STRATEGIES, WICK_STRATEGIES, MACD_KD_STRATEGIES, KD_MACD_STRATEGIES,
                  KD_BOLLINGER_STRATEGIES, ZONE_PV_STRATEGIES, KD_PV_STRATEGIES):
        for name, fn in group.items():
            if fn in seen:
                continue
            seen.add(fn)
            out[name] = fn
    return out


def all_signals(df):
    """回傳 {策略名: (放空, 回補, 類型)}；類型＝反向／放空專用。"""
    sig = {}
    for name, fn in reversed_strategies().items():
        buy, sell = fn(df)
        sig[name] = (sell, buy, "反向")
    for name, fn in SHORT_STRATEGIES.items():
        short, cover = fn(df)
        sig[name] = (short, cover, "放空專用")
    return sig


def ex_dividend_blocks(index, ex_dates, before=FORCE_COVER_BEFORE):
    """回傳 (強制回補訊號, 停券期) 兩個布林 Series。

    最後回補日 = 除權息日前 before 個交易日；訊號放在其前一天收盤（隔天開盤回補）。
    停券期 = 最後回補日起到除權息日前一天，不能新放空。
    """
    force = pd.Series(False, index=index)
    block = pd.Series(False, index=index)
    pos = index.searchsorted(pd.DatetimeIndex(ex_dates))
    for p in pos:
        last = p - before
        if last - 1 < 0 or p > len(index):
            continue
        force.iloc[last - 1] = True
        block.iloc[max(last - 1, 0):p] = True
    return force, block


def load_ex_dates(stock_id, single=False):
    path = ROOT / "data" / f"{stock_id}_dividend_result.csv" if single else UNI / "dividend_result_all.csv"
    if not path.exists():
        return []
    r = pd.read_csv(path, dtype={"stock_id": str})
    r = r[(r["stock_id"] == stock_id) & r["stock_or_cache_dividend"].astype(str).str.contains("息|權")]
    return pd.to_datetime(r["date"]).tolist()


# ---------- 放空引擎 ----------

def run_short(df, short, cover, start, end, stop=None, tp=None, max_days=None, trail=None, use_signal=True,
              force=None, block=None, uptick=True, borrow=BORROW_RATE, flip=None, flip_gain=0.0, flip_confirm=1):
    """flip：布林 Series，True＝盤勢已轉多；轉多且放空獲利 >= flip_gain 時回補（原因「轉多有賺」）。"""
    """回傳 (交易明細, 每日權益)。權益以 1.0 起算；放空名目＝進場時權益。"""
    idx = np.flatnonzero((df.index >= start) & (df.index <= end))
    dates = df.index
    o, c = df["open"].values, df["close"].values
    short = short.reindex(dates).fillna(False).to_numpy(dtype=bool)
    cover = cover.reindex(dates).fillna(False).to_numpy(dtype=bool)
    force = force.reindex(dates).fillna(False).to_numpy(dtype=bool) if force is not None else np.zeros(len(df), bool)
    block = block.reindex(dates).fillna(False).to_numpy(dtype=bool) if block is not None else np.zeros(len(df), bool)
    flip = flip.reindex(dates).fillna(False).to_numpy(dtype=bool) if flip is not None else np.zeros(len(df), bool)
    chg = df["close"].pct_change().to_numpy()

    trades, equity = [], []
    eq, pos = 1.0, None
    for n, i in enumerate(idx):
        if n > 0:
            prev = idx[n - 1]
            if pos is None:
                ok = short[prev] and not block[i]
                if ok and uptick and chg[prev] <= UPTICK_DROP and o[i] < c[prev]:
                    ok = False  # 前日大跌，隔天只能平盤以上放空
                if ok:
                    N = eq / o[i]
                    pos = {"i0": i, "p0": o[i], "N": N, "eq0": eq, "proceeds": N * o[i] * (1 - SELL_COST - SHORT_FEE),
                           "low": c[i], "exit": None, "streak": 0}
            elif pos["exit"]:
                days = (dates[i] - dates[pos["i0"]]).days
                eq = pos["eq0"] + pos["proceeds"] - pos["N"] * o[i] * (1 + BUY_COST) - pos["N"] * pos["p0"] * borrow * days / 365
                trades.append((dates[pos["i0"]], pos["p0"], dates[i], o[i], eq / pos["eq0"] - 1, i - pos["i0"], pos["exit"],
                               pos["low"] / pos["p0"] - 1))
                eq = max(eq, 1e-9)
                pos = None
        if pos is not None:
            days = (dates[i] - dates[pos["i0"]]).days
            mark = pos["eq0"] + pos["proceeds"] - pos["N"] * c[i] * (1 + BUY_COST) - pos["N"] * pos["p0"] * borrow * days / 365
            pos["low"] = min(pos["low"], c[i])
            ret = c[i] / pos["p0"] - 1
            reason = None
            if use_signal and cover[i]:
                reason = "訊號"
            pos["streak"] = pos["streak"] + 1 if (flip[i] and -ret >= flip_gain) else 0
            if pos["streak"] >= flip_confirm:
                reason = "轉多有賺"
            if max_days is not None and i - pos["i0"] + 1 >= max_days:
                reason = "到期"
            if trail is not None and c[i] / pos["low"] - 1 >= trail:
                reason = "移動停損"
            if tp is not None and ret <= -tp:
                reason = "停利"
            if stop is not None and ret >= stop:
                reason = "停損"
            if ret >= MARGIN_CALL:
                reason = "斷頭"
            if force[i]:
                reason = "強制回補"
            pos["exit"] = reason
            equity.append(max(mark, 1e-9))
        else:
            equity.append(eq)

    if pos is not None:  # 期末以收盤強制回補
        i = idx[-1]
        days = (dates[i] - dates[pos["i0"]]).days
        eq = pos["eq0"] + pos["proceeds"] - pos["N"] * c[i] * (1 + BUY_COST) - pos["N"] * pos["p0"] * borrow * days / 365
        trades.append((dates[pos["i0"]], pos["p0"], dates[i], c[i], eq / pos["eq0"] - 1, i - pos["i0"], "期末",
                       pos["low"] / pos["p0"] - 1))
        equity[-1] = max(eq, 1e-9)

    trades = pd.DataFrame(trades, columns=["entry_date", "entry_price", "exit_date", "exit_price", "return", "bars", "reason", "mfe"])
    trades["days"] = (pd.to_datetime(trades["exit_date"]) - pd.to_datetime(trades["entry_date"])).dt.days
    return trades, pd.Series(equity, index=dates[idx])


def summarize(trades, equity):
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    r = trades["return"]
    wins, losses = r[r > 0], r[r <= 0]
    peak = equity.cummax()
    held = trades["bars"].sum()
    final = equity.iloc[-1]
    return {
        "交易次數": len(r),
        "勝率%": 100 * len(wins) / len(r) if len(r) else np.nan,
        "每筆期望值%": 100 * r.mean() if len(r) else np.nan,
        "平均獲利%": 100 * wins.mean() if len(wins) else 0.0,
        "平均虧損%": 100 * losses.mean() if len(losses) else 0.0,
        "賺賠比": wins.mean() / -losses.mean() if len(wins) and len(losses) else np.nan,
        "總報酬%": 100 * (final - 1),
        "年化%": 100 * (final ** (1 / years) - 1) if final > 1e-6 else -100.0,
        "最大回撤%": 100 * (equity / peak - 1).min(),
        "持股時間%": 100 * held / len(equity),
        "平均持有天數": trades["days"].mean() if len(r) else np.nan,
        "破產": bool((equity <= 1e-8).any()),
    }


def safe_long(df, buy, sell, start, end):
    """backtest.run 在沒有任何交易時會因空表的 .dt 出錯，這裡先檔掉。"""
    buy = buy.reindex(df.index).fillna(False).astype(bool)
    sell = sell.reindex(df.index).fillna(False).astype(bool)
    period = (df.index >= start) & (df.index <= end)
    if not buy[period].iloc[:-1].any():
        return pd.DataFrame(columns=["entry_date", "entry_price", "entry_value", "exit_date", "exit_price", "exit_value", "return", "days"])
    return run_long(df, buy, sell, start, end)[0]


def long_stats(df, buy, sell, start, end):
    """同一組訊號做多（回補訊號買、放空訊號賣）的對照。"""
    t, eq = run_long(df, buy, sell, start, end)
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    r = t["return"]
    return {"做多次數": len(r), "做多勝率%": 100 * (r > 0).mean() if len(r) else np.nan,
            "做多每筆%": 100 * r.mean() if len(r) else np.nan, "做多年化%": 100 * (eq.iloc[-1] ** (1 / years) - 1)}


def taiex_regimes(index):
    """加權指數位置，對齊到個股交易日。"""
    idx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    ma20, ma60, ma240 = sma(idx, 20), sma(idx, 60), sma(idx, 240)
    raw = {
        "大盤<MA240": idx < ma240,
        "大盤<MA60": idx < ma60,
        "大盤空頭排列": (sma(idx, 5) < ma20) & (ma20 < ma60),
        "大盤>MA240": idx >= ma240,
    }
    return {k: v.reindex(index.union(v.index)).ffill().reindex(index).fillna(False).astype(bool) for k, v in raw.items()}


def fmt(table):
    with pd.option_context("display.width", 300, "display.max_columns", 40, "display.max_rows", 500,
                           "display.unicode.east_asian_width", True):
        return table.to_string()


# ---------- 一、二：單檔 ----------

def single_stock(stock_id="2382", in_sample_years=7, log=print):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    split = df.index[0] + pd.DateOffset(years=in_sample_years)
    periods = {"樣本內": (start, split), "樣本外": (split + pd.Timedelta(days=1), df.index[-1])}
    force, block = ex_dividend_blocks(df.index, load_ex_dates(stock_id, single=True))
    sig = all_signals(df)
    log(f"【{stock_id}】樣本內 {start:%Y-%m-%d}~{split:%Y-%m-%d}，樣本外 {split:%Y-%m-%d}~{df.index[-1]:%Y-%m-%d}；"
        f"策略 {len(sig)} 個（反向 {sum(t == '反向' for *_, t in sig.values())}、放空專用 {len(SHORT_STRATEGIES)}）")

    # 1. 每個策略：放空（訊號回補，含台股限制）vs 同訊號做多
    rows, all_trades = {}, []
    for name, (short, cover, kind) in sig.items():
        for pname, (s, e) in periods.items():
            t, eq = run_short(df, short, cover, s, e, force=force, block=block)
            row = {"類型": kind, **summarize(t, eq), **long_stats(df, cover, short, s, e)}
            rows[(name, pname)] = row
            all_trades.append(t.assign(strategy=name, period=pname))
    table = pd.DataFrame(rows).T
    table.index.names = ["策略", "期間"]
    table.to_csv(RESULTS / f"short_{stock_id}_strategies.csv", encoding="utf-8-sig")
    pd.concat(all_trades).to_csv(RESULTS / f"short_{stock_id}_trades.csv", index=False, encoding="utf-8-sig")

    bh = {p: 100 * ((df.loc[s:e, "close"].iloc[-1] / df.loc[s:e, "open"].iloc[0]) ** (365.25 / max((e - s).days, 1)) - 1)
          for p, (s, e) in periods.items()}
    log(f"\n買進持有年化：樣本內 {bh['樣本內']:.1f}%、樣本外 {bh['樣本外']:.1f}%（股價長期上漲，做空是逆風）")
    view = table[["年化%", "勝率%", "交易次數", "做多年化%"]].astype(float).unstack("期間").round(1)
    view.columns = [f"{a}｜{b}" for a, b in view.columns]
    view = view[["年化%｜樣本內", "年化%｜樣本外", "勝率%｜樣本內", "勝率%｜樣本外", "交易次數｜樣本內", "交易次數｜樣本外",
                 "做多年化%｜樣本內", "做多年化%｜樣本外"]]
    view.insert(0, "類型", table["類型"].unstack("期間")["樣本內"])
    log("\n【一、放空年化%（訊號回補，含台股限制）與同訊號做多對照，依樣本內放空年化排序】\n"
        + fmt(view.sort_values("年化%｜樣本內", ascending=False)))
    pos_both = view[(view["年化%｜樣本內"] > 0) & (view["年化%｜樣本外"] > 0)]
    log(f"\n樣本內外放空都是正報酬的策略：{len(pos_both)} / {len(view)} 個 → {', '.join(pos_both.index) or '（無）'}")

    # 2. 出場變體：對放空專用策略與樣本內前 5 名反向策略
    top = view[view["類型"] == "反向"].sort_values("年化%｜樣本內", ascending=False).index[:5].tolist()
    picks = list(SHORT_STRATEGIES) + top
    rows = {}
    for name in picks:
        short, cover, kind = sig[name]
        for vname, kw in EXIT_VARIANTS.items():
            for pname, (s, e) in periods.items():
                t, eq = run_short(df, short, cover, s, e, force=force, block=block, **kw)
                rows[(name, vname, pname)] = summarize(t, eq)
    ex = pd.DataFrame(rows).T
    ex.index.names = ["策略", "出場", "期間"]
    ex.to_csv(RESULTS / f"short_{stock_id}_exits.csv", encoding="utf-8-sig")
    v2 = ex[["年化%", "勝率%", "交易次數", "最大回撤%"]].astype(float).unstack("期間").round(1)
    v2.columns = [f"{a}｜{b}" for a, b in v2.columns]
    log("\n【二、出場變體（放空專用 S 系列＋樣本內前 5 名反向策略）】\n" + fmt(v2))
    agg = ex["年化%"].astype(float).groupby(["出場", "期間"]).mean().unstack("期間").round(1)
    log("\n出場變體平均年化%（所有策略平均）：\n" + fmt(agg))

    # 3. 台股限制的影響 ＋ 借券費敏感度（S 系列，訊號回補）
    rows = {}
    for name in SHORT_STRATEGIES:
        short, cover, _ = sig[name]
        for pname, (s, e) in periods.items():
            variants = {
                "無限制、借券0%": dict(uptick=False, borrow=0.0),
                "無限制、借券2%": dict(uptick=False),
                "含平盤下禁空": dict(),
                "含禁空＋除息前強制回補": dict(force=force, block=block),
                "含禁空＋強制回補、借券4%": dict(force=force, block=block, borrow=0.04),
            }
            for vname, kw in variants.items():
                t, eq = run_short(df, short, cover, s, e, **kw)
                rows[(name, vname, pname)] = summarize(t, eq)["年化%"]
    cons = pd.Series(rows).unstack([1, 2]).astype(float).round(1)
    log("\n【三、台股限制與借券費對放空年化%的影響（S 系列）】\n" + fmt(cons))
    cons.to_csv(RESULTS / f"short_{stock_id}_constraints.csv", encoding="utf-8-sig")

    # 4. 大盤濾網（S 系列＋前 5 名反向，訊號回補）
    reg = taiex_regimes(df.index)
    rows = {}
    for name in picks:
        short, cover, _ = sig[name]
        for fname, f in {"無濾網": pd.Series(True, index=df.index), **{k: v for k, v in reg.items() if k != "大盤>MA240"}}.items():
            for pname, (s, e) in periods.items():
                t, eq = run_short(df, short & f, cover, s, e, force=force, block=block)
                rows[(name, fname, pname)] = summarize(t, eq)
    mf = pd.DataFrame(rows).T
    mf.index.names = ["策略", "大盤濾網", "期間"]
    mf.to_csv(RESULTS / f"short_{stock_id}_market_filter.csv", encoding="utf-8-sig")
    v4 = mf[["年化%", "交易次數"]].astype(float).unstack("期間").round(1)
    v4.columns = [f"{a}｜{b}" for a, b in v4.columns]
    log("\n【四、只在大盤轉弱時放空（訊號回補）】\n" + fmt(v4))
    log("\n大盤濾網平均年化%（所有策略平均）：\n"
        + fmt(mf["年化%"].astype(float).groupby(["大盤濾網", "期間"]).mean().unstack("期間").round(1)))
    return table


# ---------- 三：股票池 ----------

def universe(log=print, stop=0.10):
    t0 = time.time()
    cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
    stock_ids = sorted(set(cons["stock_id"]))
    taiex = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")
    all_dates = taiex.index[taiex.index >= pd.Timestamp("2015-01-01")]
    member = membership(cons, all_dates)
    res_all = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    res_all["date"] = pd.to_datetime(res_all["date"])
    regimes = taiex_regimes(all_dates)

    picks = {**SHORT_STRATEGIES}
    rev = reversed_strategies()
    for name in ("A2 價格站上/跌破 MA60", "A1 均線交叉 MA20/60", "C2 唐奇安 20/10", "B1 KD 低檔金叉/高檔死叉",
                 "I2 逆勢：觸下軌＋KD<30 金叉買／KD>70 死叉賣", "J3 低檔區＋(下影線或長紅)買／高檔區＋(上影線或長黑/量縮)賣",
                 "F2 ＋爆量", "D1 帶量長紅", "E1 60 日新高/20 日新低"):
        picks[name] = rev[name]
    variants = {"訊號回補（只有斷頭保護）": {}, "訊號＋停損10%": {"stop": stop}, "停損10%最多60日": {"stop": stop, "max_days": 60, "use_signal": False}}

    trades, n_used, skipped = [], 0, []
    for sid in stock_ids:
        loaded = load_prices(sid)
        if loaded is None or len(loaded[0]) < 300 or sid not in member:
            skipped.append(sid)
            continue
        df, _ = loaded
        df = df[df.index >= pd.Timestamp("2015-01-01")]
        if df.index[-1] < UNIVERSE_START + pd.Timedelta(days=200):
            skipped.append(sid)
            continue
        n_used += 1
        mem = member[sid].reindex(df.index).ffill().fillna(False).astype(bool)
        ex_dates = res_all.loc[(res_all["stock_id"] == sid) & res_all["stock_or_cache_dividend"].astype(str).str.contains("息|權"), "date"]
        force, block = ex_dividend_blocks(df.index, ex_dates.tolist())
        reg = {k: v.reindex(df.index).ffill().fillna(False).astype(bool) for k, v in regimes.items()}
        start, end = max(UNIVERSE_START, df.index[0] + pd.Timedelta(days=200)), df.index[-1]
        for name, fn in picks.items():
            kind = "放空專用" if name in SHORT_STRATEGIES else "反向"
            a, b = fn(df)
            short, cover = (a, b) if kind == "放空專用" else (b, a)
            short = short & mem
            for vname, kw in variants.items():
                t, _ = run_short(df, short, cover, start, end, force=force, block=block, **kw)
                if len(t):
                    t = t.assign(stock_id=sid, strategy=name, kind=kind, variant=vname)
                    for k, v in reg.items():
                        t[k] = v.reindex(t["entry_date"]).to_numpy()
                    trades.append(t)
            # 同訊號做多對照（只在成分股期間買）
            tl = safe_long(df, cover & mem, short, start, end)
            if len(tl):
                trades.append(pd.DataFrame({"entry_date": tl["entry_date"], "entry_price": tl["entry_price"], "exit_date": tl["exit_date"],
                                            "exit_price": tl["exit_price"], "return": tl["return"], "bars": np.nan, "reason": "訊號",
                                            "mfe": np.nan, "days": tl["days"], "stock_id": sid, "strategy": name, "kind": kind,
                                            "variant": "（同訊號做多）"}).assign(**{k: v.reindex(tl["entry_date"]).to_numpy() for k, v in reg.items()}))
    T = pd.concat(trades, ignore_index=True)
    T.to_csv(RESULTS / "short_universe_trades.csv", index=False, encoding="utf-8-sig")
    years = (all_dates[-1] - UNIVERSE_START).days / 365.25
    log(f"\n【股票池】{n_used} 檔（略過 {len(skipped)} 檔：{', '.join(skipped) or '無'}），{UNIVERSE_START:%Y-%m-%d}~{all_dates[-1]:%Y-%m-%d}"
        f"（{years:.1f} 年），{len(T):,} 筆交易，耗時 {time.time() - t0:.0f} 秒")

    def agg(g):
        r = g["return"]
        wins, losses = r[r > 0], r[r <= 0]
        return pd.Series({
            "筆數": len(r), "檔數": g["stock_id"].nunique(), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
            "每筆中位%": 100 * r.median(), "賺賠比": wins.mean() / -losses.mean() if len(wins) and len(losses) else np.nan,
            "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
            "平均天數": g["days"].mean(), "最差一筆%": 100 * r.min(),
            "每檔每年貢獻%": 100 * r.sum() / g["stock_id"].nunique() / years,
        })

    summ = T.groupby(["strategy", "variant"], sort=False).apply(agg, include_groups=False)
    summ.index.names = ["策略", "出場"]
    summ.to_csv(RESULTS / "short_universe_summary.csv", encoding="utf-8-sig")
    log("\n【五、股票池彙總：每筆期望值 ＝ 所有放空交易的平均報酬（扣成本），每檔每年貢獻 ＝ 每檔股票每年放空累積報酬】")
    for vname in list(variants) + ["（同訊號做多）"]:
        sub = summ.xs(vname, level="出場").sort_values("每筆期望值%", ascending=False).round(2)
        log(f"\n── {vname} ──\n" + fmt(sub))

    # 按大盤位置拆（訊號＋停損10%）
    sub = T[T["variant"] == "訊號＋停損10%"].copy()
    sub["大盤位置"] = np.select([sub["大盤空頭排列"], sub["大盤<MA240"]], ["空頭排列", "年線下（非空頭排列）"], "年線上")
    by_reg = sub.groupby(["strategy", "大盤位置"], sort=False).apply(agg, include_groups=False)[["筆數", "勝率%", "每筆期望值%", "獲利因子"]].round(2)
    by_reg.index.names = ["策略", "進場時大盤位置"]
    by_reg.to_csv(RESULTS / "short_universe_by_regime.csv", encoding="utf-8-sig")
    log("\n【六、進場時大盤位置 × 放空結果（訊號＋停損10%）】\n" + fmt(by_reg["每筆期望值%"].unstack("進場時大盤位置").round(2)))
    log("\n筆數：\n" + fmt(by_reg["筆數"].unstack("進場時大盤位置").astype("Int64")))
    overall = sub.groupby("大盤位置").apply(agg, include_groups=False)[["筆數", "勝率%", "每筆期望值%", "獲利因子"]].round(2)
    log("\n全部策略合計：\n" + fmt(overall))

    # 按年
    sub["年"] = sub["entry_date"].dt.year
    by_year = sub.groupby("年").apply(agg, include_groups=False)[["筆數", "勝率%", "每筆期望值%", "獲利因子"]].round(2)
    tai = taiex["close"]
    yr_ret = (tai.groupby(tai.index.year).last() / tai.groupby(tai.index.year).first() - 1) * 100
    by_year["加權指數該年%"] = yr_ret.reindex(by_year.index).round(1)
    by_year.to_csv(RESULTS / "short_universe_by_year.csv", encoding="utf-8-sig")
    log("\n【七、按進場年份（全部策略，訊號＋停損10%）】\n" + fmt(by_year))

    # 回補原因
    reason = sub.groupby("reason").apply(agg, include_groups=False)[["筆數", "勝率%", "每筆期望值%"]].round(2)
    log("\n【八、回補原因（訊號＋停損10%）】\n" + fmt(reason))
    return summ


# ---------- 四：先判多空盤，利空盤才放空，其他時間不做 ----------

def regime_defs(index):
    """加權指數的多種「空頭盤」定義，對齊到個股交易日。回傳 {名稱: 布林 Series}。"""
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")["close"]
    ma5, ma20, ma60, ma120, ma240 = (sma(tai, n) for n in (5, 20, 60, 120, 240))
    raw = {
        "R1 指數<年線": tai < ma240,
        "R2 指數<年線且年線下彎": (tai < ma240) & (ma240 < ma240.shift(20)),
        "R3 指數<季線且季線下彎": (tai < ma60) & (ma60 < ma60.shift(10)),
        "R4 空頭排列MA5<20<60": (ma5 < ma20) & (ma20 < ma60),
        "R5 季線<年線（死亡交叉後）": ma60 < ma240,
        "R6 指數<年線且空頭排列": (tai < ma240) & (ma5 < ma20) & (ma20 < ma60),
        "R7 近60日跌幅>10%": tai / tai.shift(60) - 1 < -0.10,
        "R8 自250日高點回落>15%": tai / tai.rolling(250).max() - 1 < -0.15,
        "R9 月線<季線<年線且指數<月線": (ma20 < ma60) & (ma60 < ma240) & (tai < ma20),
        "R10 指數<半年線且半年線下彎": (tai < ma120) & (ma120 < ma120.shift(20)),
    }
    return {k: v.reindex(index.union(v.index)).ffill().reindex(index).fillna(False).astype(bool) for k, v in raw.items()}, tai


def regime_study(log=print, stop=0.10):
    """每種空頭盤定義：(1) 盤勢本身對不對：期間占比、期間內指數年化、0050 在期間內放空的結果；
    (2) 只在空頭盤放空個股、多頭盤完全不做：進場要在空頭盤內，回補＝訊號 或 停損 10% 或 盤勢轉多。"""
    t0 = time.time()
    cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
    stock_ids = sorted(set(cons["stock_id"]))
    taiex = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")
    all_dates = taiex.index[taiex.index >= pd.Timestamp("2015-01-01")]
    member = membership(cons, all_dates)
    res_all = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    res_all["date"] = pd.to_datetime(res_all["date"])
    regimes, tai = regime_defs(all_dates)
    span = all_dates[all_dates >= UNIVERSE_START]
    years = (span[-1] - span[0]).days / 365.25

    # (1) 盤勢本身：期間占比、期間內指數報酬、放空 0050 的結果（盤勢成立隔天開盤空，轉多隔天開盤補）
    etf, _ = load_prices("0050")
    rows = {}
    for name, r in regimes.items():
        rs = r.reindex(span).fillna(False)
        in_days = rs.sum()
        # 指數在空頭盤期間的日報酬累計
        ret = tai.reindex(span).pct_change().fillna(0)
        idx_in = (1 + ret[rs.shift(1, fill_value=False)]).prod() - 1
        idx_out = (1 + ret[~rs.shift(1, fill_value=False)]).prod() - 1
        start_sig = rs & ~rs.shift(1, fill_value=False)
        t, eq = run_short(etf, start_sig.reindex(etf.index).fillna(False), (~rs).reindex(etf.index).fillna(False),
                          span[0], span[-1], uptick=False)
        s = summarize(t, eq)
        rows[name] = {"空頭盤占比%": 100 * in_days / len(span), "段數": int(start_sig.sum()),
                      "空頭盤期間指數累計%": 100 * idx_in, "多頭盤期間指數累計%": 100 * idx_out,
                      "放空0050筆數": s["交易次數"], "放空0050勝率%": s["勝率%"], "放空0050每筆%": s["每筆期望值%"],
                      "放空0050總報酬%": s["總報酬%"], "放空0050年化%": s["年化%"], "放空0050最大回撤%": s["最大回撤%"]}
    reg_tab = pd.DataFrame(rows).T.astype(float).round(1)
    reg_tab.to_csv(RESULTS / "short_regime_index.csv", encoding="utf-8-sig")
    log(f"\n【九、多空盤定義本身對不對（{span[0]:%Y-%m-%d}~{span[-1]:%Y-%m-%d}，{years:.1f} 年；加權指數同期累計 "
        f"{100 * (tai.reindex(span).iloc[-1] / tai.reindex(span).iloc[0] - 1):.0f}%）】\n"
        "空頭盤成立隔天開盤放空 0050、轉多隔天開盤回補，中間不看個股訊號：\n" + fmt(reg_tab))

    # (2) 個股：只在空頭盤內放空
    picks = {k: v for k, v in SHORT_STRATEGIES.items()}
    rev = reversed_strategies()
    for n in ("A2 價格站上/跌破 MA60", "C2 唐奇安 20/10", "D1 帶量長紅", "A1 均線交叉 MA20/60"):
        picks[n] = rev[n]
    trades = []
    for sid in stock_ids:
        loaded = load_prices(sid)
        if loaded is None or len(loaded[0]) < 300 or sid not in member:
            continue
        df, _ = loaded
        df = df[df.index >= pd.Timestamp("2015-01-01")]
        if df.index[-1] < UNIVERSE_START + pd.Timedelta(days=200):
            continue
        mem = member[sid].reindex(df.index).ffill().fillna(False).astype(bool)
        ex_dates = res_all.loc[(res_all["stock_id"] == sid) & res_all["stock_or_cache_dividend"].astype(str).str.contains("息|權"), "date"]
        force, block = ex_dividend_blocks(df.index, ex_dates.tolist())
        start, end = max(UNIVERSE_START, df.index[0] + pd.Timedelta(days=200)), df.index[-1]
        sigs = {}
        for name, fn in picks.items():
            a, b = fn(df)
            sigs[name] = (a, b) if name in SHORT_STRATEGIES else (b, a)
        for rname, r in regimes.items():
            rr = r.reindex(df.index).ffill().fillna(False).astype(bool)
            for name, (short, cover) in sigs.items():
                for mode in ("轉多就補", "訊號補"):
                    cv = cover | ~rr if mode == "轉多就補" else cover
                    t, _ = run_short(df, short & mem & rr, cv, start, end, stop=stop, force=force, block=block)
                    if len(t):
                        trades.append(t.assign(stock_id=sid, strategy=name, regime=rname, mode=mode))
    T = pd.concat(trades, ignore_index=True)
    T.to_csv(RESULTS / "short_regime_trades.csv", index=False, encoding="utf-8-sig")

    def agg(g):
        r = g["return"]
        wins, losses = r[r > 0], r[r <= 0]
        return pd.Series({"筆數": len(r), "勝率%": 100 * (r > 0).mean(), "每筆期望值%": 100 * r.mean(),
                          "獲利因子": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else np.nan,
                          "平均天數": g["days"].mean(), "每檔每年貢獻%": 100 * r.sum() / g["stock_id"].nunique() / years})

    summ = T.groupby(["regime", "mode", "strategy"], sort=False).apply(agg, include_groups=False)
    summ.index.names = ["空頭盤定義", "回補方式", "策略"]
    summ.to_csv(RESULTS / "short_regime_summary.csv", encoding="utf-8-sig")
    by_reg = T.groupby(["regime", "mode"], sort=False).apply(agg, include_groups=False).round(2)
    by_reg.index.names = ["空頭盤定義", "回補方式"]
    log(f"\n【十、只在空頭盤放空個股（停損 10%；{len(T):,} 筆，耗時 {time.time() - t0:.0f} 秒）：各定義合計（14 個策略）】\n" + fmt(by_reg))
    pivot = summ["每筆期望值%"].unstack("策略").round(2)
    log("\n各定義 × 策略 每筆期望值%：\n" + fmt(pivot.T))
    pos = summ[summ["每筆期望值%"] > 0].sort_values("每筆期望值%", ascending=False).round(2)
    log(f"\n正期望值的組合：{len(pos)} / {len(summ)}（筆數 >= 100 的：{int((pos['筆數'] >= 100).sum())}）\n" + fmt(pos[pos["筆數"] >= 30].head(25)))
    return reg_tab, summ


def main(argv):
    RESULTS.mkdir(exist_ok=True)
    lines = []

    def log(s=""):
        print(s)
        lines.append(str(s))

    if len(argv) > 1 and argv[1] == "regime":
        regime_study(log)
        (RESULTS / "short_regime_study.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    if len(argv) > 1:
        single_stock(argv[1], int(argv[2]) if len(argv) > 2 else 7, log)
    else:
        single_stock("2382", 7, log)
        universe(log)
        regime_study(log)
    (RESULTS / "short_tech_study.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
