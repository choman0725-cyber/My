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
from indicators import bollinger, cross_down, kd, pv_triggers, rsi, sma
from yield_entry_study import entries
from yield_study import REPORT_DEADLINE

UNI = ROOT / "data" / "universe"
MAX_SLOTS, TARGET, MIN_YIELD = 5, 0.20, 5.0
# 加碼方式同 strategy_a：首買 50%；曾跌到 -15% / -30% 後，出現爆量下影線/長紅且收盤仍低於首買價，加碼 30% / 20%
FIRST, ADDS, ADD_STEPS = 0.50, (0.30, 0.20), (-0.15, -0.30)
# 「套牢／久抱」定義（stale_free_slot、offset_only_stale 用）：持有超過 STALE_DAYS 天或虧損超過 STALE_LOSS
STALE_DAYS, STALE_LOSS = 365, -0.30
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
        y = yield_series(raw_close, dates, eps_table(eps_all, sid), dividend_events(div_all, sid, res_all))
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
            "buy": (sigs["任一"].reindex(dates).fillna(False).astype(bool) & (y >= MIN_YIELD)).values,
            "add": add.reindex(dates).fillna(False).astype(bool).values,
            "yield": y.values,
        }
    return data, skipped


def yield_series(raw_close, dates, eps, div, ffill_limit=5):
    """每日預估殖利率（%），對齊交易日曆 dates。
    價格檔缺的交易日（yfinance 沒有週六補班日等，全池約 805 個股票日）用前一個有價日的原始收盤延續，最多 5 天；
    否則那幾天殖利率算不出來，續抱規則「算不出殖利率視同 < 4.75%」會把本來該續抱的部位賣掉。
    上市前、下市後仍為 NaN。"""
    cal = dates[(dates >= raw_close.index[0]) & (dates <= raw_close.index[-1])]
    dps = forward_dividend(cal, eps, div)
    px = raw_close.reindex(cal).ffill(limit=ffill_limit)
    return (100 * dps / px).reindex(dates)


# ---------- 回測 ----------

