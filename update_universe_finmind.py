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
API = "https://api.finmindtrade.com/api/v4/data"
PRICE_COLS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
ETFS = ("0050", "0056")
SOURCE = "FinMind TaiwanStockPrice + 自算 adj_close"


# ---------- FinMind ----------

class FinMind:
    def __init__(self, token=None, refresh=False, pause=0.3):
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.refresh, self.pause, self.calls = refresh, pause, 0
        self.disabled = set()

    def get(self, dataset, data_id, start, end, optional=False):
        """optional=True：遇到 402（可能是付費資料集）就整個停用該資料集、回傳空表，不等待。"""
        if dataset in self.disabled:
            return pd.DataFrame()
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / f"{dataset}_{data_id}_{start}_{end}.json"
        if f.exists() and not self.refresh:
            return pd.DataFrame(json.loads(f.read_text(encoding="utf-8")))
        params = {"dataset": dataset, "data_id": data_id, "start_date": start, "end_date": end}
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
                if optional:
                    print(f"    {dataset} 回 402（{body.get('msg', '')}），本次略過此資料集")
                    self.disabled.add(dataset)
                    return pd.DataFrame()
                if waited >= 75 * 60:
                    raise RuntimeError("等待流量限制超過 75 分鐘，請稍後重跑（已抓的會從快取接續）")
                print(f"    FinMind 流量限制（本次已抓 {self.calls} 次），5 分鐘後續抓… {body.get('msg', '')}")
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


def adjust_events(div_result, reduction=None, split=None):
    """[(生效日, 係數)]：生效日之前的價格要乘上係數。同一事件若在兩個資料集都出現（±5 天、係數差 <1%）只算一次。"""
    events = _events(div_result, "before_price", "reference_price")
    extra = (_events(reduction, "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice")
             + _events(split, "before_price", "after_price"))
    for d, k in extra:
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


def share_events(sid, div, res, reduction, split, inferred):
    """股數變動紀錄 [(stock_id, 日期, 種類, 變動後股數 ÷ 變動前股數)]，給殖利率換算同一股數基準用。
    配股：1 + (盈餘配股＋公積配股) ÷ 10（面額 10 元），日期＝除權交易日；股利政策缺漏時用除權息結果「權」（只有權、沒有息）的價格比。
    分割：分割前價 ÷ 分割後價；減資：減資前收盤 ÷ 減資後參考價（現金退還型為近似）；推定減資：1 ÷ 價格係數。
    同一事件出現在兩個來源（±5 天、比例差 <1%）只記一次。"""
    ev = []
    if div is not None and not div.empty and "StockExDividendTradingDate" in div:
        x = div.copy()
        x["stock"] = pd.to_numeric(x["StockEarningsDistribution"], errors="coerce").fillna(0) \
            + pd.to_numeric(x["StockStatutorySurplus"], errors="coerce").fillna(0)
        x["d"] = pd.to_datetime(x["StockExDividendTradingDate"], errors="coerce")
        for d, st in zip(x["d"], x["stock"]):
            if pd.notna(d) and st > 0:
                ev.append((d, "配股", 1 + st / 10))
    if res is not None and not res.empty:
        r = res[res["stock_or_cache_dividend"].astype(str) == "權"]
        for d, k in _events(r, "before_price", "reference_price"):
            if not any(abs((d - d0).days) <= 5 for d0, _, _ in ev):
                ev.append((d, "配股或分割（除權結果）", 1 / k))
    for kind, lst in (("分割", _events(split, "before_price", "after_price")),
                      ("減資", _events(reduction, "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice")),
                      ("推定減資", inferred)):
        for d, k in lst:
            ratio = 1 / k
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


