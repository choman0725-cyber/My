"""多股票組合回測：0050 ＋ 0056 歷年成分股，套用 A 版邏輯，最多同時持有 5 檔（只做多）。

選股範圍：每天只看「當天」屬於 0050 或 0056 成分股的股票（依 data/universe/constituents.csv 的生效日）。
被踢出成分股：不再新進場；已持有的部位照原邏輯加碼與出場（獲利 20% 賣出）。
單檔邏輯（同 strategy_a.py）：
  預估殖利率 >= 5%（EPS 法）＋ 技術買點任一 → 隔天開盤買進
  每檔額度 = 進場當時總資產 / 5；首次買額度的 50%；收盤曾跌到首買價 -15% / -30% 後，
  出現爆量長下影線或爆量長紅且收盤仍低於首買價，分別加碼額度的 30% / 20%
  收盤較平均成本獲利 >= 20% → 隔天開盤全部賣出；不停損
同一天有多檔訊號而空位不夠：依預估殖利率高到低挑選。
一天一檔＋冷卻期＋資金水位 80%（測試 COOLDOWNS 各種天數）：每天最多新買 1 檔（殖利率最高），
  之後 N 個交易日內不新買。水位有兩種解讀：
  解讀一（committed）：新買前先保留各檔未用的加碼額度，「已投入＋預留加碼＋新部位額度」<= 80%，
           首買為額度 50%（總資產 10%），最多 4 檔，實際投入通常遠低於 80%。
  解讀二（invested）：實際持股市值 <= 80%，首買放大為額度 80%（總資產 16%），5 檔約 80%；
           剩下 20% 現金給加碼（總資產 6% / 4%），先觸發先用、用完就不再加碼。
閒置現金加碼（idle_cash=True 時）：持股滿 5 檔時，觸發加碼的那一檔除了原本 20% 額度，
  再多投入「閒置現金 / 持有檔數」；閒置現金 = 現金 − 各檔尚未用掉的加碼額度。
預估股利（適用年配、半年配、季配）：
  - 若該股過去每年只配一次，且下一次股利已公告未除息 → 用公告值
  - 否則 = 最近四季 EPS × 近 3 個已知年度平均配息率
  年度配息率只在該年度最後一次公告、且隔年 4/1 之後才視為已知。
資料：data/universe/ 下的 constituents.csv、prices/<代號>.csv、eps_all.csv、dividend_all.csv
價格：預設用還原價（含現金股利）；PRICE_MODE=raw 用原始價。

會分別跑三種選股範圍：0050＋0056、只看 0050、只看 0056。
用法：python portfolio_study.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import BUY_COST, RAW_PRICES, RESULTS, ROOT, SELL_COST
from indicators import pv_triggers
from yield_entry_study import entries
from yield_study import REPORT_DEADLINE

UNI = ROOT / "data" / "universe"
MAX_SLOTS, TARGET, MIN_YIELD = 5, 0.20, 5.0
# 加碼方式同 strategy_a：首買 50%；曾跌到 -15% / -30% 後，出現爆量下影線/長紅且收盤仍低於首買價，加碼 30% / 20%
FIRST, ADDS, ADD_STEPS = 0.50, (0.30, 0.20), (-0.15, -0.30)
START = pd.Timestamp("2017-01-01")
COOLDOWNS = (0, 3, 5, 7, 10, 15, 20, 30)


# ---------- 資料 ----------

def load_prices(stock_id):
    path = UNI / "prices" / f"{stock_id}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    df = df[df["volume"] > 0].dropna(subset=["open", "high", "low", "close"])
    raw_close = df["close"].copy()
    if not RAW_PRICES and "adj_close" in df:
        factor = (df["adj_close"] / df["close"]).fillna(1.0)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col] * factor
    return df.drop(columns=["adj_close"], errors="ignore"), raw_close


def eps_table(eps_all, stock_id):
    e = eps_all[eps_all["stock_id"].astype(str) == stock_id][["date", "value"]].copy()
    e.columns = ["quarter_end", "eps"]
    e["quarter_end"] = pd.to_datetime(e["quarter_end"])
    e = e[e["quarter_end"].dt.month.isin(REPORT_DEADLINE)].sort_values("quarter_end").drop_duplicates("quarter_end")
    e["published"] = [pd.Timestamp(q.year + (q.month == 12), *REPORT_DEADLINE[q.month]) for q in e["quarter_end"]]
    e["fy"] = e["quarter_end"].dt.year
    return e.reset_index(drop=True)


def dividend_events(div_all, stock_id, res_all=None):
    d = div_all[div_all["stock_id"].astype(str) == stock_id].copy()
    if d.empty:
        # 股利政策缺漏：用除權息結果補（視為年配，除息日當天才得知、所屬年度 = 除息年 - 1）
        if res_all is None:
            return d
        r = res_all[(res_all["stock_id"].astype(str) == stock_id)
                    & (res_all["stock_or_cache_dividend"].astype(str).str.contains("息"))].copy()
        if r.empty:
            return pd.DataFrame(columns=["fy", "cash", "announced", "ex_date"])
        r["date"] = pd.to_datetime(r["date"])
        return pd.DataFrame({"fy": r["date"].dt.year - 1, "cash": r["stock_and_cache_dividend"],
                             "announced": r["date"], "ex_date": r["date"]}).sort_values("announced").reset_index(drop=True)
    d["cash"] = d["CashEarningsDistribution"].fillna(0) + d["CashStatutorySurplus"].fillna(0)
    d["announced"] = pd.to_datetime(d["AnnouncementDate"], errors="coerce")
    # 年度欄位為「不適用」等（多為資本公積發放）時，以公告年 - 1 視為所屬年度
    roc = pd.to_numeric(d["year"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    d["fy"] = (roc + 1911).fillna(d["announced"].dt.year - 1)
    d = d.dropna(subset=["fy"])
    d["fy"] = d["fy"].astype(int)
    d["ex_date"] = pd.to_datetime(d["CashExDividendTradingDate"], errors="coerce")
    d = d[d["cash"] > 0].dropna(subset=["announced"])
    return d[["fy", "cash", "announced", "ex_date"]].sort_values("announced").reset_index(drop=True)


def forward_dividend(dates, eps, div, payout_years=3):
    out = pd.Series(np.nan, index=dates)
    if eps.empty or div.empty:
        return out
    annual_eps = eps.groupby("fy")["eps"].agg(["sum", "size"])
    annual_eps = annual_eps[annual_eps["size"] == 4]["sum"]
    by_fy = div.groupby("fy").agg(cash=("cash", "sum"), last_ann=("announced", "max"), n=("cash", "size"))
    by_fy["payout"] = by_fy["cash"] / annual_eps.reindex(by_fy.index)
    by_fy["known_from"] = [max(a, pd.Timestamp(fy + 1, 4, 1)) for fy, a in zip(by_fy.index, by_fy["last_ann"])]
    annual_payer = (by_fy["n"] == 1).all()
    eps_pub, eps_val = eps["published"].values, eps["eps"].values
    for t in dates:
        if annual_payer:
            pending = div[(div["announced"] <= t) & (div["ex_date"] > t)]
            if len(pending):
                out[t] = pending["cash"].iloc[-1]
                continue
        k = np.searchsorted(eps_pub, np.datetime64(t), side="right")
        if k < 4:
            continue
        ttm = eps_val[k - 4:k].sum()
        known = by_fy[(by_fy["known_from"] <= t) & by_fy["payout"].notna()]["payout"].iloc[-payout_years:]
        if len(known):
            out[t] = max(ttm, 0) * known.clip(0, 2).mean()
    return out


def membership(constituents, dates):
    """回傳 {stock_id: 每日是否為 0050 或 0056 成分股} 。"""
    c = constituents.copy()
    c["effective_date"] = pd.to_datetime(c["effective_date"])
    c["stock_id"] = c["stock_id"].astype(str)
    member = {}
    for etf, g in c.groupby("etf"):
        periods = sorted(g["effective_date"].unique())
        for i, start in enumerate(periods):
            end = periods[i + 1] if i + 1 < len(periods) else pd.Timestamp.max
            mask = (dates >= start) & (dates < end)
            for sid in g[g["effective_date"] == start]["stock_id"]:
                member.setdefault(sid, np.zeros(len(dates), bool))
                member[sid] |= mask
    return {k: pd.Series(v, index=dates) for k, v in member.items()}


def prepare(stock_ids, dates):
    eps_all = pd.read_csv(UNI / "eps_all.csv")
    div_all = pd.read_csv(UNI / "dividend_all.csv")
    res_all = pd.read_csv(UNI / "dividend_result_all.csv")
    data, skipped = {}, []
    for sid in stock_ids:
        loaded = load_prices(sid)
        if loaded is None or len(loaded[0]) < 260:
            skipped.append(sid)
            continue
        df, raw_close = loaded
        dps = forward_dividend(df.index, eps_table(eps_all, sid), dividend_events(div_all, sid, res_all))
        sigs, add = entries(df)
        d = df.reindex(dates)
        last = d["close"].last_valid_index()
        # 最後交易日比資料最後一天早 10 天以上才視為下市（避免各檔資料最後更新日不同被誤判）
        delisted = last is not None and last < dates[-1] - pd.Timedelta(days=10)
        data[sid] = {
            "df": d,
            "open": d["open"].values, "close": d["close"].values, "low": d["low"].values,
            "close_ff": d["close"].ffill().values,
            "last_n": dates.get_loc(last) if delisted else len(dates) + 1,
            "buy": (sigs["任一"] & (100 * dps / raw_close >= MIN_YIELD)).reindex(dates).fillna(False).astype(bool).values,
            "add": add.reindex(dates).fillna(False).astype(bool).values,
            "yield": (100 * dps / raw_close).reindex(dates).values,
        }
    return data, skipped


# ---------- 回測 ----------

def run(data, member, dates, idle_cash=False, one_per_day=False, cooldown=0, target_util=None,
        util_mode="committed", first=FIRST, offset_loss=False, capital=5_000_000,
        offset_frac=1.0, offset_only_stale=False):
    """one_per_day：每天最多新買 1 檔；cooldown：新買後隔幾個交易日才能再新買；
    target_util 搭配 util_mode：
      committed：已投入 + 預留加碼額度 + 新部位額度 <= 總資產 × target_util（加碼額度優先保留）
      invested ：已投入股票市值 + 新部位首買金額 <= 總資產 × target_util（剩下現金給加碼，先到先用）
    first：首買占單檔額度（總資產/5）的比例。
    股票下市／合併後沒有價格：在最後交易日的隔天，以最後收盤價結算出場（原因記為「下市結算」）。
    offset_loss（以盈補虧）：某檔停利賣出時，用這筆已實現獲利，同一天開盤平掉「已加碼過且仍虧損」
      部位的整數張（1 張 = 1000 股，依 capital 與原始股價換算），平掉的虧損不超過這筆獲利；
      虧損幅度最大的先平，有剩再平下一檔。
    offset_frac：只拿獲利的這個比例去補虧（例如 0.5 = 一半）。
    offset_only_stale：只處理「持有超過 1 年」或「虧損超過 30%」的部位。"""
    mem = {k: v.values for k, v in member.items()}
    no = np.zeros(len(dates), bool)
    cash, positions, trades, equity, exposure = 1.0, {}, [], [], []
    last_buy_n = -10 ** 9

    raw_cache = {}

    def raw_open(sid, n):
        if sid not in raw_cache:
            raw = pd.read_csv(UNI / "prices" / f"{sid}.csv", parse_dates=["date"]).set_index("date")["open"]
            raw_cache[sid] = raw.reindex(dates).values
        return raw_cache[sid][n]

    def offset(n, profit, exclude):
        nonlocal cash
        losers = []
        for sid, pos in positions.items():
            o = data[sid]["open"][n]
            if sid in exclude or pos["adds"] < 1 or np.isnan(o):
                continue
            avg = pos["cost"] / pos["shares"]
            if offset_only_stale and not ((dates[n] - dates[pos["start"]]).days > 365 or o / avg - 1 < -0.30):
                continue
            if o * (1 - SELL_COST) < avg:
                losers.append((o / avg - 1, sid))
        for _, sid in sorted(losers):
            if profit <= 0:
                break
            pos, o = positions[sid], data[sid]["open"][n]
            avg = pos["cost"] / pos["shares"]
            loss_per_share = avg - o * (1 - SELL_COST)
            ro = raw_open(sid, n)
            real_per_norm = o * capital / ro if ro and not np.isnan(ro) else np.nan   # 每 1 單位模型股數 = 多少實際股
            if np.isnan(real_per_norm):
                continue
            held_lots = int(pos["shares"] * real_per_norm // 1000)
            lots = min(held_lots, int(profit / loss_per_share * real_per_norm // 1000))
            if lots <= 0:
                continue
            sell = min(pos["shares"], lots * 1000 / real_per_norm)
            if lots >= held_lots:
                sell = pos["shares"]
            proceeds = sell * o * (1 - SELL_COST)
            cost = avg * sell
            profit -= cost - proceeds
            cash += proceeds
            trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": dates[n], "原因": f"以盈補虧({lots}張)",
                           "加碼": pos["adds"], "投入": cost, "回收": proceeds, "被踢出": pos["removed"],
                           "報酬%": 100 * (proceeds / cost - 1), "最深套牢%": 100 * (pos["low"] / pos["first"] - 1),
                           "持有日": (dates[n] - dates[pos["start"]]).days})
            pos["shares"] -= sell
            pos["cost"] -= cost
            if pos["shares"] <= 1e-12:
                positions.pop(sid)

    def close_out(sid, n, price, reason):
        nonlocal cash
        pos = positions.pop(sid)
        proceeds = pos["shares"] * price * (1 - SELL_COST)
        cash += proceeds
        if offset_loss and reason == "停利":
            pending_offsets.append((proceeds - pos["cost"]) * offset_frac)
        trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": dates[n], "原因": reason, "加碼": pos["adds"],
                       "投入": pos["cost"], "回收": proceeds,
                       "被踢出": pos["removed"], "報酬%": 100 * (proceeds / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": (dates[n] - dates[pos["start"]]).days})

    for n in range(1, len(dates)):
        p = n - 1
        value_prev = cash + sum(pos["shares"] * data[s_]["close_ff"][p] for s_, pos in positions.items())
        sold_today = set()
        pending_offsets = []
        for sid in list(positions):
            if sid not in positions:
                continue
            pos, d = positions[sid], data[sid]
            if p >= d["last_n"] and n > d["last_n"]:          # 已下市
                close_out(sid, n, d["close_ff"][d["last_n"]], "下市結算")
                sold_today.add(sid)
                continue
            o, c_prev = d["open"][n], d["close"][p]
            if np.isnan(o) or np.isnan(c_prev):
                continue
            if c_prev / (pos["cost"] / pos["shares"]) - 1 >= TARGET:
                close_out(sid, n, o, "停利")
                sold_today.add(sid)
                continue
            pos["removed"] |= not mem.get(sid, no)[p]
            while pos["hit"] < len(ADD_STEPS) and c_prev / pos["first"] - 1 <= ADD_STEPS[pos["hit"]]:
                pos["hit"] += 1
            if pos["adds"] < pos["hit"] and d["add"][p] and c_prev < pos["first"]:
                invest = pos["budget"] * ADDS[pos["adds"]]
                if idle_cash and len(positions) >= MAX_SLOTS:
                    reserved = sum(q["budget"] * sum(ADDS[q["adds"]:]) for q in positions.values())
                    invest += max(cash - reserved, 0) / len(positions)
                invest = min(cash, invest)
                if invest > 0:
                    pos["shares"] += invest * (1 - BUY_COST) / o
                    pos["cost"] += invest
                    pos["adds"] += 1
                    cash -= invest
        for profit in pending_offsets:
            before = set(positions)
            offset(n, profit, sold_today)
            sold_today |= before - set(positions)
        free = MAX_SLOTS - len(positions)
        if one_per_day:
            free = min(free, 1) if n - last_buy_n > cooldown else 0
        if free > 0:
            cands = [(data[s_]["yield"][p], s_) for s_ in data
                     if s_ not in positions and s_ not in sold_today and data[s_]["buy"][p]
                     and mem.get(s_, no)[p] and not np.isnan(data[s_]["open"][n])]
            for _, sid in sorted(cands, reverse=True)[:free]:
                budget = value_prev / MAX_SLOTS
                invest = min(cash, budget * first)
                if target_util is not None and util_mode == "committed":
                    reserved = sum(q["budget"] * sum(ADDS[q["adds"]:]) for q in positions.values())
                    committed = (value_prev - cash) + reserved
                    if committed + budget > target_util * value_prev or cash - reserved < invest:
                        break
                if target_util is not None and util_mode == "invested":
                    if (value_prev - cash) + invest > target_util * value_prev + 1e-12:
                        break
                if invest <= 0:
                    break
                o = data[sid]["open"][n]
                positions[sid] = {"start": n, "first": o, "shares": invest * (1 - BUY_COST) / o, "cost": invest,
                                  "budget": budget, "adds": 0, "hit": 0, "low": o, "removed": False}
                cash -= invest
                last_buy_n = n
        value = cash
        for sid, pos in positions.items():
            d = data[sid]
            if not np.isnan(d["low"][n]):
                pos["low"] = min(pos["low"], d["low"][n])
            value += pos["shares"] * d["close_ff"][n]
        equity.append(value)
        exposure.append(1 - cash / value if value > 0 else 0.0)
    for sid, pos in positions.items():
        last = data[sid]["close_ff"][-1]
        trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": None, "原因": "持有中", "加碼": pos["adds"],
                       "投入": pos["cost"], "市值": pos["shares"] * last,
                       "被踢出": pos["removed"], "報酬%": 100 * (pos["shares"] * last * (1 - SELL_COST) / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": (dates[-1] - dates[pos["start"]]).days})
    cols = ["代號", "進場", "出場", "原因", "加碼", "被踢出", "報酬%", "最深套牢%", "持有日", "投入", "回收", "市值"]
    eq = pd.Series(equity, index=dates[1:])
    eq.attrs["資金使用率%"] = 100 * float(np.mean(exposure))
    return pd.DataFrame(trades, columns=cols), eq


def stats(equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return {"年化%": 100 * ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1),
            "總報酬%": 100 * (equity.iloc[-1] / equity.iloc[0] - 1),
            "最大回撤%": 100 * (equity / equity.cummax() - 1).min()}


def main():
    constituents = pd.read_csv(UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= START - pd.Timedelta(days=5)]).sort_values()
    universes = {"0050＋0056": ("0050", "0056"), "只看0050": ("0050",), "只看0056": ("0056",)}
    all_ids = sorted(constituents["stock_id"].unique())
    import pickle
    cache = RESULTS / "portfolio_prepared.pkl"
    if cache.exists() and cache.stat().st_mtime > max(f.stat().st_mtime for f in UNI.rglob("*.csv")) \
            and cache.stat().st_mtime > Path(__file__).stat().st_mtime:
        data, skipped = pickle.loads(cache.read_bytes())
    else:
        data, skipped = prepare(all_ids, dates)
        cache.write_bytes(pickle.dumps((data, skipped)))
    if skipped:
        print("缺資料略過：", ", ".join(skipped))

    rows, equities, all_trades = {}, {}, {}
    variants = {"原版": {}, "閒置現金加碼": {"idle_cash": True}}
    for cd in COOLDOWNS:
        variants[f"解讀一·冷卻{cd}日"] = {"one_per_day": True, "cooldown": cd, "target_util": 0.8}
        variants[f"解讀二·冷卻{cd}日"] = {"one_per_day": True, "cooldown": cd, "target_util": 0.8,
                                       "util_mode": "invested", "first": 0.8}
    runs = [(u, e, v) for u, e in universes.items() for v in variants]
    for base, etfs, vname in runs:
        member = membership(constituents[constituents["etf"].astype(str).isin(etfs)], dates)
        sub = {k: v for k, v in data.items() if k in member}
        trades, equity = run(sub, member, dates, **variants[vname])
        uname = f"{base}｜{vname}"
        closed = trades[trades["出場"].notna()]
        rows[uname] = stats(equity) | {
            "股票池": len(sub), "筆數": len(trades), "已結案": len(closed),
            "勝率%": 100 * (closed["報酬%"] > 0).mean() if len(closed) else np.nan,
            "每筆平均%": closed["報酬%"].mean(), "最差一筆%": closed["報酬%"].min(),
            "最深套牢%": trades["最深套牢%"].min(), "最長持有日": trades["持有日"].max(),
            "被踢出的部位": int(trades["被踢出"].sum()), "持有中": len(trades) - len(closed),
            "資金使用率%": equity.attrs["資金使用率%"]}
        equities[uname] = equity
        all_trades[uname] = trades
        trades.to_csv(RESULTS / f"portfolio_trades_{uname.replace('｜', '_').replace('·', '_')}.csv",
                      index=False, encoding="utf-8-sig")
    for etf in ("0050", "0056"):
        loaded = load_prices(etf)
        if loaded:
            px = loaded[0]["close"].reindex(next(iter(equities.values())).index).ffill().dropna()
            px = px / px.iloc[0]
            rows[f"{etf} 買進持有"] = stats(px)
            equities[f"{etf} 買進持有"] = px
    table = pd.DataFrame(rows).T
    RESULTS.mkdir(exist_ok=True)
    table.to_csv(RESULTS / "portfolio_summary.csv", encoding="utf-8-sig")
    curves = pd.DataFrame(equities)
    curves.to_csv(RESULTS / "portfolio_equity.csv", encoding="utf-8-sig")
    yearly = curves.groupby(curves.index.year).last().pct_change() * 100
    with pd.option_context("display.width", 250, "display.max_rows", 300, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        print("【每年報酬%】\n", yearly.round(1).to_string(), "\n")
        best = table.drop([i for i in table.index if "買進持有" in i])["年化%"].idxmax()
        print(f"【年化最高：{best} 交易明細】\n", all_trades[best].round(1).to_string(), "\n")


if __name__ == "__main__":
    main()
