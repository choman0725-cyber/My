"""用 FinMind 把 0050／0056 成分股資料庫補到 20 年前，並更新到最新交易日。

做法：每檔都用 FinMind 從 --start 抓到 --end，整段重建成同一套口徑，再與現有資料庫合併。
  - prices/<代號>.csv：
      · open/high/low/close/volume = FinMind TaiwanStockPrice 原始成交價（high/low = max/min，volume = 股數）。
      · adj_close（還原價，股利再投入）自算：
            adj_close(t) = close(t) × Π(參考價 ÷ 前一日收盤價)，乘積涵蓋 t 之後的每次
            除權息（TaiwanStockDividendResult）、減資（TaiwanStockCapitalReductionReferencePrice）、
            面額分割（TaiwanStockSplitPrice）。
        README 已用 2382 驗證此式與 Yahoo adj_close/close 到小數 4 位一致。
      · 為什麼不保留現有的 yfinance 日線：yfinance 的 close 已對「配股／分割」做過調整，不是當天真實價。
        殖利率 = 預估股利 ÷ close，配股或分割前的殖利率會被高估
        （例：6669 緯穎 2026-09 一拆三，2020-08-11 被當成殖利率 8.32% 買進，實際價約 706 元、殖利率約 2.8%）。
        FinMind 原始價可修正這點。重疊期間的差異逐檔列在 data/universe/update_report.csv。
      · FinMind 沒有任何資料的代號，保留現有檔案不動。
  - eps_all.csv、dividend_all.csv、dividend_result_all.csv：現有＋新抓的合併去重（同一筆以 FinMind 新抓的為準）。
  - prices_manifest.csv：重算來源、筆數、起訖日、SHA-256。
  - share_events_all.csv：股數變動（分割、配股、減資），引擎用來把 EPS、股利、股價換成同一股數基準再算殖利率。
  - data/TAIEX.csv（回測的交易日曆）：現有日期保留，往前補、往後接 FinMind 的 TAIEX。

股票清單 = constituents.csv（0050／0056 歷年成分股）＋ constituents_*.csv（例如 0051）＋ 0050、0056（可加 --extra 補其他代號）。

用法（需要能連到 api.finmindtrade.com；建議設 token：免費會員 600 次／小時，無 token 300 次／小時）：
    export FINMIND_TOKEN=...                 # 選用
    python update_universe_finmind.py                        # 2006-01-01 起抓到今天
    python update_universe_finmind.py --start 2006-01-01 --end 2026-10-31
    python update_universe_finmind.py --only 2330 2382 6669  # 只更新幾檔（先試跑）
    python update_universe_finmind.py --dry-run              # 只抓資料、印報告，不寫檔

約 149 × 6 + 2 × 4 + 1 ≈ 900 次請求；遇到流量限制（HTTP 402）會自動每 5 分鐘重試續抓。
原始回應快取在 data/universe/_finmind_cache/（已 gitignore），中斷後重跑會從快取接續；--refresh 忽略快取。

更新完成後（見 HANDOFF.md 第 3 節）：
    rm -f results/portfolio_prepared.pkl results/param_opt_sigs.pkl
    python portfolio_electronics.py      # 重建快取（附帶回測）
    python daily_run.py
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent
UNI = ROOT / "data" / "universe"
PRICES = UNI / "prices"
CACHE = UNI / "_finmind_cache"
VERIFY_CACHE = UNI / "_verify_cache" / "finmind"
MANUAL = UNI / "capital_reductions_manual.csv"
API = "https://api.finmindtrade.com/api/v4/data"
PRICE_COLS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
ETFS = ("0050", "0051", "0052", "0056", "00679B", "00687B", "00719B")
SOURCE = "FinMind TaiwanStockPrice + 自算 adj_close"
SPLIT_START = "2000-01-01"   # 分割資料集不帶 data_id 一次抓全市場


# ---------- FinMind ----------

class FinMind:
    def __init__(self, token=None, refresh=False, pause=0.3):
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.refresh, self.pause, self.calls = refresh, pause, 0
        self.disabled = set()

    def get(self, dataset, data_id, start, end, optional=False, cached_only=False):
        """optional=True：遇到 402（可能是付費資料集）就整個停用該資料集、回傳空表，不等待。
        cached_only=True：只讀快取，沒有就回傳空表（--local 模式用）。
        快取也讀 verify/ 腳本存的原始回應（data/universe/_verify_cache/finmind/，格式為整個回應）。"""
        if dataset in self.disabled:
            return pd.DataFrame()
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / f"{dataset}_{data_id}_{start}_{end}.json"
        if f.exists() and not self.refresh:
            return pd.DataFrame(json.loads(f.read_text(encoding="utf-8")))
        v = VERIFY_CACHE / f"{dataset}_{data_id or 'ALL'}_{start}_{end}.json"
        if v.exists() and not self.refresh:
            return pd.DataFrame(json.loads(v.read_text(encoding="utf-8"))["data"])
        if cached_only:
            return pd.DataFrame()
        params = {"dataset": dataset, "start_date": start, "end_date": end}
        if data_id:
            params["data_id"] = data_id
        waited, attempt = 0, 0
        while True:
            try:
                r = self.session.get(API, params=params, timeout=60)
            except requests.RequestException as e:
                attempt += 1
                if attempt > 5:
                    raise
                print(f"    連線錯誤（{e}），{2 ** attempt} 秒後重試")
                time.sleep(2 ** attempt)
                continue
            try:
                body = r.json()
            except ValueError:
                body = {}
            status = body.get("status", r.status_code)
            if r.status_code == 402 or status == 402:
                # 流量限制（msg 含 upper limit）也是 402：optional 資料集同樣要等，否則之後每檔都缺減資／股數 → 還原價、share_events 錯
                if optional and "upper limit" not in str(body.get("msg", "")):
                    print(f"    {dataset} 回 402（{body.get('msg', '')}），本次略過此資料集")
                    self.disabled.add(dataset)
                    return pd.DataFrame()
                if waited >= 75 * 60:
                    raise RuntimeError("等待流量限制超過 75 分鐘，請稍後重跑（已抓的會從快取接續）")
                print(f"    FinMind 流量限制（本次已抓 {self.calls} 次），5 分鐘後續抓… {body.get('msg', '')}", flush=True)
                time.sleep(300)
                waited += 300
                continue
            if r.status_code != 200 or status != 200:
                raise RuntimeError(f"{dataset} {data_id}: HTTP {r.status_code} {body.get('msg', r.text[:200])}")
            rows = body.get("data", [])
            self.calls += 1
            f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            time.sleep(self.pause)
            return pd.DataFrame(rows)


# ---------- 還原價 ----------

def _events(df, before_col, after_col):
    if df is None or df.empty or before_col not in df or after_col not in df:
        return []
    r = df[["date", before_col, after_col]].copy()
    r["date"] = pd.to_datetime(r["date"])
    r[before_col] = pd.to_numeric(r[before_col], errors="coerce")
    r[after_col] = pd.to_numeric(r[after_col], errors="coerce")
    r = r[(r[before_col] > 0) & (r[after_col] > 0)].drop_duplicates("date")
    return list(zip(r["date"], r[after_col] / r[before_col]))


def result_events(res):
    """除權息結果 → [(日期, 參考價÷除權息前收盤, 是否現增除權)]。
    現金增資除權時 FinMind 的 reference_price 等於 before_price（未調整），但 after_price 是理論除權價
    (P + 認購價×認購率)/(1+認購率)（與股利政策的認購資料核對，平均誤差 0.3%），這時改用 after_price。"""
    if res is None or res.empty:
        return []
    out = []
    for _, x in res.drop_duplicates("date").iterrows():
        b, ref, aft = (pd.to_numeric(x.get(c), errors="coerce") for c in ("before_price", "reference_price", "after_price"))
        if not (b > 0 and ref > 0):
            continue
        rights = abs(ref - b) < 1e-9 and aft > 0 and abs(aft / b - 1) > 0.0005
        out.append((pd.Timestamp(x["date"]), (aft if rights else ref) / b, rights))
    return out


def _num(x, c):
    return pd.to_numeric(x[c], errors="coerce").fillna(0) if c in x else pd.Series(0.0, index=x.index)


def policy_events(div, res, prices, skip=()):
    """股利政策有除權息日、但除權息結果沒有（±5 天）的配股／配息，用政策數字自算參考價：
    參考價 = (P − 現金股利) ÷ (1 + 配股元/10)，P＝前一交易日收盤。
    多半是上市前（上櫃、興櫃）的除權息，例：6669 2018-07-26 配股 2.02 元＋配息 4.04 元。
    不補「現增除權」：股利政策的現增日期不一定是除權交易日（例：9941 2018-09-18 依政策參考價應為 91.8，當天開盤 103，
    超過漲跌幅），現增只用除權息結果裡有的紀錄。
    skip：減資、分割日（±5 天）不補——停牌期間的除息已含在減資參考價裡（例：1513 2014-12-10）。
    回傳 [(生效日, 係數, 種類, None)]。"""
    if div is None or div.empty or "StockExDividendTradingDate" not in div or prices is None or prices.empty:
        return []
    x = div.copy()
    x["stock"] = _num(x, "StockEarningsDistribution") + _num(x, "StockStatutorySurplus")
    x["cash"] = _num(x, "CashEarningsDistribution") + _num(x, "CashStatutorySurplus")
    x["inc"] = _num(x, "TotalNumberOfCashCapitalIncrease")
    x["rate"] = _num(x, "CashIncreaseSubscriptionRate") / 100
    x["subp"] = _num(x, "CashIncreaseSubscriptionpRrice")
    x["sd"] = pd.to_datetime(x["StockExDividendTradingDate"], errors="coerce")
    x["cd"] = pd.to_datetime(x.get("CashExDividendTradingDate"), errors="coerce")
    agg = {}
    for _, r in x.iterrows():
        if pd.notna(r.sd) and (r.stock > 0 or (r.inc > 0 and r.rate > 0 and r.subp > 0)):
            a = agg.setdefault(r.sd, [0.0, 0.0, 0.0, 0.0])
            a[0] += r.stock
            if r.inc > 0 and r.rate > 0 and r.subp > 0:
                a[2] += r.rate; a[3] = r.subp
        if pd.notna(r.cd) and r.cash > 0:
            agg.setdefault(r.cd, [0.0, 0.0, 0.0, 0.0])[1] += r.cash
    rd = [] if res is None or res.empty else list(pd.to_datetime(res["date"]))
    dates, close = pd.DatetimeIndex(prices["date"]), prices["close"].values
    out = []
    for d, (st, cash, rate, subp) in sorted(agg.items()):
        if st == 0 and cash == 0:
            continue
        if any(abs((d - e).days) <= 5 for e in rd) or d <= dates[0] or d > dates[-1]:
            continue
        i = dates.searchsorted(d)                      # 生效日＝d 當天或之後第一個交易日
        if any(abs((dates[i] - e).days) <= 5 for e in skip):
            continue
        p = close[i - 1]
        ref = (p - cash) / (1 + st / 10)
        if not (0 < ref < p):
            continue
        out.append((dates[i], ref / p, "除權息（股利政策）", None))
    return out


# ---------- 已發行股數（TaiwanStockShareholding.NumberOfSharesIssued） ----------

def share_levels(sh):
    """每日已發行股數，用 11 筆滾動中位數去掉來回跳動的雜訊（例：2412 2006 年在兩個數字間來回）。"""
    if sh is None or sh.empty or "NumberOfSharesIssued" not in sh:
        return pd.Series(dtype=float)
    s = sh.assign(date=pd.to_datetime(sh["date"])).drop_duplicates("date").set_index("date")["NumberOfSharesIssued"]
    s = pd.to_numeric(s, errors="coerce")
    s = s[s > 0].sort_index()
    return s.rolling(11, center=True, min_periods=1).median()


def level_changes(lvl, tol=0.002):
    """持續的股數變動 [(變動日, 變動後÷變動前)]：滾動中位數前後差超過 tol 才算。"""
    if lvl.empty:
        return []
    r = lvl / lvl.shift(1)
    return [(d, float(v)) for d, v in r[(r - 1).abs() > tol].items()]


def shares_ratio_after(lvl, d, max_days, up=True):
    """d（含前 5 天）起 max_days 天內第一次持續變動的累積比例（同方向的連續變動合併）。沒有就回傳 None。"""
    if lvl.empty or d < lvl.index[0] or d > lvl.index[-1]:
        return None
    base = lvl[lvl.index < d - pd.Timedelta(days=5)]
    if base.empty:
        return None
    base = base.iloc[-1]
    win = lvl[(lvl.index >= d - pd.Timedelta(days=5)) & (lvl.index <= d + pd.Timedelta(days=max_days))]
    ratio = win / base
    hit = ratio[(ratio - 1 > 0.002) if up else (1 - ratio > 0.02)]
    if hit.empty:
        return None
    t = hit.index[0]
    after = lvl[(lvl.index >= t) & (lvl.index <= t + pd.Timedelta(days=30))]
    return float((after.max() if up else after.min()) / base)


def _manual_ref(m, p, share_r):
    """人工表一列 → (參考價, 股數比例, 備註)。現金減資沒寫退還金額時用面額：10 ×(1 − 股數比例)。"""
    if pd.notna(m.get("share_ratio")):
        # 有官方比例就用官方比例：已發行股數可能同時反映減資後的現增（例：2408 2009 股數只少 45%，官方減資 66.4%）
        share_r = float(m["share_ratio"])
    if pd.notna(m.get("ref_price")):
        ref = float(m["ref_price"])
        share_r = float(m["share_ratio"]) if pd.notna(m.get("share_ratio")) else p / ref
    else:
        if share_r is None:
            return None
        cash = float(m["cash_per_share"]) if pd.notna(m.get("cash_per_share")) else \
            (10 * (1 - share_r) if "現金" in str(m["type"]) else 0.0)
        ref = (p - cash) / share_r
    return ref, share_r, f"{m['type']}；{m['source']}"


def halt_gaps(prices, market_days, min_days=3):
    """個股停牌：前後兩個交易日之間，大盤（TAIEX）有 ≥ min_days 個交易日（排除春節等全市場休市）。
    回傳 [(恢復交易日, 停牌前收盤)]。"""
    dates, close = pd.DatetimeIndex(prices["date"]), prices["close"].values
    md = pd.DatetimeIndex(market_days)
    out = []
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days < 5:
            continue
        n = md.searchsorted(dates[i]) - md.searchsorted(dates[i - 1], side="right")
        if n >= min_days:
            out.append((dates[i], close[i - 1]))
    return out


def _guess_type(prices, t, p, r):
    """人工表沒有的減資：看「彌補虧損」(P÷r) 或「現金減資」((P − 10(1−r))÷r) 哪個參考價能讓恢復日開盤落在漲跌幅內
    （2015-06-01 前 ±7%、之後 ±10%，各加 0.5% 容差）；都能就取較接近的；都不能代表已發行股數失真
    （例如同期私募、現增），改以恢復日開盤當參考價。回傳 (股數比例, 參考價, 備註)。"""
    o = float(prices.loc[prices["date"] == t, "open"].iloc[0])
    lim = (0.07 if t < pd.Timestamp("2015-06-01") else 0.10) + 0.005
    cands = [("彌補虧損", p / r), ("現金減資", (p - 10 * (1 - r)) / r)]
    fit = [(abs(o / ref - 1), kind, ref) for kind, ref in cands if ref > 0 and abs(o / ref - 1) <= lim]
    if fit:
        _, kind, ref = min(fit)
        return r, ref, f"類型未查證，依開盤推定為{kind}"
    return p / o, o, f"類型未查證，已發行股數比例 {r:.4f} 與開盤不符（可能同時私募／現增），以恢復日開盤當參考價"


def unlisted_reductions(lvl, prices, known, manual, sid, market_days):
    """FinMind 減資資料集（2011-01 起）沒有的減資。
    1. 已發行股數（FinMind TaiwanStockShareholding）持續減少 >2%，且 ±20 天內有停牌 ≥7 天 → 減資；
       股數比例＝已發行股數前後比，恢復交易日＝最接近的停牌後第一天。
       沒有停牌的股數減少（例如庫藏股註銷）不影響股價，不調整。
    2. 類型、退還現金、官方股數比例查不到 FinMind 資料，用 capital_reductions_manual.csv（附來源；有官方比例時以官方為準）；
       表裡沒有的視為彌補虧損（不退現金），備註「類型未查證」。
    3. 人工表有、但已發行股數查不到的（例如 2633 高鐵減資時是興櫃，沒有已發行股數資料），用表裡的股數比例。
    參考價＝(停牌前收盤 − 每股退還現金) ÷ 股數比例；價格係數＝參考價 ÷ 停牌前收盤。
    回傳 [(恢復交易日, 價格係數, 股數比例, 備註)]。"""
    if prices.empty:
        return []
    dates, close = pd.DatetimeIndex(prices["date"]), prices["close"].values
    gaps = halt_gaps(prices, market_days)
    man = manual[manual["stock_id"] == sid] if manual is not None else pd.DataFrame()
    out, used = [], set()
    for c, step in level_changes(lvl, 0.02):
        if step >= 1:
            continue
        g = [(t, p) for t, p in gaps if -20 <= (t - c).days <= 20 and t not in used]
        if not g:
            continue
        t, p = min(g, key=lambda z: abs((z[0] - c).days))
        if any(abs((t - e).days) <= 20 for e in known):
            continue
        r = shares_ratio_after(lvl, t, 40, up=False)
        if r is None or r > 0.98:
            continue
        used.add(t)
        m = man[(pd.to_datetime(man["date"]) - t).abs() <= pd.Timedelta(days=5)] if len(man) else man
        got = _manual_ref(m.iloc[0], p, r) if len(m) else None
        if got:
            ref, share_r, note = got
        else:
            share_r, ref, note = _guess_type(prices, t, p, r)
        out.append((t, ref / p, share_r, note))
    for _, m in man.iterrows():
        t = pd.Timestamp(m["date"])
        if any(abs((t - u).days) <= 5 for u in used) or t <= dates[0] or t > dates[-1]:
            continue
        i = dates.searchsorted(t)
        got = _manual_ref(m, close[i - 1], None)
        if got is None:
            continue
        ref, share_r, note = got
        out.append((dates[i], ref / close[i - 1], share_r, note + "（已發行股數未偵測到，用表列比例）"))
    return sorted(out)


def adjust_events(div_result, reduction=None, split=None, extra=()):
    """[(生效日, 係數)]：生效日之前的價格要乘上係數。同一事件若在兩個資料集都出現（±5 天、係數差 <1%）只算一次。"""
    events = [(d, k) for d, k, _ in result_events(div_result)]
    more = (_events(reduction, "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice")
            + _events(split, "before_price", "after_price") + list(extra))
    for d, k in more:
        if not any(abs((d - d0).days) <= 5 and abs(k / k0 - 1) < 0.01 for d0, k0 in events):
            events.append((d, k))
    return sorted(events)


def cum_factor(dates, events):
    """每個日期 t 的 Π(係數, 生效日 > t)。"""
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    out = pd.Series(1.0, index=idx)
    for d, k in events:
        out[idx < d] *= k
    return out.values


def reduction_share_ratios(reduction, div=None, prices=None):
    """FinMind 減資資料集 → [(日期, 股數比例)]。彌補虧損：減資前收盤 ÷ 減資後參考價。
    現金退還（每股退面額 10 元 ×減資比例）：參考價 R = (C − 10(1−r)) ÷ r → r = (C − 10) ÷ (R − 10)。
    例：2412 2011-01-25 C=73.10、R=88.87 → 0.8001（官方減資 20%）；只用價格比會得到 0.8226。
    停牌期間若有除息，證交所的參考價已先扣掉現金股利 D：r = (C − D − 10) ÷ (R − 10)
    （例：1513 2014-12-10 → 0.8756，FinMind 已發行股數實際 0.8750；不扣 D 會得到 0.9552）。"""
    if reduction is None or reduction.empty:
        return []
    halt_cash = {}
    if div is not None and not div.empty and "CashExDividendTradingDate" in div and prices is not None and len(prices):
        dates = pd.DatetimeIndex(prices["date"])
        cd = pd.to_datetime(div["CashExDividendTradingDate"], errors="coerce")
        cash = _num(div, "CashEarningsDistribution") + _num(div, "CashStatutorySurplus")
        for d in pd.to_datetime(reduction["date"]):
            i = dates.searchsorted(d)
            if 0 < i <= len(dates):
                halt_cash[d] = float(cash[(cd > dates[i - 1]) & (cd <= d)].sum())
    out = []
    for _, x in reduction.drop_duplicates("date").iterrows():
        c = pd.to_numeric(x.get("ClosingPriceonTheLastTradingDay"), errors="coerce")
        r = pd.to_numeric(x.get("PostReductionReferencePrice"), errors="coerce")
        if not (c > 0 and r > 0):
            continue
        cash = "cash" in str(x.get("ReasonforCapitalReduction", "")).lower()
        d = pd.Timestamp(x["date"]); dv = halt_cash.get(d, 0.0)
        out.append((d, (c - dv - 10) / (r - 10) if cash and r > 10 and c - dv > 10 else (c - dv) / r))
    return out


def share_events(sid, div, res, reduction, split, extra=(), lvl=None, log=None, prices=None):
    """股數變動紀錄 [(stock_id, 日期, 種類, 變動後股數 ÷ 變動前股數)]，給殖利率換算同一股數基準用。
    配股：1 + (盈餘配股＋公積配股) ÷ 10（面額 10 元），日期＝除權交易日。
    股利政策缺漏時：
      · 除權息結果「權」（只有權）：除權前價 ÷ 參考價（現增除權用理論除權價，見 result_events）。
      · 除權息結果「權息」（配股＋配息，常見於 FinMind 缺 2009 年股利政策）：無法從價格分開股、息，
        改用 FinMind 已發行股數（TaiwanStockShareholding）在除權日後 80 天內的增加比例。
    分割：分割前價 ÷ 分割後價；減資：見 reduction_share_ratios；extra：其他來源已算好的 [(日期, 種類, 比例)]。
    同一事件出現在兩個來源（±5 天、比例差 <1%）只記一次。"""
    ev = []
    log = log if log is not None else []
    if div is not None and not div.empty and "StockExDividendTradingDate" in div:
        x = div.copy()
        x["stock"] = _num(x, "StockEarningsDistribution") + _num(x, "StockStatutorySurplus")
        x["d"] = pd.to_datetime(x["StockExDividendTradingDate"], errors="coerce")
        for d, st in zip(x["d"], x["stock"]):
            if pd.notna(d) and st > 0:
                ev.append((d, "配股", 1 + st / 10))
    if res is not None and not res.empty:
        kinds = res.drop_duplicates("date").set_index(pd.to_datetime(res.drop_duplicates("date")["date"]))["stock_or_cache_dividend"].astype(str)
        for d, k, rights in result_events(res):
            kd = kinds.get(d, "")
            if "權" not in kd or any(abs((d - d0).days) <= 5 for d0, kind0, _ in ev if kind0 == "配股"):
                continue
            if kd in ("權", "除權") or rights:
                ev.append((d, "現增除權（除權結果）" if rights else "配股或分割（除權結果）", 1 / k))
            else:                                           # 權息
                cash = 0.0
                if div is not None and not div.empty and "CashExDividendTradingDate" in div:
                    cd = pd.to_datetime(div["CashExDividendTradingDate"], errors="coerce")
                    near = (cd - d).abs() <= pd.Timedelta(days=5)
                    cash = float((_num(div, "CashEarningsDistribution") + _num(div, "CashStatutorySurplus"))[near].sum())
                if cash > 0:                                # 有配息紀錄：(除權前價 − 現金) ÷ 參考價 ＝ 配股（或同日現增）的比例
                    b = float(res.loc[pd.to_datetime(res["date"]) == d, "before_price"].iloc[0])
                    r = (b - cash) / (k * b)
                    if r > 1.002:
                        ev.append((d, "配股或現增（除權結果扣配息）", r))
                    continue
                r = shares_ratio_after(lvl, d, 80, up=True) if lvl is not None else None   # 無配息紀錄：用已發行股數
                if r is not None and 1.002 < r < 1 / k + 0.02:
                    ev.append((d, "配股（已發行股數推算）", r))
                else:
                    log.append(f"{sid} {d:%Y-%m-%d} 權息但股利政策無配股、已發行股數也推不出比例（{r}），未記")
    for kind, lst in (("分割", [(d, 1 / k) for d, k in _events(split, "before_price", "after_price")]),
                      ("減資", reduction_share_ratios(reduction, div, prices))):
        for d, ratio in lst:
            if not any(abs((d - d0).days) <= 5 and abs(ratio / r0 - 1) < 0.01 for d0, _, r0 in ev):
                ev.append((d, kind, ratio))
    for d, kind, ratio in extra:
        if not any(abs((d - d0).days) <= 5 and abs(ratio / r0 - 1) < 0.01 for d0, _, r0 in ev):
            ev.append((d, kind, ratio))
    return [(sid, f"{d:%Y-%m-%d}", kind, round(ratio, 6)) for d, kind, ratio in sorted(ev) if abs(ratio - 1) > 0.001]


def finmind_price_frame(raw):
    cols = ["date", "open", "high", "low", "close", "volume"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    df = raw.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[cols]
    df = df[(df["volume"] > 0) & (df["close"] > 0)].drop_duplicates("date").sort_values("date").reset_index(drop=True)
    # 資料錯誤 1：開高低為 0（例：2633 2015-12-25 開盤 0）→ 用收盤價代替
    for c in ("open", "high", "low"):
        df.loc[df[c] <= 0, c] = df["close"]
    # 資料錯誤 2：單日腰斬／翻倍、隔天又回到原水準（例：8454 2014-09-09 收盤 3.43）→ 刪除該日
    prev, nxt = df["close"].shift(1), df["close"].shift(-1)
    spike = ((df["close"] / prev < 0.5) | (df["close"] / prev > 2)) & ((nxt / prev - 1).abs() < 0.15)
    return df[~spike].reset_index(drop=True)


def unexplained_jumps(df, events, gap_days=7, jump=0.11):
    """只做檢查、不調整：停牌 ≥ gap_days 天後恢復交易、開盤比停牌前收盤高 > jump，且 ±10 天內沒有任何已知事件。
    （舊版把這些直接當成減資，比例用漲停開盤近似、系統性偏差 5～7%，還誤判 3665、5880 兩筆掛牌前資料；
    現在減資改由 FinMind 已發行股數判斷，見 unlisted_reductions。）"""
    out = []
    d = df["date"].reset_index(drop=True)
    for i in range(1, len(df)):
        if (d[i] - d[i - 1]).days < gap_days:
            continue
        k = df["open"].iloc[i] / df["close"].iloc[i - 1]
        if k - 1 > jump and not any(abs((d[i] - e).days) <= 10 for e, _ in events):
            out.append((d[i], k))
    return out


def build_prices(new, events):
    out = new.copy()
    out["adj_close"] = out["close"] * cum_factor(out["date"], events)
    out = out[PRICE_COLS].sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "adj_close"):
        out[c] = out[c].astype(float).round(4)
    out["volume"] = out["volume"].astype("int64")
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


def compare(old, new):
    """現有 vs 新檔在重疊日期的差異：收盤價、還原日報酬。"""
    if old is None or old.empty:
        return {}
    o = old.assign(date=pd.to_datetime(old["date"])).set_index("date")
    n = new.assign(date=pd.to_datetime(new["date"])).set_index("date")
    j = o.join(n, how="inner", lsuffix="_old")
    if j.empty:
        return {"overlap_days": 0}
    cdiff = (j["close_old"] / j["close"] - 1).abs()
    rdiff = (j["adj_close_old"].pct_change() - j["adj_close"].pct_change()).abs()
    return {"overlap_days": len(j),
            "old_only_days": int((~o.index.isin(n.index)).sum()),
            "close_diff_days": int((cdiff > 0.005).sum()),
            "close_diff_max": round(float(cdiff.max()), 4),
            "adj_return_diff_max": round(float(rdiff.max()), 4)}


def merge_table(path, new, keys):
    old = pd.read_csv(path, dtype={"stock_id": str}) if path.exists() else pd.DataFrame()
    if new is None or new.empty:
        return old
    new = new.copy()
    new["stock_id"] = new["stock_id"].astype(str)
    cols = list(old.columns) if not old.empty else list(new.columns)
    for c in cols:
        if c not in new:
            new[c] = pd.NA
    out = pd.concat([old, new[cols]], ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    for k in keys:
        out[k] = out[k].astype(str)
    out = out.drop_duplicates(keys, keep="last").sort_values(["stock_id", "date"]).reset_index(drop=True)
    return out


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- 主程式 ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--token", default=os.environ.get("FINMIND_TOKEN"))
    ap.add_argument("--only", nargs="*", help="只更新這些代號")
    ap.add_argument("--extra", nargs="*", default=[], help="額外加入的代號（例如 2006–2015 的舊成分股）")
    ap.add_argument("--refresh", action="store_true", help="忽略快取重抓")
    ap.add_argument("--dry-run", action="store_true", help="不寫檔，只印報告")
    ap.add_argument("--skip-taiex", action="store_true")
    ap.add_argument("--local", action="store_true",
                    help="不重抓日線、財報、股利：用現有 prices/*.csv 的 OHLCV 與 *_all.csv（皆為 FinMind 原始資料），"
                         "只抓已發行股數（並讀快取裡的減資、分割），重算 adj_close 與 share_events_all.csv")
    a = ap.parse_args()

    cons = pd.read_csv(UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    # 其他 ETF 的成分股（例如 constituents_0051.csv）也一起抓；這些檔不影響正式版（正式版只讀 constituents.csv）
    extra_cons = [pd.read_csv(f, dtype={"stock_id": str, "etf": str}) for f in sorted(UNI.glob("constituents_*.csv"))]
    if extra_cons:
        cons = pd.concat([cons] + extra_cons, ignore_index=True)
    names = cons.drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    names.update({"0050": "元大台灣50", "0051": "元大中型100", "0052": "富邦科技", "0056": "元大高股息",
                  "00679B": "元大美債20年", "00687B": "國泰20年美債", "00719B": "元大美債1-3"})
    ids = list(ETFS) + sorted(cons["stock_id"].unique()) + [s for s in a.extra if s not in names]
    if a.only:
        ids = [s for s in ids if s in set(a.only)] + [s for s in a.only if s not in ids]
    if not a.token:
        a.token = os.environ.get("KEY")
    print(f"FinMind 更新：{len(ids)} 檔，{a.start} ~ {a.end}，token {'有' if a.token else '無（300 次／小時）'}"
          f"{'，--local（只重算還原價與股數變動）' if a.local else ''}")

    fm = FinMind(a.token, a.refresh)
    manifest_path = UNI / "prices_manifest.csv"
    old_manifest = pd.read_csv(manifest_path, dtype=str).set_index("stock_id") if manifest_path.exists() else None
    res_hist = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    eps_new, div_new, res_new, report, updated, share_rows = [], [], [], [], set(), []

    manual = pd.read_csv(MANUAL, dtype={"stock_id": str}) if MANUAL.exists() else None
    split_all = fm.get("TaiwanStockSplitPrice", "", SPLIT_START, a.end, optional=True)   # 1 次請求，ETF 也會分割（0050 2025-06 一拆四）
    if a.local:
        eps_hist = pd.read_csv(UNI / "eps_all.csv", dtype={"stock_id": str})
        div_hist = pd.read_csv(UNI / "dividend_all.csv", dtype={"stock_id": str})
        a.skip_taiex = True
    warn_log = []
    market_days = pd.read_csv(ROOT / "data" / "TAIEX.csv", usecols=["date"], parse_dates=["date"])["date"]

    for i, sid in enumerate(ids, 1):
        reduction = div = None
        lvl = pd.Series(dtype=float)
        if a.local:
            path = PRICES / f"{sid}.csv"
            if not path.exists():
                continue
            raw = None
            res = pd.DataFrame()
            if sid not in ETFS:
                div = div_hist[div_hist["stock_id"] == sid]
                reduction = fm.get("TaiwanStockCapitalReductionReferencePrice", sid, a.start, a.end, cached_only=True)
        else:
            raw = fm.get("TaiwanStockPrice", sid, a.start, a.end)
            res = fm.get("TaiwanStockDividendResult", sid, a.start, a.end)
            if sid not in ETFS:
                fin = fm.get("TaiwanStockFinancialStatements", sid, a.start, a.end)
                if not fin.empty:
                    eps_new.append(fin[fin["type"] == "EPS"][["stock_id", "date", "value"]])
                div = fm.get("TaiwanStockDividend", sid, a.start, a.end)
                if not div.empty:
                    div_new.append(div)
                reduction = fm.get("TaiwanStockCapitalReductionReferencePrice", sid, a.start, a.end, optional=True)
            if not res.empty:
                res_new.append(res)
        if sid not in ETFS:
            lvl = share_levels(fm.get("TaiwanStockShareholding", sid, a.start, a.end, optional=True))
        split = split_all[split_all["stock_id"] == sid] if not split_all.empty else split_all

        # 還原係數：新抓的＋既有的除權息結果（避免 FinMind 某次缺漏），再加減資、分割
        res_all = pd.concat([res_hist[res_hist["stock_id"] == sid], res], ignore_index=True)
        events = adjust_events(res_all, reduction, split)

        path = PRICES / f"{sid}.csv"
        old = pd.read_csv(path) if path.exists() else None
        new = finmind_price_frame(raw) if not a.local else \
            old.drop(columns="adj_close").assign(date=pd.to_datetime(old["date"]))
        label = f"  [{i}/{len(ids)}] {sid} {names.get(sid, '')}"
        if new.empty:
            print(f"{label}：FinMind 沒有日線，{'保留現有檔案' if old is not None else '略過'}")
            continue
        # 股利政策有、除權息結果沒有的除權息／現增除權（多半在上市前）
        known = [d for d, _ in _events(reduction, "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice")
                 + _events(split, "before_price", "after_price")]
        pol = policy_events(div, res_all, new, known)
        # FinMind 減資資料集沒有的減資（2011-01 以前）：已發行股數減少＋停牌
        unl = unlisted_reductions(lvl, new, known + [d for d, *_ in pol], manual, sid, market_days)
        events = adjust_events(res_all, reduction, split, [(d, k) for d, k, *_ in pol] + [(d, k) for d, k, *_ in unl])
        extra = [(d, kind, r) for d, k, kind, r in pol if r is not None] + [(d, "減資（2011 前，見 capital_reductions_manual.csv）" if "未查證" not in note else ("減資（以開盤推估，比例未查證）" if "開盤當參考價" in note else "減資（已發行股數推算，類型未查證）"), r)
                                                                for d, k, r, note in unl]
        share_rows += share_events(sid, div if sid not in ETFS else None, res_all, reduction, split, extra, lvl, warn_log, new)
        for d, k, r, note in unl:
            if "未查證" in note:
                warn_log.append(f"{sid} {d:%Y-%m-%d} 減資 {note}；股數比例 {r:.4f}")
        for d, k, r, note in unl:                       # 參考價合理性：恢復日開盤應在參考價 ±10% 內
            j = new.index[new["date"] == d]
            if len(j) and j[0] > 0:
                ref = new["close"].iloc[j[0] - 1] * k
                if abs(new["open"].iloc[j[0]] / ref - 1) > 0.105:
                    warn_log.append(f"{sid} {d:%Y-%m-%d} 減資參考價 {ref:.2f} 與恢復日開盤 {new['open'].iloc[j[0]]} 差超過 10%（{note}）")
        for d, k in unexplained_jumps(new, events):
            warn_log.append(f"{sid} {d:%Y-%m-%d} 停牌後開盤跳 {k - 1:+.1%}，±10 天內沒有已知事件（未調整）")
        built = build_prices(new, events)
        diff = compare(old, built)
        report.append({"stock_id": sid, "name": names.get(sid, ""), "old_rows": 0 if old is None else len(old),
                       "rows": len(built), "first_date": built["date"].iloc[0], "last_date": built["date"].iloc[-1],
                       "adjust_events": len(events),
                       "policy_events": "；".join(f"{d:%Y-%m-%d}×{k:.4f}" for d, k, *_ in pol),
                       "unlisted_reductions": "；".join(f"{d:%Y-%m-%d}×{k:.4f}（股數 {r:.4f}；{n}）" for d, k, r, n in unl), **diff})
        note = ""
        if diff.get("close_diff_days"):
            note = f"；重疊期 {diff['close_diff_days']} 天收盤價與現有差 >0.5%（現有為 yfinance 配股調整價）"
        if unl:
            note += "；減資（已發行股數）" + "、".join(f"{d:%Y-%m-%d}" for d, *_ in unl)
        if pol:
            note += "；股利政策補除權息 " + "、".join(f"{d:%Y-%m-%d}" for d, *_ in pol)
        print(f"{label}：{0 if old is None else len(old)} → {len(built)} 筆，"
              f"{built['date'].iloc[0]} ~ {built['date'].iloc[-1]}{note}")
        if not a.dry_run:
            PRICES.mkdir(parents=True, exist_ok=True)
            built.to_csv(path, index=False, lineterminator="\n")
            updated.add(sid)

    if warn_log:
        print("\n需要人工確認（未自動調整）：")
        for w in warn_log:
            print("  " + w)
    if not a.dry_run and (a.only is None):
        (UNI / "update_warnings.txt").write_text("\n".join(warn_log) + "\n", encoding="utf-8")

    # 財報與股利表
    tables = [("eps_all.csv", eps_new, ["stock_id", "date"]),
              ("dividend_all.csv", div_new, ["stock_id", "date", "year"]),
              ("dividend_result_all.csv", res_new, ["stock_id", "date"])]
    for fname, parts, keys in tables:
        new = pd.concat(parts, ignore_index=True) if parts else None
        before = len(pd.read_csv(UNI / fname)) if (UNI / fname).exists() else 0
        out = merge_table(UNI / fname, new, keys)
        print(f"{fname}：{before} → {len(out)} 筆")
        if not a.dry_run:
            out.to_csv(UNI / fname, index=False, lineterminator="\n")

    # 股數變動紀錄（分割、配股、減資）：只換掉本次更新的代號，其他保留
    if not a.dry_run and updated:
        sp = UNI / "share_events_all.csv"
        cols = ["stock_id", "date", "kind", "share_ratio"]
        keep = pd.read_csv(sp, dtype={"stock_id": str}) if sp.exists() else pd.DataFrame(columns=cols)
        keep = keep[~keep["stock_id"].isin(updated)]
        out = pd.concat([keep, pd.DataFrame(share_rows, columns=cols)], ignore_index=True).sort_values(["stock_id", "date"])
        out.to_csv(sp, index=False, lineterminator="\n")
        print(f"share_events_all.csv：{len(out)} 筆股數變動（{out['stock_id'].nunique()} 檔）")

    # TAIEX（交易日曆）：現有日期保留，往前補、往後接
    if not a.skip_taiex:
        t = finmind_price_frame(fm.get("TaiwanStockPrice", "TAIEX", a.start, a.end))
        tp = ROOT / "data" / "TAIEX.csv"
        old = pd.read_csv(tp, parse_dates=["date"])
        if t.empty:
            print("TAIEX：FinMind 沒有回傳資料，交易日曆未更新")
        else:
            add = t[(t["date"] < old["date"].min()) | (t["date"] > old["date"].max())]
            out = pd.concat([old, add[old.columns]], ignore_index=True).sort_values("date")
            out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
            print(f"TAIEX.csv：{len(old)} → {len(out)} 筆，{out['date'].iloc[0]} ~ {out['date'].iloc[-1]}")
            if not a.dry_run:
                out.to_csv(tp, index=False, lineterminator="\n")

    if not a.dry_run and updated:
        eps = pd.read_csv(UNI / "eps_all.csv", dtype={"stock_id": str})
        div = pd.read_csv(UNI / "dividend_all.csv", dtype={"stock_id": str})
        res = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
        rows = []
        for p in sorted(PRICES.glob("*.csv")):
            sid = p.stem
            df = pd.read_csv(p, usecols=["date"])
            prev = old_manifest.loc[sid] if old_manifest is not None and sid in old_manifest.index else None
            etf = sid in ETFS
            rows.append({"stock_id": sid, "name": names.get(sid, "" if prev is None else prev["name"]),
                         "source": SOURCE if sid in updated else (prev["source"] if prev is not None else ""),
                         "rows": len(df), "first_date": df["date"].iloc[0], "last_date": df["date"].iloc[-1],
                         "eps_rows": "" if etf else int((eps["stock_id"] == sid).sum()),
                         "dividend_rows": "" if etf else int((div["stock_id"] == sid).sum()),
                         "dividend_result_rows": "" if etf else int((res["stock_id"] == sid).sum()),
                         "sha256": sha256(p)})
        pd.DataFrame(rows).to_csv(manifest_path, index=False, lineterminator="\n")

    rep = pd.DataFrame(report)
    if not rep.empty:
        latest = rep["last_date"].max()
        recent = (pd.Timestamp(latest) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        lag = rep[(rep["last_date"] < latest) & (rep["last_date"] >= recent)]
        print(f"\n最新交易日 {latest}；{(rep['last_date'] == latest).sum()} / {len(rep)} 檔到最新。")
        if not lag.empty:
            print("以下現存股沒有到最新一天（當天市場中位數檔數會變少）：", " ".join(lag["stock_id"]))
        early = rep[rep["first_date"] > a.start].sort_values("first_date")
        print(f"{len(early)} 檔起始日晚於 {a.start}（上市較晚，或 FinMind 只有到那天）")
        if not a.dry_run:
            rep.to_csv(UNI / "update_report.csv", index=False, lineterminator="\n")
            print("逐檔比對：data/universe/update_report.csv")
    print(f"\nFinMind 請求 {fm.calls} 次（其餘來自快取）。")
    if not a.dry_run:
        print("下一步：rm -f results/portfolio_prepared.pkl results/param_opt_sigs.pkl && python portfolio_electronics.py")


if __name__ == "__main__":
    sys.exit(main())
