"""每日增量更新＋明天的建議（2026-11-01 使用者：整段重抓驗證過一次後，每天 13:35 只更新最近幾天、給建議）。

名單＝股票池（portfolio_electronics.ELECTRONICS）∪ 當天 0050／0056 成分股（市場殖利率中位數要用）＋ TAIEX。
  1. 沒有日線檔的（新進池）→ update_universe_finmind.py --only 整段抓。
  2. 每檔抓最近 LOOKBACK_DAYS 天日線：與現有檔重疊的日子逐日比對 OHLCV，不一致（FinMind 改了資料）→ 整段重抓那一檔；
     一致 → 接上新的日子（新日子之後還沒有除權息，adj_close＝close）。
  3. 除權息結果、減資、面額分割：新的日子裡有事件 → 整段重抓那一檔（還原價、股數事件都要重算）。
  4. 財報 EPS、股利政策：抓最近 FUND_DAYS 天，合併進 eps_all.csv、dividend_all.csv。
  5. TAIEX 接上新的日子；build_db.py；重建 results/portfolio_prepared.pkl、param_opt_sigs.pkl；
     daily_run.py --holdings（帳戶設定讀 my_account.json，持股讀 my_holdings.csv，兩者都不進 git）。
今天的資料還沒出來（FinMind 通常收盤後一段時間才更新）→ 每 RETRY_MIN 分鐘重試，到 GIVE_UP 為止。

用法：python daily_update.py [--no-wait] [--skip-advice]
需要環境變數 FINMIND_TOKEN。建議存在 my_reports/<日期>.md。
"""
import argparse
import json
import os
import pickle
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd

import update_universe_finmind as uf

ROOT = uf.ROOT
LOOKBACK_DAYS, FUND_DAYS = 14, 400
RETRY_MIN, GIVE_UP = 10, "18:00"
REPORTS = ROOT / "my_reports"
ACCOUNT = ROOT / "my_account.json"
HOLDINGS = ROOT / "my_holdings.csv"
# 帳戶清單：(名稱, 設定檔, 預設持股檔)；設定檔不存在就略過。設定檔可用 "holdings" 指定持股檔（2026-11-02 加第二帳戶）
ACCOUNTS = [("帳戶 A（主帳戶）", ACCOUNT, HOLDINGS), ("帳戶 B（第二帳戶）", ROOT / "my_account2.json", ROOT / "my_holdings_account2.csv")]
PRICE_KEYS = ["open", "high", "low", "close", "volume"]


