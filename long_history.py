"""2006 年起的全程回測（正式版 E＋D，可選避險部位）。
資料：results/portfolio_prepared_2006.pkl（用 2006-01-01 起的日曆重建的快取；沒有時自動建，約 5 分鐘）。
殖利率需要 4 季 EPS 與股利紀錄、5 年賺錢濾網至少 1 年已知，所以實際最早買點約在 2007 年。
用法：python long_history.py                 正式版 2006 起 + 每年起跑 + 逐年績效 vs 0050
      python long_history.py --hedge         加上避險變體（0050／美債／條件式）
輸出：results/long_history_yearly.csv、long_history_starts.csv、long_history_trades.csv、long_history_hedge_yearly.csv"""
import pickle
import sys
import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_ext
from backtest import RESULTS, ROOT
from yield_entry_study import entries
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, ELECTRONICS, POOL as _POOL

POOL = _POOL   # 正式版股票池（47 檔）；要重現 2026-11-01 以前的研究（電子 90 檔）先設 POOL = ELECTRONICS 再 setup()

START = pd.Timestamp("2006-01-01")
PKL = RESULTS / "portfolio_prepared_2006.pkl"
SIGS = RESULTS / "param_opt_sigs_2006.pkl"


def setup():
    """把 robust_study.G 換成 2006 起的資料，再讓 param_opt 的快取跟著走。"""
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= START - pd.Timedelta(days=5)]).sort_values()
    if not PKL.exists():
        PKL.write_bytes(pickle.dumps(ps.prepare(sorted(cons["stock_id"].unique()), dates)))
    data, _ = pickle.loads(PKL.read_bytes())
    ps.attach_fundamentals(data, dates)
    zone = {e: {k: v.values for k, v in ps.membership(cons[(cons["etf"] == e) & cons["stock_id"].isin(POOL)], dates).items()} for e in ("0050", "0056")}
    member = ps.membership(cons[cons["stock_id"].isin(POOL)], dates)
    G = rs.G
    G.clear()
    G.update(dates=dates, zone=zone, member=member, sub={k: v for k, v in data.items() if k in member},
             etf={e: ps.load_prices(e)[0]["close"].reindex(dates).ffill() for e in ("0050", "0056")})
    rs.SPLITS.clear(); rs.SPLITS.update(po.SPLITS)
    if SIGS.exists():
        G["sig"] = pickle.loads(SIGS.read_bytes())
    else:
        sig = {k: {} for k in po.ENTRIES.values()}
        for sid in G["sub"]:
            df, _ = ps.load_prices(sid)
            e, _ = entries(df)
            for k in sig:
                sig[k][sid] = e[k].reindex(dates).fillna(False).astype(bool).values
        G["sig"] = sig
        SIGS.write_bytes(pickle.dumps(sig))
    # 市場中位數（全部成分股）：param_opt.market_stats 會去讀 2017 的 pkl，這裡先算好塞進快取
    mem_all = ps.membership(cons, dates)
    Y = pd.DataFrame({s: np.where(mem_all[s].values, data[s]["yield"][:len(dates)], np.nan) for s in data if s in mem_all}, index=dates)
    po._mk[("all", len(dates))] = (Y.median(axis=1).values, Y.std(axis=1).values, Y.notna().sum(axis=1).values)
    po._applied.clear(); po._conf.clear()
    return G


def yearly_table(eq, d, extra_series=None, trades=None, ledger=None):
    """逐年：策略報酬、0050 報酬、年底現金比、年內買進／賣出筆數、年內最大回撤。"""
    nav = eq.copy()
    y = nav.groupby(nav.index.year).last()
    y0 = pd.concat([pd.Series({y.index[0] - 1: nav.iloc[0]}), y])
    ret = (y / y0.shift(1).reindex(y.index).fillna(nav.iloc[0]) - 1) * 100
    out = pd.DataFrame({"策略%": ret.round(1)})
    if extra_series is not None:
        for k, s in extra_series.items():
            s = s.reindex(nav.index).ffill()
            ys = s.groupby(s.index.year).last()
            ys0 = ys.shift(1); ys0.iloc[0] = s.iloc[0]
            out[k] = ((ys / ys0 - 1) * 100).round(1)
    dd = (nav / nav.cummax() - 1) * 100
    out["年內最大回撤%"] = dd.groupby(dd.index.year).min().round(1)
    if trades is not None and len(trades):
        t = trades.copy()
        out["買進筆"] = t.groupby(t["進場"].dt.year).size().reindex(out.index).fillna(0).astype(int)
        s = t.dropna(subset=["出場"])
        out["賣出筆"] = s.groupby(pd.to_datetime(s["出場"]).dt.year).size().reindex(out.index).fillna(0).astype(int)
        out["賣出勝率%"] = s.groupby(pd.to_datetime(s["出場"]).dt.year)["報酬%"].apply(lambda x: (x > 0).mean() * 100).reindex(out.index).round(0)
    if ledger is not None and len(ledger):
        L = pd.DataFrame(ledger)
        L["年"] = L["日期"].dt.year
        last = L.groupby("年").last()
        out["年底現金%"] = (last["現金"] / last["總資產"] * 100).reindex(out.index).round(0)
        if "避險部位" in last:
            out["年底避險%"] = (last["避險部位"] / last["總資產"] * 100).reindex(out.index).round(0)
    out["期末萬"] = (y * CAPITAL / 1e4).round(0).astype(int)
    return out


