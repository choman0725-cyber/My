"""一鍵檢查（交接用）：程式能不能跑、資料完不完整、正式版數字能不能重現。
用法：python check_all.py            # 約 3 分鐘：編譯、資料、兩條正式路徑、每日程式
      python check_all.py --full     # 再加 20 情境＋後 3 年（約 5 分鐘），核對三段平均／最差 10%／標準差
每一項印 PASS／FAIL 與實際值；預期值寫在 EXPECT。"""
import glob
import py_compile
import sqlite3
import subprocess
import sys

import numpy as np
import pandas as pd

from backtest import RESULTS, ROOT

UNI = ROOT / "data" / "universe"
# 2026-11-01 股票池改成半導體＋電腦及週邊 47 檔（使用者採用，pool_tech_study.py）；電子 90 檔時為 3828／4854／7 檔／25.97／21.69／2.25／24.24／29.66／24.02
# 回測截止日＝rules_research.BACKTEST_END（2026-11-02 起回測與每日程式分開，每天更新資料不會動到這些數字）。
# 要往前推基準：改 rules_research.BACKTEST_END → 跑 --full → 把六個新數字和日期抄進這裡；日期對不上這裡會 FAIL 提醒
# 2026-11-02 技術買點加「落底（跌深守前低）」（使用者採用，bottom_entry_study.py）；之前為 5022／5093／33.31／23.36／1.70／26.82／35.42／37.71
# 2026-11-02 晚再加「下影線站穩」（k=0.8×5 日均量，bottom_entry_study.py kscan）；只有落底時為 6184／5771／33.33／23.85／1.49／26.65／37.02／36.33
EXPECT = {"回測截止日": "2026-10-30", "2016-12-28 起期末萬": 6323, "2017-01-03 起期末萬": 6287, "持股檔數": 5,
          "三段平均": 34.73, "最差10最小": 25.37, "標準差平均": 1.62, "前7年": 27.26, "延續": 40.14, "單獨": 36.80}
fails = []