def run(data, member, dates, idle_cash=False, one_per_day=False, cooldown=0, target_util=None,
        util_mode="committed", first=FIRST, offset_loss=False, capital=5_000_000,
        offset_frac=1.0, offset_only_stale=False, offset_only_bad=False, exit_bad=False, stale_free_slot=False,
        removal_exit=None, trap_days=None, slot_split=None, offset_only_deep=False,
        free_slot_removed=False, free_slot_deep=False, contributions=None,
        time_add_days=None, time_add_amount=0.20, target_schedule=None, max_hold_days=None,
        late_tech_days=None, offset_min_hold_days=None, need_candidate=False, exit_eps_loss=False,
        start_n=1, end_n=None, lot_mode=None, hold_yield=None, hold_yield_floor=None, hold_yield_cap=None,
        defer_breakout=None, defer_reversal=None, defer_floor=0.05, add_reserve=None,
        tech_exit=None, tech_exit_profit=False, tranches=None, ledger=None, settle=None, time_add_trap=False, trap_ref="cost",
        time_add_base="budget", deep_add_base="budget", rest=None, rest_gain=None, rest_mode="all"):
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
    offset_only_stale：只處理「持有超過 1 年」或「虧損超過 30%」的部位。
    offset_only_deep：只處理「目前虧損超過 30%」的部位（不看持有多久）。
    free_slot_removed：已被移出成分股、尚未賣出的部位不佔名額。
    free_slot_deep：目前虧損超過 30% 的部位不佔名額。
    time_add_days：持有每滿這麼多天且仍虧損，就多一次加碼機會（出現爆量下影線／長紅、收盤低於平均成本時，
      加碼單檔額度 × time_add_amount）；例如 365＝每年一次、182＝每半年一次。
    target_schedule：依持有天數調整停利門檻，例如 [(0, 0.20), (365, 0.10), (548, 0.0)]＝
      滿 1 年改賺 10% 賣、滿 1.5 年回本就賣（0.0 表示扣成本後不虧）。
    max_hold_days：持有滿這麼多天，不論賺賠，隔天開盤強制賣出。
    add_reserve：加碼讓位給新買點。None＝有現金就加；"one"＝加碼後現金仍須 ≥ 一筆首買金額；
      "near1"/"near2"＝先保留「快到買點」股票（data[sid]["near_near1/near2"]，仍在成分股、未持有，上限＝空位數）
      的首買金額，剩餘現金才可加碼；沒有快到買點的股票就不保留。
    defer_breakout / defer_reversal：停利類賣出成立時，若股價處於「突破狀態」（data[sid][defer_breakout]）就先不賣，
      等「反轉訊號」（data[sid][defer_reversal]）出現再賣；延後期間獲利回落到「門檻 − defer_floor」以下則保利賣出。
      突破／反轉陣列由 attach_fundamentals 產生：breakout_B1/B2/B3、reversal_Ra/Rb/Rc。
    hold_yield：獲利達停利門檻時，若預估殖利率仍 >= hold_yield（%）就續抱；也可傳字串，指 data[sid] 裡每日門檻陣列的鍵；殖利率跌破且獲利仍達門檻才賣。
      hold_yield_floor：曾達門檻後，獲利回落到「門檻 − floor」以下就賣（保利）；
      hold_yield_cap：獲利達 cap 就不看殖利率直接賣（封頂）。
    time_add_trap：定期加碼改成「套牢後才啟動」——收盤低於平均成本 30% 以上才開始計時（回到 -30% 以內就歸零重算），
      連續套牢每滿 time_add_days 天、出現加碼訊號且收盤低於平均成本，才多一次加碼（額度 × time_add_amount）。
    rest：長度＝dates 的布林陣列，True＝「休息期」：前一天為休息期時，隔天開盤把所有部位出清（不補、不加碼），
      休息期內不新買；休息期結束後照規則伺機重新建倉。
    rest_gain：組合自上次全面出清（或起跑）以來總資產漲幅達此比例（例如 0.5＝+50%）時，隔天開盤全部出清，
      之後立刻照規則重新建倉。
    rest_mode："all"＝休息時全部出清；"profit"＝只賣扣成本後有賺的，賠錢的留著、照常加碼，休息期內一樣不新買。
    time_add_base / deep_add_base：加碼金額的計算基準。"budget"＝進場時的額度（總資產÷5，固定不變，預設）；
      "assets"＝加碼當天的總資產÷5；"position"＝加碼當天該部位的市值。再乘上 time_add_amount 或 ADDS 的比例。
    trap_ref：套牢的比較基準，"cost"＝平均成本（預設）、"first"＝首買價。
    settle：定期結算。(months, mode)，例如 (6, "profit")＝每半年第一個交易日，把「扣成本後有賺」的部位全部賣出；
      mode "all"＝全部出清重來，"profit"＝只賣有賺的，"target"＝只賣獲利已達停利門檻的（不管殖利率）。
    ledger：傳入 list 時，每一筆成交（買進／加碼／賣出／追加資金）都記一列：日期、代號、動作、價格、股數、金額、
      成交後現金、持股檔數、持股市值與總資產（以前一日收盤計）。金額單位同 capital（1.0＝初始資金）。
    tranches：分批出場，取代停利＋hold_yield 的單一賣點。例如 [(0.5, 0.10, 5.0), (0.5, 0.20, 4.5)]＝
      獲利 >= 10% 且殖利率 < 5% 先賣一半；剩下一半獲利 >= 20% 且殖利率 < 4.5% 再賣。
      分批賣出後部位仍佔名額、仍可依原規則加碼；其他出場（EPS 轉負、移出名單等）照舊整筆出清。
    tech_exit：搭配 hold_yield 使用。殖利率已跌破 hold_yield（不再便宜）且當天出現技術賣訊
      （data[sid][tech_exit]，例如 tech_sell＝爆量上影線/爆量長黑、reversal_Rb＝跌破月線）就隔天賣出，
      不看獲利門檻；tech_exit_profit=True 時另外要求扣除賣出成本後不賠錢。停利門檻仍同時有效
      （要純技術出場就把 TARGET 設很大）。
    lot_mode：整張限制（1 張 = 1000 股，依 capital 與原始股價換算）。None＝不限制（可零股）；
      "skip"＝不足一張就放棄，夠的話無條件捨去到整張；
      "borrow"＝不足一張時借用下一次追加資金（現金可為負，下限 = 下一次追加金額），沒有未來追加則放棄。
    start_n / end_n：只在 dates[start_n]～dates[end_n] 之間交易與計算（資產曲線也只含這段），
      用來做樣本內（例如只跑前 7 年）與不同起始日的穩健度測試。
    exit_eps_loss：最近四季 EPS 合計轉負（公司虧損）時，不論賺賠隔天開盤出場（需 attach_fundamentals）。
    need_candidate：降低停利（target_schedule 中低於 TARGET 的門檻）與以盈補虧，只有在當天有其他
      「可以買的好標的」（殖利率 ≥5% ＋ 技術買點、仍在成分股、尚未持有）時才執行，換股用。
    offset_min_hold_days：以盈補虧只處理持有超過這麼多天的虧損部位。
    late_tech_days：持有滿這麼多天後，有獲利且出現價量／引線賣訊也賣。
    contributions：{日期索引 n: 追加金額（以初始資金為 1 的比例）}，當天開盤前加入現金。
    offset_only_bad：只處理「基本面變壞」的部位（最近兩季單季 EPS 都年減，或預估殖利率 < 3%）。
    exit_bad：基本面變壞且虧損的部位，不等獲利，直接全部賣出。
    stale_free_slot：虧損超過 30% 或持有超過 1 年的部位，不佔「最多 5 檔」的名額。
    slot_split：分區名額，例如 {"0050": (2, member_0050), "0056": (3, member_0056)}；
      member_x 為 {代號: numpy 布林陣列}；每區只能放該 ETF 當天的成分股，兩區都可放時優先放排在後面的區（0056）。
      設定時忽略 MAX_SLOTS 的總名額，one_per_day / cooldown 仍為全組合共用。
    trap_days：改用「套牢」定義判斷 stale（供 offset_only_stale 與 stale_free_slot 使用）——
      收盤低於平均成本 30% 以上視為套牢，連續套牢超過 trap_days 天才算；回到 -30% 以內就重新計算。
      未設定時沿用舊定義：持有超過 1 年或虧損超過 30%。
    removal_exit：被移出成分股後的伺機出場方式（不等 +20%）：
      immediate＝隔天開盤就賣；breakeven＝扣成本後不虧就賣；half_target＝獲利 10% 就賣；
      tech＝出現價量／引線賣訊（爆量長上影線、爆量長黑、價創高量縮）或回本就賣；
      tech_profit＝有獲利（扣成本後不虧）且出現價量／引線賣訊才賣，虧損時續抱（仍可等 +20% 停利）。
    使用 offset_only_bad / exit_bad / removal_exit="tech" 前須先呼叫 attach_fundamentals(data, dates)。"""
    mem = {k: v.values for k, v in member.items()}
    no = np.zeros(len(dates), bool)
    cash, positions, trades, equity, exposure = 1.0, {}, [], [], []
    last_buy_n = -10 ** 9

    raw_cache = {}

    def is_stale(sid, pos, k, price):
        if trap_days is None:
            return (dates[k] - dates[pos["start"]]).days > STALE_DAYS or price / (pos["cost"] / pos["shares"]) - 1 < STALE_LOSS
        return pos.get("trap_start") is not None and (dates[k] - pos["trap_start"]).days > trap_days

    def raw_open(sid, n):
        if sid not in raw_cache:
            raw = pd.read_csv(UNI / "prices" / f"{sid}.csv", parse_dates=["date"]).set_index("date")["open"]
            raw_cache[sid] = raw.reindex(dates).values
        return raw_cache[sid][n]

    def size(sid, n, invest):
        """依整張限制調整投入金額（占初始資金比例）。回傳 0 表示放棄。"""
        if lot_mode is None or invest <= 0:
            return max(invest, 0.0)
        ro = raw_open(sid, n)
        if not ro or np.isnan(ro):
            return invest
        lot_cost = 1000 * ro / capital
        lots = int(invest // lot_cost)
        if lots >= 1:
            return lots * lot_cost
        if lot_mode == "borrow" and contributions:
            nxt = [k for k in contributions if k > n]
            if nxt and cash + contributions[min(nxt)] >= lot_cost:
                return lot_cost
        return 0.0

    def addable_cash(n, p, value_prev, occupies):
        if add_reserve is None:
            return cash
        unit = value_prev / MAX_SLOTS * first
        free = max(MAX_SLOTS - sum(1 for s_, q in positions.items() if occupies(s_, q)), 0)
        if add_reserve == "one":
            k = 1 if free > 0 else 0
        else:
            key = "near_" + add_reserve
            k = min(free, sum(1 for s_ in data if s_ not in positions and data[s_][key][p] and mem.get(s_, no)[p]))
        return cash - k * unit

    def offset(n, profit, exclude):
        nonlocal cash
        losers = []
        for sid, pos in positions.items():
            o = data[sid]["open"][n]
            if sid in exclude or pos["adds"] < 1 or np.isnan(o):
                continue
            avg = pos["cost"] / pos["shares"]
            if offset_only_stale and not is_stale(sid, pos, n - 1, data[sid]["close_ff"][n - 1]):
                continue
            if offset_min_hold_days and (dates[n] - dates[pos["start"]]).days <= offset_min_hold_days:
                continue
            if offset_only_deep and not (o / avg - 1 < -0.30):
                continue
            if offset_only_bad and not data[sid]["bad"][n - 1]:
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

    realized = [0.0]   # 本結算期已實現損益（settle 補虧模式用）
    rest_base = [1.0]  # 上次全面出清後的總資產（rest_gain 用）
    next_settle = [dates[max(start_n, 1)] + pd.DateOffset(months=settle[0])] if settle and settle[0] > 12 else [None]

    def log(n, sid, action, price, shares_delta, amount, note=""):
        if ledger is None:
            return
        p_ = n - 1
        mv = sum(q["shares"] * data[s_]["close_ff"][p_] for s_, q in positions.items())
        ledger.append({"日期": dates[n], "代號": sid, "動作": action, "價格": price, "股數": shares_delta, "金額": amount,
                       "說明": note, "現金": cash, "持股檔數": len(positions), "持股市值": mv, "總資產": cash + mv,
                       "持股": "、".join(f"{s_}({q['shares'] * data[s_]['close_ff'][p_] / (cash + mv):.0%})" for s_, q in positions.items())})

    def close_out(sid, n, price, reason):
        nonlocal cash
        pos = positions.pop(sid)
        proceeds = pos["shares"] * price * (1 - SELL_COST)
        cash += proceeds
        realized[0] += proceeds - pos["cost"]
        log(n, sid, "賣出", price, -pos["shares"], proceeds, f"{reason}；成本 {pos['cost']:.4f}，損益 {100 * (proceeds / pos['cost'] - 1):+.1f}%")
        if offset_loss and reason == "停利":
            pending_offsets.append((proceeds - pos["cost"]) * offset_frac)
        trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": dates[n], "原因": reason, "加碼": pos["adds"],
                       "投入": pos["cost"], "回收": proceeds,
                       "被踢出": pos["removed"], "報酬%": 100 * (proceeds / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": (dates[n] - dates[pos["start"]]).days})

    end_n = len(dates) - 1 if end_n is None else end_n
    for n in range(max(start_n, 1), end_n + 1):
        p = n - 1
        if contributions and n in contributions:
            cash += contributions[n]
            rest_base[0] += contributions[n]
            log(n, "", "追加資金", np.nan, 0.0, contributions[n])
        value_prev = cash + sum(pos["shares"] * data[s_]["close_ff"][p] for s_, pos in positions.items())
        sold_today = set()
        pending_offsets = []
        def occupies(s_, q):
            if stale_free_slot and is_stale(s_, q, p, data[s_]["close_ff"][p]):
                return False
            if free_slot_removed and not mem.get(s_, no)[p]:
                return False
            if free_slot_deep and data[s_]["close_ff"][p] / (q["cost"] / q["shares"]) - 1 < -0.30:
                return False
            return True
        has_cand = (not need_candidate) or any(
            data[s_]["buy"][p] and mem.get(s_, no)[p] and s_ not in positions and not np.isnan(data[s_]["open"][n])
            for s_ in data)
        resting = rest is not None and bool(rest[p])
        if resting or (rest_gain is not None and value_prev / rest_base[0] - 1 >= rest_gain):
            for s_ in list(positions):
                o_ = data[s_]["open"][n]
                q_ = positions[s_]
                if np.isnan(o_):
                    continue
                if rest_mode == "profit" and data[s_]["close"][p] * (1 - SELL_COST) * q_["shares"] <= q_["cost"]:
                    continue
                close_out(s_, n, o_, ("休息出清" if resting else f"組合獲利達{rest_gain:.0%}出清") + ("·只賣有賺" if rest_mode == "profit" else ""))
                sold_today.add(s_)
            if not positions or rest_mode == "profit":
                rest_base[0] = value_prev if rest_mode == "profit" else cash
        settle_today = False
        if settle:
            if settle[0] <= 12:
                settle_today = (dates[n].month - 1) % settle[0] == 0 and dates[p].month != dates[n].month
            elif dates[n] >= next_settle[0]:     # 超過一年的週期：從起跑日起算
                settle_today = True
                next_settle[0] = next_settle[0] + pd.DateOffset(months=settle[0])
        if settle_today:
            if settle[1].startswith("offset"):
                # 補虧結算：先賣有賺的（offset_target 只賣達停利門檻的），再用本期累計已實現獲利去認列虧損部位，
                # 虧損由小到大（offset_big：由大到小）逐檔檢查，認列後本期合計仍 >= 0 才賣；其餘續抱。
                gains = {}
                for s_, q in positions.items():
                    o_, c_ = data[s_]["open"][n], data[s_]["close"][p]
                    if not (np.isnan(o_) or np.isnan(c_)):
                        gains[s_] = (c_ * (1 - SELL_COST) / (q["cost"] / q["shares"]) - 1, (c_ * (1 - SELL_COST) - q["cost"] / q["shares"]) * q["shares"], o_)
                win_min = TARGET if settle[1] == "offset_target" else 0.0
                for s_, (g_, pl, o_) in gains.items():
                    if g_ >= win_min:
                        close_out(s_, n, o_, f"定期結算·獲利{g_:+.0%}")
                        sold_today.add(s_)
                losers = sorted([(pl, s_, o_) for s_, (g_, pl, o_) in gains.items() if g_ < 0], reverse=(settle[1] == "offset_big"))
                for pl, s_, o_ in losers:
                    if realized[0] + pl >= 0:
                        close_out(s_, n, o_, f"定期結算·補虧{pl:+.4f}")
                        sold_today.add(s_)
            realized[0] = 0.0
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
            if settle_today and not settle[1].startswith("offset"):
                g_ = c_prev * (1 - SELL_COST) / (pos["cost"] / pos["shares"]) - 1
                if settle[1] == "all" or (settle[1] == "profit" and g_ > 0) or (settle[1] == "target" and g_ >= TARGET):
                    close_out(sid, n, o, f"定期結算({settle[0]}個月)")
                    sold_today.add(sid)
                    continue
            held = (dates[p] - dates[pos["start"]]).days
            target = TARGET
            if target_schedule:
                target = [tg for d0, tg in target_schedule if held >= d0][-1]
            gain = c_prev * (1 - SELL_COST) / (pos["cost"] / pos["shares"]) - 1 if target == 0 else \
                c_prev / (pos["cost"] / pos["shares"]) - 1
            if gain < TARGET and not has_cand:
                gain = -1  # 降低停利需要有好標的可換
            if tech_exit and hold_yield is not None and d[tech_exit][p]:
                y_ = d["yield"][p]
                if (np.isnan(y_) or y_ < hold_yield) and \
                        (not tech_exit_profit or c_prev * (1 - SELL_COST) >= pos["cost"] / pos["shares"]):
                    close_out(sid, n, o, "殖利率<門檻＋技術賣訊")
                    sold_today.add(sid)
                    continue
            if tranches:
                k = pos.get("tranche", 0)
                if k < len(tranches):
                    frac, tg, hy = tranches[k]
                    y = d["yield"][p]
                    if c_prev / (pos["cost"] / pos["shares"]) - 1 >= tg and (np.isnan(y) or y < hy):
                        if k == len(tranches) - 1:
                            close_out(sid, n, o, f"停利第{k + 1}批")
                            sold_today.add(sid)
                            continue
                        sell_frac = frac / sum(f for f, _, _ in tranches[k:])
                        sh, cost_part = pos["shares"] * sell_frac, pos["cost"] * sell_frac
                        proceeds = sh * o * (1 - SELL_COST)
                        cash += proceeds
                        trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": dates[n], "原因": f"停利第{k + 1}批",
                                       "加碼": pos["adds"], "投入": cost_part, "回收": proceeds, "被踢出": pos["removed"],
                                       "報酬%": 100 * (proceeds / cost_part - 1), "最深套牢%": 100 * (pos["low"] / pos["first"] - 1),
                                       "持有日": (dates[n] - dates[pos["start"]]).days})
                        pos["shares"] -= sh
                        pos["cost"] -= cost_part
                        pos["tranche"] = k + 1
                        log(n, sid, "賣出", o, -sh, proceeds, f"停利第{k + 1}批")
                        continue
            elif gain >= target:
                y = d["yield"][p]
                hy_ = d[hold_yield][p] if isinstance(hold_yield, str) else hold_yield   # 字串＝每檔每日不同的門檻陣列
                keep = (hold_yield is not None and not np.isnan(y) and not np.isnan(hy_) and y >= hy_
                        and not (hold_yield_cap is not None and gain >= hold_yield_cap))
                if keep:
                    pos["tp_hit"] = True
                elif defer_breakout and d[defer_breakout][p] and not d[defer_reversal][p]:
                    pos["defer"] = True          # 突破中，等反轉再賣
                else:
                    close_out(sid, n, o, ("停利" if target == TARGET else f"降低停利({target:.0%})")
                              + ("·殖利率<門檻" if pos.get("tp_hit") else "") + ("·突破後反轉" if pos.get("defer") else ""))
                    sold_today.add(sid)
                    continue
            elif pos.get("defer") and gain >= 0 and (d[defer_reversal][p] or gain < target - defer_floor):
                close_out(sid, n, o, "突破後反轉賣出" if d[defer_reversal][p] else "突破延後·保利回落")
                sold_today.add(sid)
                continue
            elif pos.get("tp_hit") and hold_yield_floor is not None and gain < target - hold_yield_floor:
                close_out(sid, n, o, "保利回落賣出")
                sold_today.add(sid)
                continue
            if late_tech_days and held >= late_tech_days and d["tech_sell"][p] \
                    and c_prev * (1 - SELL_COST) >= pos["cost"] / pos["shares"]:
                close_out(sid, n, o, "持有久＋技術賣訊")
                sold_today.add(sid)
                continue
            if exit_eps_loss and d["eps_loss"][p]:
                close_out(sid, n, o, "公司虧損出場")
                sold_today.add(sid)
                continue
            if max_hold_days and held >= max_hold_days:
                close_out(sid, n, o, "持有滿期強制出場")
                sold_today.add(sid)
                continue
            if removal_exit and not mem.get(sid, no)[p]:
                avg = pos["cost"] / pos["shares"]
                even = c_prev * (1 - SELL_COST) >= avg
                if (removal_exit == "immediate" or (removal_exit == "breakeven" and even)
                        or (removal_exit == "half_target" and c_prev / avg - 1 >= TARGET / 2)
                        or (removal_exit == "tech" and (even or d["tech_sell"][p]))
                        or (removal_exit == "tech_profit" and even and d["tech_sell"][p])):
                    close_out(sid, n, o, "移出名單出場")
                    sold_today.add(sid)
                    continue
            if exit_bad and d["bad"][p] and c_prev < pos["cost"] / pos["shares"]:
                close_out(sid, n, o, "基本面變壞出場")
                sold_today.add(sid)
                continue
            pos["removed"] |= not mem.get(sid, no)[p]
            while pos["hit"] < len(ADD_STEPS) and c_prev / pos["first"] - 1 <= ADD_STEPS[pos["hit"]]:
                pos["hit"] += 1
            avg_now = pos["cost"] / pos["shares"]
            if time_add_trap:
                t0 = pos.get("trap_start")
                due = (time_add_days and d["add"][p] and c_prev < avg_now and t0 is not None
                       and (dates[p] - t0).days // time_add_days > pos.get("trap_adds", 0))
            else:
                due = (time_add_days and d["add"][p] and c_prev < avg_now
                       and (dates[p] - dates[pos["start"]]).days // time_add_days > pos.get("time_adds", 0))
            def add_base(kind):
                if kind == "assets":
                    return value_prev / MAX_SLOTS
                if kind == "position":
                    return pos["shares"] * c_prev
                return pos["budget"]
            if due:
                invest = size(sid, n, min(addable_cash(n, p, value_prev, occupies), add_base(time_add_base) * time_add_amount))
                if invest > 0:
                    pos["shares"] += invest * (1 - BUY_COST) / o
                    pos["cost"] += invest
                    if time_add_trap:
                        pos["trap_adds"] = (dates[p] - pos["trap_start"]).days // time_add_days
                        pos["time_adds"] = pos.get("time_adds", 0) + 1
                    else:
                        pos["time_adds"] = (dates[p] - dates[pos["start"]]).days // time_add_days
                    cash -= invest
                    log(n, sid, "加碼", o, invest * (1 - BUY_COST) / o, invest, f"定期加碼第{pos['time_adds']}次（持有滿{time_add_days}天仍虧損）")
                    continue
            if pos["adds"] < pos["hit"] and d["add"][p] and c_prev < pos["first"]:
                invest = add_base(deep_add_base) * ADDS[pos["adds"]]
                if idle_cash and len(positions) >= MAX_SLOTS:
                    reserved = sum(q["budget"] * sum(ADDS[q["adds"]:]) for q in positions.values())
                    invest += max(cash - reserved, 0) / len(positions)
                invest = size(sid, n, min(addable_cash(n, p, value_prev, occupies), invest))
                if invest > 0:
                    pos["shares"] += invest * (1 - BUY_COST) / o
                    pos["cost"] += invest
                    pos["adds"] += 1
                    cash -= invest
                    log(n, sid, "加碼", o, invest * (1 - BUY_COST) / o, invest, f"跌深加碼第{pos['adds']}次（曾跌到首買價{ADD_STEPS[pos['adds'] - 1]:.0%}）")
        for profit in (pending_offsets if has_cand else []):
            before = set(positions)
            offset(n, profit, sold_today)
            sold_today |= before - set(positions)
        counted = sum(1 for s_, q in positions.items() if occupies(s_, q))
        free = MAX_SLOTS - counted
        if slot_split:
            used = {z: 0 for z in slot_split}
            for s_, q in positions.items():
                if occupies(s_, q):
                    used[q["zone"]] += 1
            zone_free = {z: cap - used[z] for z, (cap, _) in slot_split.items()}
            free = sum(max(v, 0) for v in zone_free.values())
        if resting:
            free = 0
        if one_per_day:
            free = min(free, 1) if n - last_buy_n > cooldown else 0
        if free > 0:
            cands = [(data[s_]["yield"][p], s_) for s_ in data
                     if s_ not in positions and s_ not in sold_today and data[s_]["buy"][p]
                     and mem.get(s_, no)[p] and not np.isnan(data[s_]["open"][n])]
            picked = 0
            for _, sid in sorted(cands, reverse=True):
                if picked >= free:
                    break
                zone = None
                if slot_split:
                    for z, (cap, zm) in reversed(list(slot_split.items())):
                        if zone_free[z] > 0 and sid in zm and zm[sid][p]:
                            zone = z
                            break
                    if zone is None:
                        continue
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
                invest = size(sid, n, invest)
                if invest <= 0:
                    continue
                o = data[sid]["open"][n]
                positions[sid] = {"start": n, "first": o, "shares": invest * (1 - BUY_COST) / o, "cost": invest,
                                  "budget": budget, "adds": 0, "hit": 0, "low": o, "removed": False, "zone": zone}
                cash -= invest
                log(n, sid, "買進", o, invest * (1 - BUY_COST) / o, invest, f"首買（殖利率 {data[sid]['yield'][p]:.2f}%，額度 {budget:.4f} 的 {first:.0%}）")
                last_buy_n = n
                picked += 1
                if zone:
                    zone_free[zone] -= 1
        value = cash
        for sid, pos in positions.items():
            d = data[sid]
            if not np.isnan(d["low"][n]):
                pos["low"] = min(pos["low"], d["low"][n])
            value += pos["shares"] * d["close_ff"][n]
            trapped = d["close_ff"][n] < 0.7 * (pos["first"] if trap_ref == "first" else pos["cost"] / pos["shares"])
            if trapped and pos.get("trap_start") is None:
                pos["trap_start"] = dates[n]
            elif not trapped:
                pos["trap_start"] = None
                pos["trap_adds"] = 0
        equity.append(value)
        exposure.append(1 - cash / value if value > 0 else 0.0)
    for sid, pos in positions.items():
        last = data[sid]["close_ff"][end_n]
        trades.append({"代號": sid, "進場": dates[pos["start"]], "出場": None, "原因": "持有中", "加碼": pos["adds"],
                       "投入": pos["cost"], "市值": pos["shares"] * last,
                       "被踢出": pos["removed"], "報酬%": 100 * (pos["shares"] * last * (1 - SELL_COST) / pos["cost"] - 1),
                       "最深套牢%": 100 * (pos["low"] / pos["first"] - 1), "持有日": (dates[end_n] - dates[pos["start"]]).days})
    cols = ["代號", "進場", "出場", "原因", "加碼", "被踢出", "報酬%", "最深套牢%", "持有日", "投入", "回收", "市值"]
    eq = pd.Series(equity, index=dates[max(start_n, 1):end_n + 1])
    eq.attrs["資金使用率%"] = 100 * float(np.mean(exposure))
    eq.attrs["positions"] = {sid: dict(pos) for sid, pos in positions.items()}  # 期末部位狀態（供每日執行程式用）
    eq.attrs["cash"] = cash
    return pd.DataFrame(trades, columns=cols), eq


def attach_fundamentals(data, dates):
    """在 data[sid]["bad"] 標記每日是否「基本面變壞」：最近兩季已公布的單季 EPS 都比去年同季低，或預估殖利率 < 3%。"""
    eps_all = pd.read_csv(UNI / "eps_all.csv")
    for sid, d in data.items():
        e = eps_table(eps_all, sid)
        bad = np.zeros(len(dates), bool)
        if len(e) >= 6:
            prev = e.set_index("quarter_end")["eps"]
            yoy_down = [(q - pd.DateOffset(years=1)) in prev.index and v < prev[q - pd.DateOffset(years=1)]
                        for q, v in zip(e["quarter_end"], e["eps"])]
            e = e.assign(down=yoy_down)
            e["two_down"] = e["down"] & e["down"].shift(1, fill_value=False)
            flag = pd.Series(e["two_down"].values, index=e["published"]).groupby(level=0).last()
            bad = flag.reindex(dates.union(flag.index)).ffill().reindex(dates).fillna(False).astype(bool).values
        y = d["yield"]
        d["bad"] = bad | (~np.isnan(y) & (y < 3))
        loss = np.zeros(len(dates), bool)
        if len(e) >= 4:
            ttm = pd.Series(e["eps"].rolling(4).sum().values, index=e["published"]).groupby(level=0).last()
            loss = (ttm < 0).reindex(dates.union(ttm.index)).ffill().reindex(dates).fillna(False).astype(bool).values
        d["eps_loss"] = loss
        annual = e.groupby("fy")["eps"].agg(["sum", "size"]) if len(e) else pd.DataFrame(columns=["sum", "size"])
        d["annual_eps"] = annual[annual["size"] == 4]["sum"]      # 完整四季的年度 EPS（fy → 合計），profit_years_flag 用
        px = d["df"].dropna(subset=["open", "close"])
        t = pv_triggers(px)
        d["tech_sell"] = (t["wick_sell"] | t["pv_sell"]).reindex(dates).fillna(False).astype(bool).values
        c = px["close"]
        ma10, ma20 = sma(c, 10), sma(c, 20)
        _, _, upper = bollinger(px)
        k, dd = kd(px)
        rx = lambda ser: ser.reindex(dates).fillna(False).astype(bool).values
        d["breakout_B1"] = rx(c >= c.rolling(20).max())
        d["breakout_B2"] = rx(c > upper)
        d["breakout_B3"] = rx((c > ma20) & (ma20 > ma20.shift(5)))
        ts = (t["wick_sell"] | t["pv_sell"])
        d["reversal_Ra"] = rx(ts | (c < ma10))
        d["reversal_Rb"] = rx(c < ma20)
        d["reversal_Rc"] = rx(ts | cross_down(k, dd))
        lower, _, _ = bollinger(px)
        r = rsi(c)
        y = pd.Series(d["yield"], index=dates).reindex(px.index)
        d["near_near1"] = rx((y >= 5.0) & ((k < 30) | (r < 35) | (c <= lower * 1.03)))
        d["near_near2"] = rx((y >= 4.5) & ((k < 40) | (r < 40) | (c <= lower * 1.05)))
    return data


def profit_years_flag(annual, dates, n):
    """每日布林：最近 n 個「已知完整會計年度」的年度 EPS 全部 > 0（不足 n 年以已知年度計，至少 1 年）。
    年度 EPS 在隔年 3/31（Q4 法定公布期限）後才視為已知。annual 為 attach_fundamentals 存的 d["annual_eps"]。"""
    flag = np.zeros(len(dates), bool)
    if annual is None or len(annual) == 0:
        return flag
    fys = sorted(annual.index)
    bounds = [pd.Timestamp(int(fy) + 1, 3, 31) for fy in fys]
    for i, b in enumerate(bounds):
        known = fys[: i + 1][-n:]
        ok = all(annual[fy] > 0 for fy in known)
        start = dates.searchsorted(b)
        end = dates.searchsorted(bounds[i + 1]) if i + 1 < len(bounds) else len(dates)
        flag[start:end] = ok
    return flag


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