def main(hedge=False):
    G = setup(); d = G["dates"]
    po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    etf = {"0050%": pd.read_csv(ps.UNI / "prices" / "0050.csv", parse_dates=["date"]).set_index("date")["adj_close"]}
    led = []
    tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=1, ledger=led, **kw)
    yt = yearly_table(eq, d, etf, tr, led)
    yt.to_csv(RESULTS / "long_history_yearly.csv", encoding="utf-8-sig")
    tr.to_csv(RESULTS / "long_history_trades.csv", index=False, encoding="utf-8-sig")
    first_trade = tr["進場"].min()
    # 每年 1 月第一個交易日起跑
    rows = []
    for yr in range(2006, 2024):
        s = d.get_indexer([pd.Timestamp(yr, 1, 1)], method="bfill")[0]
        t_, e_ = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
        r50 = etf["0050%"].reindex(d).ffill()
        rows.append(dict(起跑=str(d[s].date()), 年數=round((d[-1] - d[s]).days / 365.25, 1), 期末萬=round(e_.iloc[-1] * CAPITAL / 1e4),
                         IRR=round(irr([CAPITAL], [d[s]], e_.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(e_, None), 1),
                         筆數=len(t_), **{"0050買進持有IRR": round(((r50.iloc[-1] / r50.iloc[s]) ** (365.25 / (d[-1] - d[s]).days) - 1) * 100, 1)}))
    st = pd.DataFrame(rows); st.to_csv(RESULTS / "long_history_starts.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(f"\n2006 起正式版：第一筆交易 {first_trade.date()}，期末 {eq.iloc[-1] * CAPITAL / 1e4:,.0f} 萬，IRR {irr([CAPITAL], [d[1]], eq.iloc[-1] * CAPITAL, d[-1]):.1f}%，筆數 {len(tr)}")
        print("\n逐年"); print(yt.to_string())
        print("\n每年起跑"); print(st.to_string(index=False))
    if hedge:
        from hedge_study import vehicles
        V = vehicles(d)
        base_h = dict(hedge_reserve=0.10, hedge_take=0.05, hedge_cooldown=10, hedge_add_timing="signal", hedge_add_cap="shortfall")
        tabs = {}
        runs = {name: {"hedge_index": arr} for name, arr in V.items()}
        runs.update({"0050·第一次賣股後才開始": {"hedge_index": V["0050"], "hedge_from": "first_sell"},
                     "0050·閒10天才投入": {"hedge_index": V["0050"], "hedge_idle_days": 10},
                     "條件式·第一次賣股後才開始": {"hedge_index": V["條件式(年線上0050/線下短債)"], "hedge_from": "first_sell"}})
        bond = next((k for k in V if "美債1-3" in k), None)
        if bond:
            runs["短債·手續費0（檢查鎖死）"] = {"hedge_index": V[bond], "hedge_cost": 0.0}
        for name, extra in runs.items():
            led = []
            tr_, eq_ = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=1, ledger=led, **kw, **{**base_h, **extra})
            hl = pd.DataFrame(eq_.attrs["hedge_log"])
            t_ = yearly_table(eq_, d, None, None, led)[["策略%", "年內最大回撤%", "年底現金%", "年底避險%", "期末萬"]]
            tabs[name] = t_
            print(f"\n避險＝{name}：期末 {eq_.iloc[-1] * CAPITAL / 1e4:,.0f} 萬，避險段數 {len(hl)}，避險總損益 {hl['回收'].sub(hl['投入']).sum() * CAPITAL / 1e4 if len(hl) else 0:,.0f} 萬")
        big = pd.concat(tabs, axis=1)
        big.to_csv(RESULTS / "long_history_hedge_yearly.csv", encoding="utf-8-sig")
        with pd.option_context("display.width", 400, "display.max_rows", 100, "display.max_columns", 60, "display.unicode.east_asian_width", True):
            print(big.to_string())


if __name__ == "__main__":
    main(hedge="--hedge" in sys.argv)
