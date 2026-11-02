"""47 檔每一檔單獨跑（股票池只留這一檔）：看這檔自己的獲利能力、交易次數（2026-11-02 使用者）。
正式版 E＋D＋U1 全部規則不變，額度仍是總資產 ÷ 5（一檔最多用到約兩成資金，其餘放現金），所以整體 IRR 會偏低，
看個股能力主要看：筆數、勝率、平均報酬、單筆年化、持有天數、最深套牢、損益。只在當天是 0050／0056 成分股時才會買。
20 情境欄＝只有這一檔時 20 情境＋後 3 年的三段平均（整體資金報酬，含 8 成閒置現金）。
用法：python pool_single_study.py　輸出：results/pool_single_eval.csv、results/pool_single_trades.csv"""
import time

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, POOL
from pool_tech_study import restrict

rs.POOL = POOL                # pool_tech_study 匯入時把池子改回電子 90 檔，這裡改回正式版 47 檔
NAMES = pd.read_csv(ps.UNI / "industry_twse_elec.csv", dtype=str).set_index("stock_id")[["name", "industry"]]


def stats(tr, eq, dates, s):
    closed = tr[tr["出場"].notna()]
    held = (pd.to_datetime(tr["出場"]).fillna(dates[-1]) - pd.to_datetime(tr["進場"])).dt.days if len(tr) else pd.Series(dtype=float)
    pnl = ((closed["回收"] - closed["投入"]).sum() + (tr.loc[tr["出場"].isna(), "市值"] - tr.loc[tr["出場"].isna(), "投入"]).sum())
    ann = closed["報酬%"] / closed["持有日"].clip(lower=1) * 365 if len(closed) else pd.Series(dtype=float)
    return {"筆數": len(tr), "已結案": len(closed), "持有中": int(tr["出場"].isna().sum()),
            "勝率%": round(100 * (closed["報酬%"] > 0).mean()) if len(closed) else np.nan,
            "平均報酬%": round(closed["報酬%"].mean(), 1) if len(closed) else np.nan,
            "單筆年化中位%": round(ann.median(), 1) if len(ann) else np.nan,
            "持有中位天": held.median() if len(held) else np.nan, "最長持有天": held.max() if len(held) else np.nan,
            "最深套牢%": round(tr["最深套牢%"].min(), 1) if len(tr) else np.nan,
            "損益萬": round(pnl * CAPITAL / 1e4), "整體IRR%": round(irr([CAPITAL], [dates[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, dates[-1]), 1)}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    full = {k: G[k] for k in ("sub", "member", "sig", "zone")}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    rows, trades = [], []
    for i, sid in enumerate(sorted(POOL)):
        t0 = time.time()
        restrict(G, full, {sid})
        po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
        name = f"只{sid}"; po.CONFIGS[name] = dr.FINAL
        m = po.evaluate([name], f"single_{sid}").loc[name]
        row = dict(代號=sid, 名稱=NAMES.loc[sid, "name"], 產業=NAMES.loc[sid, "industry"].replace("設備業", "").replace("業", ""),
                   成分股天數=int(full["member"][sid].iloc[1:].sum()), 三段平均=round(m["三段平均"], 2), 標準差=round(m["標準差平均"], 2))
        for sn, s in (("1228", 1), ("0103", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            row.update({f"{k}_{sn}": v for k, v in stats(tr, eq, dates, s).items()})
            if sn == "1228" and len(tr):
                trades.append(tr.assign(名稱=row["名稱"]))
        rows.append(row)
        for f in RESULTS.glob(f"param_opt_single_{sid}_*"):
            f.unlink()
        print(f"  [{i + 1}/{len(POOL)}] {sid} {row['名稱']}：三段 {row['三段平均']} 筆數 {row['筆數_1228']} 勝率 {row['勝率%_1228']} "
              f"平均 {row['平均報酬%_1228']} 損益 {row['損益萬_1228']} 萬（{time.time() - t0:.0f}s）", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "pool_single_eval.csv", index=False, encoding="utf-8-sig")
    if trades:
        pd.concat(trades).to_csv(RESULTS / "pool_single_trades.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out.sort_values("損益萬_1228", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
