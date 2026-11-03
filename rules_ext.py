"""正式版 2026-10-31 新增的兩條規則的共用計算（param_opt.apply、daily_run、stock_fit 都用這裡）：

1. 成長股相對殖利率（growth_rel=(k, gmed, window)）
   某檔「過去 window 日預估殖利率中位數」（用前一日為止的資料，至少 250 日有值）在 0.5%～gmed% 之間時視為成長股，
   買進條件改為「殖利率 ≥ 自己中位 × k 且技術買點且通過 5 年賺錢」，續抱門檻改為「自己中位」；
   非成長股日子照正式版（門檻 max(市場中位數, 5%)、續抱 4.75%）。
2. 信心分級首買（conf_first=(hi, frac)）
   信心 ＝ F1 相對殖利率（殖利率 ÷ 自己 3 年中位：≥1.5 → 2、≥1.25 → 1）
        ＋ F4 大盤（加權指數收盤在 200 日線上 +1；前 5 個交易日有放量 +1；放量日帶長下影線 +1）
        ＋ F5 近 20 個交易日有急漲或急跌（單日 |漲跌| ≥ 7% 或 20 日累計 |漲跌| ≥ 15%）+1
        ＋ F6 收盤距 60 日高點 −15%～−40% +1
   信心 ≥ hi 的買點首買額度 frac（0.8），其餘用正式版 first（0.5）。不略過任何買點。
全部只用訊號日以前的資料。"""
import numpy as np
import pandas as pd

from backtest import ROOT


