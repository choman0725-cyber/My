"""13:35 暫定版的快速重建（2026-11-02 使用者：「你要給我的不就是買進建議而已嗎」）。
全部重建要把約 200 檔從 2006 年起重算（20～30 分鐘）；暫定版只有庫存＋觀察股（約 10 檔）多了今天一列，所以：
  - 這幾檔：用 portfolio_study.prepare 重算（讀 CSV，資料庫 16:00 才重建）；
  - 其他股票：沿用前一天的快取，每個陣列往後延一天（價格 NaN、close_ff 沿用前一天、買點／加碼訊號 False，
    與全部重建時「這檔今天沒有價格」算出來的結果相同；唯一刻意不同：殖利率沿用前一天（全部重建會是 NaN），
    市場殖利率中位數才不會只剩十檔觀察股算、被高殖利率股拉高；已下市的仍是 NaN）；
  - param_opt_sigs.pkl（技術買點快取）同樣處理。
快取的日曆必須正好是「今天之前的交易日」，對不上就回傳 False（呼叫端改做全部重建）。"""
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import RESULTS, ROOT
from yield_entry_study import entries

PKL, SIGS = RESULTS / "portfolio_prepared.pkl", RESULTS / "param_opt_sigs.pkl"
PRICE_NAN = ("open", "close", "low")
SIG_FALSE = ("buy", "add")


def calendar():
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    return pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()


def extend(d, n_old, dates):
    """一檔沒有新價格的股票：快取往後延到 dates（多出的日子視為沒有報價）。"""
    k = len(dates) - n_old
    out = dict(d)
    alive = d["last_n"] == n_old + 1                                   # 已下市的不延續殖利率（市場中位數不該算到它）
    for key, v in d.items():
        if key == "df":
            out[key] = v.reindex(dates)
        elif key == "last_n":
            out[key] = len(dates) + 1 if v == n_old + 1 else v        # 沒下市的：沿用「比日曆長 1」的標記
        elif isinstance(v, np.ndarray) and len(v) == n_old:
            if key in PRICE_NAN or (key == "yield" and not alive):
                pad = np.full(k, np.nan)
            elif key in SIG_FALSE or v.dtype == bool:
                pad = np.zeros(k, dtype=v.dtype)
            else:                                                     # close_ff、yield：沿用前一天（全部重建時也是往前補）
                pad = np.repeat(v[-1:], k)
            out[key] = np.concatenate([v, pad])
    return out


def fast_rebuild(changed):
    if not (PKL.exists() and SIGS.exists()):
        return False
    dates = calendar()
    data, skipped = pickle.loads(PKL.read_bytes())
    sig = pickle.loads(SIGS.read_bytes())
    n_old = len(next(iter(data.values()))["close"])
    if n_old != len(dates) - 1 or any(len(d["close"]) != n_old for d in data.values()):
        return False
    db, ps.DB = ps.DB, Path("__no_db__")                              # 這幾檔讀 CSV（資料庫 16:00 才重建）
    try:
        new, _ = ps.prepare([s for s in changed if s in data], dates)
    finally:
        ps.DB = db
    for sid in data:
        data[sid] = new[sid] if sid in new else extend(data[sid], n_old, dates)
    for m in sig.values():                                            # 先全部延一天（False），有新價格的下面重算
        for sid, v in m.items():
            m[sid] = np.concatenate([v, np.zeros(len(dates) - len(v), bool)])
    db, ps.DB = ps.DB, Path("__no_db__")
    try:
        for sid in [s for s in changed if any(s in m for m in sig.values())]:
            df, _ = ps.load_prices(sid)
            e, _ = entries(df)
            for k_ in sig:
                if sid in sig[k_]:
                    sig[k_][sid] = e[k_].reindex(dates).fillna(False).astype(bool).values
    finally:
        ps.DB = db
    PKL.write_bytes(pickle.dumps((data, skipped)))
    SIGS.write_bytes(pickle.dumps(sig))
    return True
