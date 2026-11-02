"""驗證 2026-11-02 向量化的 portfolio_study.forward_dividend 與原本逐日迴圈版結果完全相同（全池、全部交易日）。
用法：python verify_forward_dividend.py　　輸出每檔最大差異，任何一檔不相同就印出來並以非 0 結束。"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import ROOT


def forward_dividend_loop(dates, eps, div, payout_years=3):
    """原版（逐日迴圈），只留在這裡當對照。"""
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


def main():
    ps.DB = Path("__no_db__")                                     # 只讀 CSV，不碰可能正在重建的資料庫
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= pd.Timestamp("2006-01-01")]).sort_values()     # 比 2017 起的日曆更廣
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv"); div_all = pd.read_csv(ps.UNI / "dividend_all.csv")
    res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv"); share_all = ps.load_share_events()
    bad, t_old, t_new, n = [], 0.0, 0.0, 0
    for sid in sorted(cons["stock_id"].unique()):
        loaded = ps.load_prices(sid)
        if loaded is None:
            continue
        _, raw = loaded
        eps, div, raw = ps.fundamentals_on_share_basis(sid, raw, eps_all, div_all, res_all, share_all)
        cal_ = dates[(dates >= raw.index[0]) & (dates <= raw.index[-1])]
        t0 = time.time(); a = forward_dividend_loop(cal_, eps, div); t1 = time.time(); b = ps.forward_dividend(cal_, eps, div); t2 = time.time()
        t_old += t1 - t0; t_new += t2 - t1; n += 1
        same = ((a.isna() & b.isna()) | np.isclose(a, b, rtol=0, atol=1e-12, equal_nan=True)).all()
        if not same:
            diff = (a - b).abs()
            bad.append((sid, int((~((a.isna() & b.isna()) | (diff <= 1e-12))).sum()), float(diff.max())))
            print(f"[DIFF] {sid}: 不同天數 {bad[-1][1]} 最大差 {bad[-1][2]}", flush=True)
    print(f"{n} 檔；舊版合計 {t_old:.1f} 秒、新版 {t_new:.1f} 秒；不同的檔：{bad or '沒有'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