def own_median(yield_arr, dates, window=750, min_obs=250, stat="median"):
    """(殖利率 ÷ 自己過去 window 日中位數, 中位數) 兩個陣列；中位數用前一日為止的資料。stat="mean" 改用平均（研究用）。"""
    y = pd.Series(yield_arr, index=dates)
    r = y.rolling(window, min_periods=min(min_obs, window // 2))
    med = (r.mean() if stat == "mean" else r.median()).shift(1)
    return (y / med).values, med.values


MIN_MED = 0.5     # 自己的中位數至少 0.5%，才用相對規則（虧損年殖利率為 0 的股票中位數會趨近 0，倍數沒有意義）


def growth_relative(sub, sigmap, dates, prof, base_buy, hold_const, k=1.25, gmed=4.0, window=750, flag=None, mode="replace", group=None, second=None):
    """回傳 {sid: (buy 陣列, 續抱門檻陣列, 成長股旗標, 倍數, 自己中位)}。
    sub：{sid: 引擎資料 dict}；sigmap：{sid: 技術買點任一陣列}；prof：{sid: 5 年賺錢旗標}；base_buy：{sid: 正式版買點}。
    成長股＝自己 window 日殖利率中位數在 [MIN_MED, gmed) 之間。
    flag（2026-11-03 msci_growth_study）：{sid: bool 陣列} 外部成長股判定（MSCI 近似版）；mode "replace"＝取代殖利率中位數定義、
    "and"＝兩者都要、"or"＝任一；三種都仍要求中位數 ≥ MIN_MED（倍數才有意義）。
    group（2026-11-03 使用者「改用所有成長股平均殖利率中值 ×K」；group_yield_study）：(基準, k_buy, k_hold)。
      基準 "today"＝每天所有長期殖利率偏低股「當天預估殖利率」的橫斷面中位數；"median"＝它們「自己 750 日中位數」的橫斷面中位數。
      偏低股改用「殖利率 ≥ 群體中位 × k_buy」買、「≥ 群體中位 × k_hold」續抱（k_hold=None＝維持自己中位）；取代每檔自己的 ×k。
    second（2026-11-03 使用者更正：「偏低股照原規則；成長股改用所有成長股殖利率中值 ×K」）：(flag, k_buy, k_hold)。
      flag={sid: bool}＝成長股判定（MSCI 近似版）。偏低股照舊；**不是偏低股但是成長股**的，改用「殖利率 ≥ 當天所有成長股殖利率中位 × k_buy」買、
      「≥ 該中位 × k_hold」續抱（k_hold=None＝一般續抱門檻）；其餘股票照一般門檻。"""
    out = {}
    for sid, d in sub.items():
        ratio, med = own_median(d["yield"], dates, window)
        m_ = np.nan_to_num(med, nan=99)
        growth = (m_ < gmed) & (m_ >= MIN_MED)
        if flag is not None:
            f_ = np.asarray(flag.get(sid, np.zeros(len(dates), bool)), bool)
            growth = {"replace": f_, "and": growth & f_, "or": growth | f_}[mode] & (m_ >= MIN_MED)
        rel_buy = sigmap[sid] & (np.nan_to_num(ratio, nan=0) >= k) & prof[sid]
        buy = np.where(growth, rel_buy, base_buy[sid])
        hy = np.where(growth, med, hold_const)
        out[sid] = (buy, hy, growth, ratio, med)
    if group:
        basis, kb, kh = group
        Y = np.array([np.where(out[s_][2], sub[s_]["yield"] if basis == "today" else out[s_][4], np.nan) for s_ in out])
        with np.errstate(all="ignore"):
            gm = np.nanmedian(Y, axis=0)        # 每天偏低股群體的中位數（沒有偏低股的日子為 NaN → 不買）
        for sid, d in sub.items():
            buy, hy, growth, ratio, med = out[sid]
            y = d["yield"]
            rel_buy = sigmap[sid] & (np.nan_to_num(y / gm, nan=0) >= kb) & prof[sid]
            buy = np.where(growth, rel_buy, base_buy[sid])
            if kh is not None:
                hy = np.where(growth, gm * kh, hold_const)
            out[sid] = (buy, hy, growth, np.where(growth, y / gm, ratio), med)
    if second:
        sflag, kb, kh = second[:3]
        basis = second[3] if len(second) > 3 else "group"     # "group"＝群體中位 ×k；"abs"＝固定殖利率 k%（2026-11-03 使用者「1.5%／2%／2.5%」）
        scope = second[4] if len(second) > 4 else "nonlow"    # "nonlow"＝只套用在不是偏低股的成長股；"all"＝所有成長股（偏低股也改）
        f2 = {s_: np.asarray(sflag.get(s_, np.zeros(len(dates), bool)), bool) for s_ in sub}
        if basis == "abs":
            gm2 = np.ones(len(dates))
        else:
            Y = np.array([np.where(f2[s_], sub[s_]["yield"], np.nan) for s_ in sub])
            with np.errstate(all="ignore"):
                gm2 = np.nanmedian(Y, axis=0)        # 每天所有成長股的殖利率中位數
        for sid, d in sub.items():
            buy, hy, growth, ratio, med = out[sid]
            y = d["yield"]
            only2 = f2[sid] if scope == "all" else (f2[sid] & ~growth)
            rel2 = sigmap[sid] & (np.nan_to_num(y / gm2, nan=0) >= kb) & prof[sid]
            buy = np.where(only2, rel2, buy)
            if kh is not None:
                hy = np.where(only2, gm2 * kh, hy)
            out[sid] = (buy, hy, growth | only2, np.where(only2, y / gm2, ratio), np.where(only2, gm2, med))
    return out


def market_factor(dates, parts=False):
    """F4 大盤：200 日線上 +1、前 5 日放量 +1、放量日長下影線 +1（0～3）。parts=True 回傳三個 0/1 陣列（年線、放量、下影線）。"""
    from indicators import pv_triggers, wick_conditions
    tx = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"]).set_index("date")
    tx = tx[tx["volume"] > 0]
    above = tx["close"] > tx["close"].rolling(200).mean()
    vol_up = wick_conditions(tx)["vol_up"]
    wick = pv_triggers(tx)["wick_buy"]
    vol5 = vol_up.astype(int).rolling(5, min_periods=1).max().astype(bool)
    wick5 = wick.astype(int).rolling(5, min_periods=1).max().astype(bool)
    if parts:
        return tuple(x.astype(int).reindex(dates).fillna(0).astype(int).values for x in (above, vol5, wick5))
    return (above.astype(int) + vol5.astype(int) + wick5.astype(int)).reindex(dates).fillna(0).astype(int).values


def stock_volwick(sub, dates):
    """個股版放量／引線（定義同大盤）：前 5 日內有放量（量 > 20 日均量 1.5 倍）、有放量長下影線。回傳 {sid: (vol5, wick5)} 0/1 陣列。"""
    from indicators import pv_triggers, wick_conditions
    import portfolio_study as ps
    out = {}
    for sid in sub:
        df, _ = ps.load_prices(sid)
        v5 = wick_conditions(df)["vol_up"].astype(int).rolling(5, min_periods=1).max()
        w5 = pv_triggers(df)["wick_buy"].astype(int).rolling(5, min_periods=1).max()
        out[sid] = tuple(x.reindex(dates).fillna(0).astype(int).values for x in (v5, w5))
    return out


def confidence(sub, dates, f4=None, vw=None, mparts=None, svw=None):
    """回傳 {sid: (信心分數陣列, 因子 DataFrame)}。
    vw：F4 的放量／引線看誰（2026-11-01 研究，conf_volwick_study.py）。None／"market"＝大盤（正式版）；
      "stock"＝個股取代大盤；"stock_main"＝個股各 1 分、大盤各 0.5 分；"both"＝個股、大盤各 1 分。年線一律看大盤。
      mparts＝market_factor(parts=True)、svw＝stock_volwick() 的結果（可傳入快取）。"""
    if vw not in (None, "market"):
        mparts = mparts if mparts is not None else market_factor(dates, parts=True)
        svw = svw if svw is not None else stock_volwick(sub, dates)
        above, mv, mw = mparts
    elif f4 is None:
        f4 = market_factor(dates)
    out = {}
    for sid, d in sub.items():
        ratio, _ = own_median(d["yield"], dates, 750)
        r = np.nan_to_num(ratio, nan=0)
        f1 = np.where(r >= 1.5, 2, np.where(r >= 1.25, 1, 0))
        c = pd.Series(d["close_ff"], index=dates)
        r1 = c.pct_change(); r20 = c / c.shift(20) - 1
        up = ((r1 >= 0.07).astype(int).rolling(20, min_periods=1).max().astype(bool) | (r20 >= 0.15)).fillna(False).values
        dn = ((r1 <= -0.07).astype(int).rolling(20, min_periods=1).max().astype(bool) | (r20 <= -0.15)).fillna(False).values
        f5 = (up | dn).astype(int)
        hi60 = c.rolling(60, min_periods=20).max()
        dd = (c / hi60 - 1).values
        f6 = ((dd <= -0.15) & (dd >= -0.40)).astype(int)
        if vw not in (None, "market"):
            sv, sw = svw[sid]
            wm = {"stock": 0.0, "stock_main": 0.5, "both": 1.0}[vw]
            f4 = above + sv + sw + wm * (mv + mw)
        score = f1 + f4 + f5 + f6
        out[sid] = (score, pd.DataFrame({"F1相對殖利率": f1, "F4大盤": f4, "F5急漲跌": f5, "F6回檔60": f6}, index=dates))
    return out