def ok(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        fails.append(name)


def main(full=False):
    print("== 1. 程式")
    bad = []
    for f in sorted(glob.glob(str(ROOT / "*.py"))):
        try:
            py_compile.compile(f, doraise=True)
        except Exception as e:
            bad.append((f, str(e)[:80]))
    ok("所有 .py 可編譯", not bad, f"{len(glob.glob(str(ROOT / '*.py')))} 檔" + (f"；失敗 {bad}" if bad else ""))
    for mod in ("portfolio_study", "param_opt", "robust_study", "oos_study", "rules_live", "rules_research", "daily_run", "rules_ext", "stock_fit", "portfolio_electronics", "hedge_study", "long_history"):
        try:
            __import__(mod); ok(f"import {mod}", True)
        except Exception as e:
            ok(f"import {mod}", False, str(e)[:100])

    print("\n== 2. 資料")
    import portfolio_electronics as pe
    pool = sorted(pe.ELECTRONICS)
    ok("股票池（分類法）檔數", len(pool) == 91, f"{len(pool)}（含廣輝，資料不足不入池 → 引擎內 90）")
    cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
    ok("0050/0056 成分股檔", cons["etf"].isin(["0050", "0056"]).all() and cons["effective_date"].min() == "2006-01-02",
       f"{len(cons)} 列、{cons.stock_id.nunique()} 檔、{cons.effective_date.min()}～{cons.effective_date.max()}")
    ind = pd.read_csv(UNI / "industry_finmind.csv", dtype=str)
    miss_ind = sorted(set(cons.stock_id) - set(ind.stock_id))
    ok("產業分類覆蓋 0050/0056 成分股", miss_ind == ["3012"], f"缺 {miss_ind}（廣輝已手動歸電子）")
    tai = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])
    cut = pd.Timestamp(EXPECT["回測截止日"])
    ok("TAIEX 涵蓋回測截止日", (tai.date == cut).any(), f"最後日 {tai.date.max().date()}（回測截止 {cut.date()}）")
    last, dup, nonpos, nan_adj, short = {}, [], [], [], []
    for sid in pool:
        p = UNI / "prices" / f"{sid}.csv"
        if not p.exists():
            short.append(sid); continue
        df = pd.read_csv(p, parse_dates=["date"])
        last[sid] = df.date.max()
        if df.date.duplicated().any(): dup.append(sid)
        if (df.close <= 0).any(): nonpos.append(sid)
        if df.adj_close.isna().any(): nan_adj.append(sid)
    cur = cons[cons.effective_date == cons.effective_date.max()]
    active = [s for s in pool if s in set(cur.stock_id)]
    stale = [s for s in active if last[s] < cut]
    live_last = max(last[s] for s in active)
    n_live = sum(1 for s in active if last[s] == live_last)
    ok("現任成分股日線到回測截止日", not stale, f"{len(active)} 檔現任電子股；未到 {cut.date()}：{stale}；"
       f"最新一天 {live_last.date()} 有 {n_live} 檔（13:35 暫定只更新庫存＋觀察股，16:00 後應為全部）")
    ok("日線無重複日期／非正收盤／adj_close 缺值", not (dup or nonpos or nan_adj), f"重複 {dup} 非正 {nonpos} 缺值 {nan_adj}")
    eps = pd.read_csv(UNI / "eps_all.csv", dtype={"stock_id": str})
    latest = eps.groupby("stock_id")["date"].max()
    eps_stale = [s for s in active if latest.get(s, "") < "2026-06-30"]
    ok("現任成分股 EPS 到 2026Q2 以後", not eps_stale, f"最新季 {eps.date.max()}；落後：{eps_stale}")
    div = pd.read_csv(UNI / "dividend_all.csv", dtype={"stock_id": str})
    ok("股利政策檔", len(div) > 3000 and set(active) <= set(div.stock_id), f"{len(div)} 列")
    se = pd.read_csv(UNI / "share_events_all.csv", dtype={"stock_id": str})
    ok("股數事件無重複鍵", not se.duplicated(["stock_id", "date", "kind"]).any(), f"{len(se)} 筆")
    db = ROOT / "data" / "market.db"
    if db.exists():
        with sqlite3.connect(db) as con:
            n_db = con.execute("select count(*) from prices").fetchone()[0]
            diff = 0
            for sid in pool[:: max(1, len(pool) // 15)]:
                a = pd.read_sql_query("select date, close, adj_close from prices where stock_id=? order by date", con, params=(sid,))
                b = pd.read_csv(UNI / "prices" / f"{sid}.csv")[["date", "close", "adj_close"]]
                if len(a) != len(b) or not np.allclose(a[["close", "adj_close"]].values, b[["close", "adj_close"]].values):
                    diff += 1
        ok("market.db 與 CSV 一致（抽 15 檔）", diff == 0, f"db 日線 {n_db:,} 列；不一致 {diff}")
    else:
        ok("market.db 存在", False, "沒有：python build_db.py（沒有 db 時引擎會讀 CSV，數字相同）")

    print("\n== 3. 正式版數字")
    ok("results/portfolio_prepared.pkl", (RESULTS / "portfolio_prepared.pkl").exists(), "沒有的話照 HANDOFF 第 3 節重建")
    import param_opt as po, robust_study as rs, daily_run as dr, portfolio_study as ps
    import rules_research as rr
    po.setup(); G = rs.G; d = G["dates"]; po.apply(dr.FINAL); kw = po.to_kw(dr.FINAL)
    ok("回測日曆截止日", str(d[-1].date()) == EXPECT["回測截止日"], f"{d[-1].date()}（rules_research.BACKTEST_END={rr.BACKTEST_END}，EXPECT {EXPECT['回測截止日']}）；"
       f"全池最新完成日 {rs.backtest_end().date()}")
    ok("引擎股票池", len(G["sub"]) == 47, f"{len(G['sub'])} 檔（2026-11-01 起半導體＋電腦及週邊；之前電子 90 檔）")
    for key, s in (("2016-12-28 起期末萬", 1), ("2017-01-03 起期末萬", d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0])):
        v = round(ps.run(G["sub"], G["member"], d, capital=5e6, start_n=s, **kw)[1].iloc[-1] * 500)
        ok(key, abs(v - EXPECT[key]) <= 1, f"{v}（預期 {EXPECT[key]}）")
    out = subprocess.run([sys.executable, "daily_run.py"], capture_output=True, text=True, cwd=ROOT).stdout
    n_hold = sum(1 for ln in out.split("【明天")[0].split("【目前持股】")[-1].splitlines() if ln[:4].isdigit())
    ok("daily_run.py 執行", "目前總資產" in out and "開盤要做的事" in out, f"持股 {n_hold} 檔（預期 {EXPECT['持股檔數']}）")
    ok("daily_run 持股檔數", n_hold == EXPECT["持股檔數"])
    if full:
        po.CONFIGS["check"] = dr.FINAL
        m = po.evaluate(["check"], "check").loc["check"]
        for k in ("前7年", "延續", "單獨", "三段平均", "最差10最小", "標準差平均"):
            ok(f"20 情境 {k}", abs(float(m[k]) - EXPECT[k]) <= 0.05, f"{float(m[k]):.2f}（預期 {EXPECT[k]}）")
        for f in RESULTS.glob("param_opt_check_*"):
            f.unlink()
    print("\n==", "全部通過" if not fails else f"未通過 {len(fails)} 項：{fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(full="--full" in sys.argv))
