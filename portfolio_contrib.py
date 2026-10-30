"""每年追加投入：初始 500 萬，2018 年起每年第一個交易日追加 100 萬或 50 萬（只買電子股）。

報酬以 IRR（資金加權年化報酬）計算；比較基準為同時間、同金額買進 0050 / 0056 並持有。
用法：python portfolio_contrib.py
"""
import pickle

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import BUY_COST, RESULTS, ROOT
from portfolio_electronics import CAPITAL, ELECTRONICS

_BASE = {"one_per_day": True, "cooldown": 7, "target_util": 0.8, "util_mode": "invested", "first": 0.8,
         "removal_exit": "tech_profit", "free_slot_removed": True}
VERSIONS = {
    "V1報酬優先｜2+3區·EPS轉負出場": ({**_BASE, "exit_eps_loss": True}, (2, 3)),
    "V2最多抱2年｜3+2區·滿2年強制賣": ({**_BASE, "max_hold_days": 730}, (3, 2)),
    "V3 A＋需好標的｜3+2區": ({**_BASE, "target_schedule": [(0, 0.20), (365, 0.0)], "offset_loss": True,
                            "offset_min_hold_days": 365, "time_add_days": 182, "need_candidate": True}, (3, 2)),
}
ADDS = {"不追加": 0, "每年追加50萬": 500_000, "每年追加100萬": 1_000_000,
        "前3年50萬·中3年80萬·後3年100萬": {**{y: 500_000 for y in (2018, 2019, 2020)},
                                       **{y: 800_000 for y in (2021, 2022, 2023)},
                                       **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
# 只看單一 ETF 時不分區，最多 5 檔
SINGLE_VERSIONS = {
    "①解讀二·R5＋移出不佔名額": ({"one_per_day": True, "cooldown": 7, "target_util": 0.8, "util_mode": "invested",
                                "first": 0.8, "removal_exit": "tech_profit", "free_slot_removed": True}, None),
    "①解讀二·R1": ({"one_per_day": True, "cooldown": 7, "target_util": 0.8, "util_mode": "invested", "first": 0.8,
                   "removal_exit": "immediate"}, None),
    "②原版＋套牢不佔名額·R5＋移出不佔名額": ({"stale_free_slot": True, "removal_exit": "tech_profit",
                                         "free_slot_removed": True}, None),
}
UNIVERSES = {"0050＋0056": (("0050", "0056"), VERSIONS)}


def irr(flows, dates_, final_value, end):
    t = np.array([(d - dates_[0]).days / 365.25 for d in dates_])
    T = (end - dates_[0]).days / 365.25
    f = lambda r: sum(-c * (1 + r) ** (T - ti) for c, ti in zip(flows, t)) + final_value
    lo, hi = -0.9, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return 100 * mid


def main():
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    ps.attach_fundamentals(data, dates)
    zone = {etf: {k: v.values for k, v in ps.membership(
        cons[(cons["etf"] == etf) & cons["stock_id"].isin(ELECTRONICS)], dates).items()} for etf in ("0050", "0056")}
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, dates[-1].year + 1)}
    etf_px = {e: ps.load_prices(e)[0]["close"].reindex(dates).ffill() for e in ("0050", "0056")}

    rows, holdings = {}, {}
    for uname, (etfs, versions) in UNIVERSES.items():
      member = ps.membership(cons[cons["etf"].isin(etfs) & cons["stock_id"].isin(ELECTRONICS)], dates)
      sub = {k: v for k, v in data.items() if k in member}
      for aname, amt in ADDS.items():
          per_year = amt if isinstance(amt, dict) else {y: amt for y in first_day} if amt else {}
          contrib = {first_day[y]: a / CAPITAL for y, a in per_year.items()} or None
          flow_dates = [dates[1]] + [dates[first_day[y]] for y in per_year]
          flows = [CAPITAL] + list(per_year.values())
          invested = sum(flows)
          for vname, (kw, split) in versions.items():
              extra = {"slot_split": {"0050": (split[0], zone["0050"]), "0056": (split[1], zone["0056"])}} if split else {}
              tr, eq = ps.run(sub, member, dates, capital=CAPITAL, contributions=contrib, **kw, **extra)
              final = eq.iloc[-1] * CAPITAL
              # 回撤用「扣除追加資金」的淨值計算（時間加權）
              units = eq.copy()
              rets = eq.pct_change()
              for n in (contrib or {}):
                  d = dates[n]
                  rets.loc[d] = (eq.loc[d] - contrib[n]) / eq.shift(1).loc[d] - 1
              nav = (1 + rets.fillna(0)).cumprod()
              rows[(uname, aname, vname)] = {"總投入(萬)": invested / 1e4, "期末資產(萬)": final / 1e4,
                                      "獲利(萬)": (final - invested) / 1e4, "IRR%": irr(flows, flow_dates, final, dates[-1]),
                                      "最大回撤%": 100 * (nav / nav.cummax() - 1).min(),
                                      "資金使用率%": eq.attrs["資金使用率%"],
                                      "勝率%": 100 * (tr.loc[tr["出場"].notna(), "報酬%"] > 0).mean(),
                                      "最長持有(年)": ((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days.max()) / 365,
                                      "持有>2年": int(((tr["出場"].fillna(dates[-1]) - tr["進場"]).dt.days > 730).sum())}
              tr["名稱"] = tr["代號"].map(names)
              holdings[(uname, aname, vname)] = tr[tr["出場"].isna()].assign(投入=lambda x: x["投入"] * CAPITAL,
                                                                      市值=lambda x: x["市值"] * CAPITAL)
          for etf, px in etf_px.items():
              shares = sum(c * (1 - BUY_COST) / px.loc[d] for c, d in zip(flows, flow_dates))
              final = shares * px.iloc[-1]
              pxn = px.loc[dates[1]:] / px.loc[dates[1]]
              rows[(uname, aname, f"{etf} 定期買進持有")] = {"總投入(萬)": invested / 1e4, "期末資產(萬)": final / 1e4,
                                                   "獲利(萬)": (final - invested) / 1e4,
                                                   "IRR%": irr(flows, flow_dates, final, dates[-1]),
                                                   "最大回撤%": 100 * (pxn / pxn.cummax() - 1).min()}
    table = pd.DataFrame(rows).T
    table.index.names = ["選股範圍", "追加", "版本"]
    table.round(2).to_csv(RESULTS / "portfolio_contrib_final3.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        for k, h in holdings.items():
            if k[1].startswith("前3年") and not k[2].endswith("買進持有"):
                print(f"【{k[0]}｜{k[1]}｜{k[2]} 目前持股】")
                print(h[["名稱", "進場", "加碼", "投入", "市值", "報酬%"]].round(0).to_string(index=False), "\n")


if __name__ == "__main__":
    main()
