"""收盤後先用 Yahoo 股市的日線當「暫定資料」（2026-11-02 使用者：FinMind 收盤後要等一陣子才有當天資料，
13:35 先抓 Yahoo 給建議，16:00 再從 FinMind 下載驗證，以 FinMind 為準）。
  apply(today)：Yahoo 有今天的 TAIEX 才做；股票池＋當天成分股（daily_update.universe）每檔接上今天一列
                （只接「前一列＝前一個交易日」的檔，adj_close＝close，與 FinMind 增量更新相同），
                TAIEX 也接上；寫進 data/provisional.json 記下接了哪些列。
  strip()：把 provisional.json 記的列從 CSV 拿掉、回傳暫定值（FinMind 更新前呼叫）。
  verify(prov)：FinMind 更新後，比對同一天 Yahoo 與 FinMind 的開高低收／成交量。
資料來源：query1.finance.yahoo.com/v8/finance/chart（上市 .TW、上櫃 .TWO、加權指數 ^TWII）。"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

import update_universe_finmind as uf

ROOT = uf.ROOT
PROV = ROOT / "data" / "provisional.json"
TAIEX = ROOT / "data" / "TAIEX.csv"
TW = timezone(timedelta(hours=8))
KEYS = ["open", "high", "low", "close", "volume"]


def bars(ticker, rng="5d"):
    """Yahoo 日線 → {日期字串: (開, 高, 低, 收, 量)}；抓不到回傳 {}。"""
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range={rng}&interval=1d"
    for k in range(3):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            r = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"]
            break
        except Exception:
            if k == 2:
                return {}
            time.sleep(2)
    if not r or "timestamp" not in r[0]:
        return {}
    q = r[0]["indicators"]["quote"][0]
    out = {}
    for i, ts in enumerate(r[0]["timestamp"]):
        row = [q[c][i] for c in KEYS]
        if None in row or not row[3] or row[3] <= 0:
            continue
        out[datetime.fromtimestamp(ts, TW).strftime("%Y-%m-%d")] = (*(round(float(x), 2) for x in row[:4]), int(row[4]))
    return out


def apply(today, ids):
    if PROV.exists():
        raise SystemExit(f"{PROV} 已存在（上一次的暫定資料還沒被 FinMind 取代），先跑 FinMind 更新")
    tai = pd.read_csv(TAIEX)
    prev = tai["date"].iloc[-1]
    tb = bars("^TWII")
    if today not in tb or prev >= today:
        return None
    prov = {"date": today, "prev": prev, "taiex": tb[today], "sids": {}}
    skip, miss = [], []
    for sid in ids:
        p = uf.PRICES / f"{sid}.csv"
        if not p.exists():
            continue
        old = pd.read_csv(p)
        if old["date"].iloc[-1] != prev:          # 已下市、停牌或本來就落後的，不補（等 FinMind）
            skip.append(sid); continue
        b = bars(f"{sid}.TW") or bars(f"{sid}.TWO")
        if today not in b:
            miss.append(sid); continue
        o, h, l, c, v = b[today]
        row = pd.DataFrame([{"date": today, "open": o, "high": h, "low": l, "close": c, "adj_close": c, "volume": v}])[old.columns]
        pd.concat([old, row], ignore_index=True).to_csv(p, index=False, lineterminator="\n")
        prov["sids"][sid] = b[today]
    o, h, l, c, v = tb[today]
    v = v or int(tai["volume"].iloc[-1])            # Yahoo 加權指數沒有成交量（0）：暫用前一天的量
    pd.concat([tai, pd.DataFrame([{"date": today, "open": o, "high": h, "low": l, "close": c, "volume": v}])[tai.columns]],
              ignore_index=True).to_csv(TAIEX, index=False, lineterminator="\n")
    PROV.write_text(json.dumps(prov, ensure_ascii=False), encoding="utf-8")
    return dict(date=today, n=len(prov["sids"]), skip=skip, miss=miss, taiex=c)


def strip():
    """拿掉暫定列，回傳暫定資料（沒有就回傳 None）。"""
    if not PROV.exists():
        return None
    prov = json.loads(PROV.read_text(encoding="utf-8"))
    d = prov["date"]
    for sid in list(prov["sids"]) + ["TAIEX"]:
        p = TAIEX if sid == "TAIEX" else uf.PRICES / f"{sid}.csv"
        df = pd.read_csv(p)
        if df["date"].iloc[-1] == d:
            df.iloc[:-1].to_csv(p, index=False, lineterminator="\n")
    return prov


def verify(prov):
    """FinMind 更新後：同一天的 Yahoo 暫定值 vs FinMind。回傳 (價格不一致清單, 量差 >1% 檔數, FinMind 沒有這天的清單)。"""
    d, bad, vol, none = prov["date"], [], 0, []
    for sid, (o, h, l, c, v) in prov["sids"].items():
        df = pd.read_csv(uf.PRICES / f"{sid}.csv").set_index("date")
        if d not in df.index:
            none.append(sid); continue
        r = df.loc[d]
        diff = [f"{k} {y}→{r[k]}" for k, y in zip(["open", "high", "low", "close"], (o, h, l, c)) if abs(float(r[k]) - y) > 0.005]
        if diff:
            bad.append(f"{sid}（{'、'.join(diff)}）")
        if r["volume"] and abs(v / float(r["volume"]) - 1) > 0.01:
            vol += 1
    return bad, vol, none