def inferred_reductions(df, events, gap_days=7, jump=0.11):
    """停牌 ≥ gap_days 天後恢復交易、開盤比停牌前收盤高 > jump，且 ±10 天內沒有已知事件 → 推定為減資。
    FinMind 減資資料集只有 2011 年起（例：2412 中華電 2009-03、2408 南亞科 2009-08、2633 高鐵 2015-12 都沒有）。
    係數 = 恢復日開盤 ÷ 停牌前收盤（以開盤近似減資後參考價）。只推定「往上跳」：減資一定讓每股價格變高，
    往下跳可能是真實下跌，不調整。"""
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
    a = ap.parse_args()

    cons = pd.read_csv(UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    # 其他 ETF 的成分股（例如 constituents_0051.csv）也一起抓；這些檔不影響正式版（正式版只讀 constituents.csv）
    extra_cons = [pd.read_csv(f, dtype={"stock_id": str, "etf": str}) for f in sorted(UNI.glob("constituents_*.csv"))]
    if extra_cons:
        cons = pd.concat([cons] + extra_cons, ignore_index=True)
    names = cons.drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    names.update({"0050": "元大台灣50", "0056": "元大高股息"})
    ids = list(ETFS) + sorted(cons["stock_id"].unique()) + [s for s in a.extra if s not in names]
    if a.only:
        ids = [s for s in ids if s in set(a.only)] + [s for s in a.only if s not in ids]
    print(f"FinMind 更新：{len(ids)} 檔，{a.start} ~ {a.end}，token {'有' if a.token else '無（300 次／小時）'}")

    fm = FinMind(a.token, a.refresh)
    manifest_path = UNI / "prices_manifest.csv"
    old_manifest = pd.read_csv(manifest_path, dtype=str).set_index("stock_id") if manifest_path.exists() else None
    res_hist = pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str})
    eps_new, div_new, res_new, report, updated, share_rows = [], [], [], [], set(), []

    for i, sid in enumerate(ids, 1):
        raw = fm.get("TaiwanStockPrice", sid, a.start, a.end)
        res = fm.get("TaiwanStockDividendResult", sid, a.start, a.end)
        reduction = split = div = None
        if sid not in ETFS:
            fin = fm.get("TaiwanStockFinancialStatements", sid, a.start, a.end)
            if not fin.empty:
                eps_new.append(fin[fin["type"] == "EPS"][["stock_id", "date", "value"]])
            div = fm.get("TaiwanStockDividend", sid, a.start, a.end)
            if not div.empty:
                div_new.append(div)
            reduction = fm.get("TaiwanStockCapitalReductionReferencePrice", sid, a.start, a.end, optional=True)
        split = fm.get("TaiwanStockSplitPrice", sid, a.start, a.end, optional=True)  # ETF 也會分割（0050 2025-06 一拆四）
        if not res.empty:
            res_new.append(res)

        # 還原係數：新抓的＋既有的除權息結果（避免 FinMind 某次缺漏），再加減資、分割
        res_all = pd.concat([res_hist[res_hist["stock_id"] == sid], res], ignore_index=True)
        events = adjust_events(res_all, reduction, split)

        new = finmind_price_frame(raw)
        path = PRICES / f"{sid}.csv"
        old = pd.read_csv(path) if path.exists() else None
        label = f"  [{i}/{len(ids)}] {sid} {names.get(sid, '')}"
        if new.empty:
            print(f"{label}：FinMind 沒有日線，{'保留現有檔案' if old is not None else '略過'}")
            continue
        inferred = inferred_reductions(new, events)
        events = sorted(events + inferred)
        share_rows += share_events(sid, div if sid not in ETFS else None, res_all, reduction, split, inferred)
        built = build_prices(new, events)
        diff = compare(old, built)
        report.append({"stock_id": sid, "name": names.get(sid, ""), "old_rows": 0 if old is None else len(old),
                       "rows": len(built), "first_date": built["date"].iloc[0], "last_date": built["date"].iloc[-1],
                       "adjust_events": len(events),
                       "inferred_reductions": "；".join(f"{d:%Y-%m-%d}×{k:.3f}" for d, k in inferred), **diff})
        note = ""
        if diff.get("close_diff_days"):
            note = f"；重疊期 {diff['close_diff_days']} 天收盤價與現有差 >0.5%（現有為 yfinance 配股調整價）"
        if inferred:
            note += "；推定減資 " + "、".join(f"{d:%Y-%m-%d}" for d, _ in inferred)
        print(f"{label}：{0 if old is None else len(old)} → {len(built)} 筆，"
              f"{built['date'].iloc[0]} ~ {built['date'].iloc[-1]}{note}")
        if not a.dry_run:
            PRICES.mkdir(parents=True, exist_ok=True)
            built.to_csv(path, index=False, lineterminator="\n")
            updated.add(sid)

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
