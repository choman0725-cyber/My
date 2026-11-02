"""每檔單獨跑、分三段看（2026-11-02 使用者：「把前段、前 7 年跟近 3 年分開來看，另外 0051／0052 成分股分類完也做」）。
股票池只留一檔，正式版 E＋D＋U1 規則與額度 ÷ 5 不變；段首 500 萬一次投入的那條路徑看筆數、持有天數與每筆進出日期；
另跑情境（每段 5 個起跑日 × 4 種追加＝20 個，近 3 年 12 個）看 IRR 中位／最差 10%／標準差。段末還沒賣的部位以段末市價計：
  前 10 年 2007-01-02～2016-12-30　前 7 年（樣本內）2017-01-03～2023-12-29　近 3 年（樣本外）2024-01-02～最新
股票：現行 47 檔（只在當天是 0050／0056 成分股時買）＋ 0051／0052 成分股裡的半導體、電腦及週邊（不在 47 檔內的，
當天在 0050／0056／0051／0052 任一名單就可買）。分類 data/universe/industry_twse_all.csv。
資料：results/portfolio_prepared_2006_all.pkl（2006 起、自己中位數為真歷史，所以與 2017 快取的數字略有不同）。
用法：python pool_single_period_study.py　輸出：results/pool_single_period.csv、results/pool_single_period_trades.csv"""
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, POOL
from pool_expand_study import load, setup_pool

PERIODS = {"前10年": ("2007-01-02", "2016-12-30"), "前7年": ("2017-01-03", "2023-12-29"), "近3年": ("2024-01-02", None)}
SC = {"半導體業", "電腦及週邊設備業"}
# 情境：每段 5 個起跑日（每半年）× 4 種追加方式＝20 個（近 3 年照樣本外 3 個起跑日＝12 個），追加在每年第一個交易日
STARTS = {"前10年": ["2007-01-02", "2007-07-02", "2008-01-02", "2008-07-01", "2009-01-05"], "前7年": rs.STARTS, "近3年": oos.STARTS_OOS}
CONTRIB = {"不追加": lambda k: 0, "每年50萬": lambda k: 500_000, "每年100萬": lambda k: 1_000_000, "分段50/80萬": lambda k: 500_000 if k < 3 else 800_000}


def scenarios(G, dates, kw, pk, e):
    """這一段 20（或 12）個情境：回傳 IRR 中位、最差 10%、標準差、損益中位（萬）、筆數中位。"""
    out = []
    for st in STARTS[pk]:
        s = dates.get_indexer([pd.Timestamp(st)], method="bfill")[0]
        yrs = [y for y in range(dates[s].year + 1, dates[e].year + 1)]
        fd = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in yrs}
        for cn, f in CONTRIB.items():
            amt = {y: f(k) for k, y in enumerate(yrs) if f(k)}
            contrib = {fd[y]: a / CAPITAL for y, a in amt.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, start_n=s, end_n=e, **kw)
            final = eq.iloc[-1] * CAPITAL; put = CAPITAL + sum(amt.values())
            out.append((irr([CAPITAL] + list(amt.values()), [dates[s]] + [dates[fd[y]] for y in amt], final, dates[e]), (final - put) / 1e4, len(tr)))
    x = pd.DataFrame(out, columns=["IRR", "損益", "筆數"])
    return {"情境數": len(x), "情境IRR中位%": round(x["IRR"].median(), 2), "情境最差10%": round(x["IRR"].quantile(.1), 2),
            "情境標準差": round(x["IRR"].std(), 2), "情境損益中位萬": round(x["損益"].median()), "情境筆數中位": x["筆數"].median()}


def stats(tr, dates, e):
    closed = tr[tr["出場"].notna()]
    held = (pd.to_datetime(tr["出場"]).fillna(dates[e]) - pd.to_datetime(tr["進場"])).dt.days if len(tr) else pd.Series(dtype=float)
    pnl = (closed["回收"] - closed["投入"]).sum() + (tr.loc[tr["出場"].isna(), "市值"] - tr.loc[tr["出場"].isna(), "投入"]).sum()
    return {"筆數": len(tr), "持有中": int(tr["出場"].isna().sum()),
            "勝率%": round(100 * (tr["報酬%"] > 0).mean()) if len(tr) else None,       # 含段末未賣部位（以市價計）
            "平均報酬%": round(tr["報酬%"].mean(), 1) if len(tr) else None,
            "每筆持有天": "/".join(f"{int(h)}{'*' if o else ''}" for h, o in zip(held, tr["出場"].isna())),   # * ＝段末還沒賣
            "持有中位天": held.median() if len(held) else None, "最深套牢%": round(tr["最深套牢%"].min(), 1) if len(tr) else None,
            "損益萬": round(pnl * CAPITAL / 1e4),
            "每筆進出": "；".join(f"{pd.Timestamp(a):%Y-%m-%d}→{'持有中' if pd.isna(b) else f'{pd.Timestamp(b):%Y-%m-%d}'}" for a, b in zip(tr["進場"], tr["出場"]))}


def main():
    cons, dates, data, sig = load()
    ind = pd.read_csv(ps.UNI / "industry_twse_all.csv", dtype=str).set_index("stock_id")
    tech = set(ind.index[ind["industry"].isin(SC)])
    extra = pd.concat([cons["0052"], cons["0051"]]); extra = extra[extra["stock_id"].isin(tech) & ~extra["stock_id"].isin(POOL)]
    G = setup_pool(pd.concat([cons["0050"], cons["0051"], cons["0052"]]), dates, data, sig)
    mem_all = dict(G["member"]); mem_50 = ps.membership(cons["0050"], dates)
    full_sub, full_sig = dict(G["sub"]), {e: dict(m) for e, m in G["sig"].items()}
    stocks = [(s, "47檔") for s in sorted(POOL)] + [(s, "0051/0052") for s in sorted(set(extra["stock_id"]) & set(full_sub))]
    win = {k: (dates.get_indexer([pd.Timestamp(a)], method="bfill")[0], len(dates) - 1 if b is None else dates.get_indexer([pd.Timestamp(b)], method="ffill")[0])
           for k, (a, b) in PERIODS.items()}
    rows, trades = [], []
    for sid, grp in stocks:
        mem = mem_50[sid] if grp == "47檔" else mem_all[sid]
        G["sub"] = {sid: full_sub[sid]}; G["member"] = {sid: mem}
        G["sig"] = {e: {sid: m[sid]} for e, m in full_sig.items() if sid in m}
        po._applied["buy"] = None; po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
        row = dict(代號=sid, 名稱=ind.loc[sid, "name"], 產業=ind.loc[sid, "industry"].replace("設備業", "").replace("業", ""), 來源=grp)
        for pk, (s, e) in win.items():
            row[f"{pk}成分天"] = int(mem.iloc[s:e + 1].sum())
            tr, _ = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, end_n=e, **kw)
            row.update({f"{pk}{k}": v for k, v in stats(tr, dates, e).items()})
            row.update({f"{pk}{k}": v for k, v in scenarios(G, dates, kw, pk, e).items()})
            if len(tr):
                trades.append(tr.assign(名稱=row["名稱"], 段=pk))
        rows.append(row)
        print(f"  {sid} {row['名稱']}（{grp}）：" + "　".join(f"{pk} {row[pk + '筆數']} 筆 {row[pk + '損益萬']} 萬 情境IRR {row[pk + '情境IRR中位%']}" for pk in PERIODS), flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "pool_single_period.csv", index=False, encoding="utf-8-sig")
    pd.concat(trades).to_csv(RESULTS / "pool_single_period_trades.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