def universe():
    import portfolio_electronics as pe
    import portfolio_study as ps
    cons = pd.read_csv(uf.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    mem = ps.membership(cons, pd.DatetimeIndex([pd.Timestamp(date.today())]))
    return sorted({s for s, v in mem.items() if v.iloc[-1]} | set(pe.ELECTRONICS))


def run(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True,
                       env={**os.environ, "PYTHONUTF8": "1"}, **kw)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit(f"失敗：{' '.join(cmd)}")
    return r.stdout


def taiex_new_days(fm, start, end):
    tp = ROOT / "data" / "TAIEX.csv"
    old = pd.read_csv(tp, parse_dates=["date"])
    t = uf.finmind_price_frame(fm.get("TaiwanStockPrice", "TAIEX", start, end))
    add = t[t["date"] > old["date"].max()] if not t.empty else t
    return tp, old, add


def update(fm, today):
    ids = universe()
    start = (pd.Timestamp(today) - pd.Timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    fstart = (pd.Timestamp(today) - pd.Timedelta(days=FUND_DAYS)).strftime("%Y-%m-%d")
    tp, tai_old, tai_add = taiex_new_days(fm, start, today)
    if tai_add.empty:
        return None
    new_days = set(tai_add["date"])
    split_all = fm.get("TaiwanStockSplitPrice", "", uf.SPLIT_START, today, optional=True)
    full, appended, verify_fail, events, report = [], {}, [], [], []
    eps_new, div_new, res_new = [], [], []
    for sid in ids:
        path = uf.PRICES / f"{sid}.csv"
        if not path.exists():
            full.append(sid); report.append(f"{sid} 新進池：整段抓"); continue
        old = pd.read_csv(path)
        old_d = pd.to_datetime(old["date"])
        new = uf.finmind_price_frame(fm.get("TaiwanStockPrice", sid, start, today))
        res = fm.get("TaiwanStockDividendResult", sid, start, today)
        red = fm.get("TaiwanStockCapitalReductionReferencePrice", sid, start, today, optional=True)
        fin = fm.get("TaiwanStockFinancialStatements", sid, fstart, today)
        div = fm.get("TaiwanStockDividend", sid, fstart, today)
        if not fin.empty:
            eps_new.append(fin[fin["type"] == "EPS"][["stock_id", "date", "value"]])
        if not div.empty:
            div_new.append(div)
        if not res.empty:
            res_new.append(res)
        if new.empty:
            continue                                   # 停牌／下市：沒有新資料，保留現有檔
        last = old_d.max()
        sp = split_all[split_all["stock_id"] == sid] if not split_all.empty else split_all
        ev = [d for d, _ in uf.adjust_events(res, red, sp) if d > last]
        if ev:
            full.append(sid); events.append(f"{sid} 除權息／減資／分割 {', '.join(f'{d:%m-%d}' for d in ev)}"); continue
        o = old.assign(date=old_d).set_index("date")[PRICE_KEYS]
        n = new.set_index("date")[PRICE_KEYS]
        j = o.join(n, how="inner", rsuffix="_n")
        bad = [c for c in PRICE_KEYS if (j[c].astype(float) - j[f"{c}_n"].astype(float)).abs().max() > 1e-6] if len(j) else ["無重疊日"]
        if set(o.index[o.index >= pd.Timestamp(start)]) != set(n.index[n.index <= last]):
            bad.append("交易日不同")
        if bad:
            full.append(sid); verify_fail.append(f"{sid}（{'、'.join(bad)}）"); continue
        add = new[new["date"] > last]
        if add.empty:
            continue
        out = pd.concat([old, uf.build_prices(add, [])], ignore_index=True)     # 新日子之後沒有事件：adj_close＝close
        out.to_csv(path, index=False, lineterminator="\n")
        appended[sid] = len(add)
    for fname, parts, keys in (("eps_all.csv", eps_new, ["stock_id", "date"]),
                               ("dividend_all.csv", div_new, ["stock_id", "date", "year"]),
                               ("dividend_result_all.csv", res_new, ["stock_id", "date"])):
        out = uf.merge_table(uf.UNI / fname, pd.concat(parts, ignore_index=True) if parts else None, keys)
        out.to_csv(uf.UNI / fname, index=False, lineterminator="\n")
    out = pd.concat([tai_old, tai_add[tai_old.columns]], ignore_index=True).sort_values("date")
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(tp, index=False, lineterminator="\n")
    if full:
        run([sys.executable, "update_universe_finmind.py", "--only", *full, "--skip-taiex"])
    # manifest：只更新本次接上新日子的代號（整段重抓的由 update_universe_finmind 自己寫）
    mp = uf.UNI / "prices_manifest.csv"
    man = pd.read_csv(mp, dtype=str).set_index("stock_id")
    for sid in appended:
        p = uf.PRICES / f"{sid}.csv"
        dd = pd.read_csv(p, usecols=["date"])["date"]
        if sid in man.index:
            man.loc[sid, ["rows", "last_date", "sha256"]] = [str(len(dd)), dd.iloc[-1], uf.sha256(p)]
    man.reset_index().to_csv(mp, index=False, lineterminator="\n")
    lag = []                                           # 最近還在交易、這次卻沒到最新一天的（已下市的不列）
    for s in ids:
        if (uf.PRICES / f"{s}.csv").exists():
            last_ = pd.read_csv(uf.PRICES / f"{s}.csv", usecols=["date"])["date"].iloc[-1]
            if start <= last_ < max(new_days).strftime("%Y-%m-%d"):
                lag.append(s)
    return dict(new_days=sorted(d.strftime("%Y-%m-%d") for d in new_days), n=len(ids), appended=len(appended), full=full,
                verify_fail=verify_fail, events=events, report=report, lag=lag, calls=fm.calls)


def rebuild():
    run([sys.executable, "build_db.py"])
    for f in ("portfolio_prepared.pkl", "param_opt_sigs.pkl"):
        (ROOT / "results" / f).unlink(missing_ok=True)
    run([sys.executable, "-c",
         "import pickle,pandas as pd,portfolio_study as ps;from backtest import RESULTS,ROOT;"
         "cons=pd.read_csv(ps.UNI/'constituents.csv',dtype={'stock_id':str,'etf':str});"
         "cal=pd.read_csv(ROOT/'data'/'TAIEX.csv',parse_dates=['date'])['date'];"
         "dates=pd.DatetimeIndex(cal[cal>=ps.START-pd.Timedelta(days=5)]).sort_values();"
         "(RESULTS/'portfolio_prepared.pkl').write_bytes(pickle.dumps(ps.prepare(sorted(cons['stock_id'].unique()),dates)))"])


def advice(account=ACCOUNT, holdings=HOLDINGS):
    acc = json.loads(account.read_text(encoding="utf-8"))
    holdings = ROOT / acc["holdings"] if acc.get("holdings") else holdings
    cmd = [sys.executable, "daily_run.py", "--holdings", str(holdings), "--cash", str(acc["cash"])]
    if acc.get("slots3"):                           # my_account.json 寫 "slots3": true → 3 檔版
        cmd.append("--slots3")
    if acc.get("monthly"):
        cmd += ["--monthly", str(acc["monthly"])] + (["--monthly-from", acc["monthly_from"]] if acc.get("monthly_from") else [])
    out = run(cmd)
    return out[out.find("資料最後日期"):] if "資料最後日期" in out else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wait", action="store_true", help="今天資料還沒出來就直接結束，不重試")
    ap.add_argument("--skip-advice", action="store_true")
    a = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise SystemExit("沒有 FINMIND_TOKEN")
    today = date.today().isoformat()
    t0 = datetime.now()
    while True:
        fm = uf.FinMind(token, refresh=True)        # 重試時不能讀到「資料還沒出來」那次的快取
        info = update(fm, today)
        if info is not None or a.no_wait or datetime.now().strftime("%H:%M") >= GIVE_UP:
            break
        print(f"{datetime.now():%H:%M} FinMind 還沒有今天的資料，{RETRY_MIN} 分鐘後重試", flush=True)
        time.sleep(RETRY_MIN * 60)
    REPORTS.mkdir(exist_ok=True)
    rep = REPORTS / f"{today}.md"
    if info is None:
        msg = f"# {today} 沒有新的交易日資料\n\nTAIEX 沒有比現有資料更新的日子（休市，或 FinMind 到 {GIVE_UP} 仍未更新）。建議沿用前一份。\n"
        rep.write_text(msg, encoding="utf-8"); print(msg)
        return 0
    rebuild()
    lines = [f"# {today} 每日更新與建議", "",
             f"- 新交易日：{', '.join(info['new_days'])}；{info['n']} 檔中 {info['appended']} 檔接上新資料，FinMind 請求 {info['calls']} 次，耗時 {(datetime.now() - t0).seconds // 60} 分鐘",
             f"- 重疊日驗證不一致而整段重抓：{', '.join(info['verify_fail']) or '無'}",
             f"- 除權息／減資／分割而整段重抓：{', '.join(info['events']) or '無'}",
             f"- 新進池：{', '.join(info['report']) or '無'}",
             f"- 沒有到最新一天：{', '.join(info['lag']) or '無'}", ""]
    if not a.skip_advice:
        for label, acc_f, hold_f in ACCOUNTS:
            if not acc_f.exists():
                continue
            hold_ = ROOT / json.loads(acc_f.read_text(encoding="utf-8")).get("holdings", hold_f.name)
            lines += [f"## {label}", "", "```", advice(acc_f, hold_f).rstrip(), "```", "",
                      f"成交後請更新 {hold_.name}（代號,進場日,股數,成本,首買價…）與 {acc_f.name} 的 cash。", ""]
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存：{rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
