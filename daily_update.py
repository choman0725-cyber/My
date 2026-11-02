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

兩段式（2026-11-02 使用者：FinMind 收盤後要等一陣子才有當天資料）：
  13:35 python daily_update.py --source yahoo：只抓庫存＋觀察股（yahoo_ids）的 Yahoo 股市當天日線當暫定資料（daily_yahoo.py），重建後給暫定建議，
        存 my_reports/<日期>_暫定.md；不需要 FINMIND_TOKEN；暫定列記在 data/provisional.json，不要 commit。
  16:00 python daily_update.py（FinMind）：等 FinMind 有今天的資料 → 拿掉暫定列 → 照原流程增量更新 →
        比對 Yahoo vs FinMind（以 FinMind 為準）→ 重建、正式建議存 my_reports/<日期>.md，並標出與暫定版建議是否相同。
"""
import argparse
import json
import os
import pickle
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import update_universe_finmind as uf

ROOT = uf.ROOT
LOOKBACK_DAYS, FUND_DAYS = 14, 400
RETRY_MIN, GIVE_UP = 10, "18:00"
YAHOO_GIVE_UP = "15:00"
TW = timezone(timedelta(hours=8))                  # 一律用台北時間（電腦時區設錯也不會抓錯日期／重試截止時間）


def now_tw():
    return datetime.now(TW).replace(tzinfo=None)
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
    mem = ps.membership(cons, pd.DatetimeIndex([pd.Timestamp(now_tw().date())]))
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


def account_sections():
    lines = []
    for label, acc_f, hold_f in ACCOUNTS:
        if not acc_f.exists():
            continue
        hold_ = ROOT / json.loads(acc_f.read_text(encoding="utf-8")).get("holdings", hold_f.name)
        lines += [f"## {label}", "", "```", advice(acc_f, hold_f).rstrip(), "```", "",
                  f"成交後請更新 {hold_.name}（代號,進場日,股數,成本,首買價…）與 {acc_f.name} 的 cash。", ""]
    return lines


def actions(text):
    """報告裡每個帳戶的「明天開盤要做的事」段落（比對暫定版與正式版用）。"""
    out = {}
    for part in ("\n" + text).split("\n## ")[1:]:
        a_ = part.find("【明天")
        out[part.splitlines()[0]] = part[a_:part.find("【觀察", a_)].strip() if a_ >= 0 else ""
    return out


def yahoo_ids(margin=0.9):
    """13:35 只抓「庫存＋觀察股」（2026-11-02 使用者；16:00 FinMind 照舊抓整個股票池）：
    各帳戶持股檔裡的代號 ∪ 股票池中最後一天在成分股內、預估殖利率 ≥ 門檻 × margin 的股票
    （觀察名單的條件；乘 0.9 是把今天可能跌進門檻的也抓進來）。"""
    import numpy as np
    import daily_run as dr
    import param_opt as po
    import robust_study as rs
    ids = set()
    for _, acc_f, hold_f in ACCOUNTS:
        if acc_f.exists():
            h = ROOT / json.loads(acc_f.read_text(encoding="utf-8")).get("holdings", hold_f.name)
            if h.exists():
                ids |= set(pd.read_csv(h, dtype={"代號": str})["代號"])
    po.setup(live=True); po.apply(dr.FINAL); G = rs.G; p = len(G["dates"]) - 1
    thr = po.buy_threshold(dr.FINAL)
    for sid, d in G["sub"].items():
        y = d["yield"][p]
        growth = bool(d.get("growth_flag", np.zeros(p + 1, bool))[p])
        gate = d["own_median"][p] * dr.FINAL["growth_rel"][0] if growth else thr[p]
        if G["member"][sid].iloc[p] and not np.isnan(y) and not np.isnan(gate) and y >= gate * margin:
            ids.add(sid)
    return sorted(ids)


def main_yahoo(a, today):
    import daily_yahoo as dy
    ids = yahoo_ids()
    print(f"Yahoo 只抓庫存＋觀察股 {len(ids)} 檔：{', '.join(ids)}", flush=True)
    t0 = now_tw()
    while True:
        info = dy.apply(today, ids)
        if info is not None or a.no_wait or now_tw().strftime("%H:%M") >= YAHOO_GIVE_UP:
            break
        print(f"{now_tw():%H:%M} Yahoo 還沒有今天的收盤，5 分鐘後重試", flush=True)
        time.sleep(300)
    REPORTS.mkdir(exist_ok=True)
    rep = REPORTS / f"{today}_暫定.md"
    if info is None:
        msg = f"# {today} 沒有新的交易日資料（Yahoo）\n\n加權指數沒有今天的收盤（休市，或 Yahoo 到 {YAHOO_GIVE_UP} 仍未更新）。\n"
        rep.write_text(msg, encoding="utf-8"); print(msg)
        return 0
    import daily_fast
    fast = daily_fast.fast_rebuild(list(json.loads(dy.PROV.read_text(encoding="utf-8"))["sids"]))
    if not fast:                                    # 快取日曆對不上（例如前一天沒跑正式版）→ 全部重建
        rebuild()
    lines = [f"# {today} 暫定建議（Yahoo 股市收盤資料；16:00 以 FinMind 驗證後的正式版為準）", "",
             f"- Yahoo 接上今天的股票 {info['n']} 檔；加權指數收盤 {info['taiex']:,.2f}；"
             f"{'快速重建（只重算這幾檔，其他股票沿用前一天）' if fast else '全部重建'}；耗時 {(now_tw() - t0).seconds // 60} 分鐘",
             f"- Yahoo 沒有今天資料：{', '.join(info['miss']) or '無'}",
             f"- 原本就沒到前一個交易日（不補、等 FinMind）：{', '.join(info['skip']) or '無'}",
             "- 今天若有除權息／減資，暫定資料還沒調整，以 16:00 正式版為準", ""]
    if not a.skip_advice:
        lines += account_sections()
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存：{rep}")
    return 0


def finmind_ready(fm, today):
    """FinMind 的 TAIEX 有沒有比「非暫定」資料更新的日子。"""
    import daily_yahoo as dy
    last = pd.read_csv(ROOT / "data" / "TAIEX.csv")["date"].iloc[-1]
    if dy.PROV.exists():
        last = json.loads(dy.PROV.read_text(encoding="utf-8"))["prev"]
    start = (pd.Timestamp(today) - pd.Timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    t = uf.finmind_price_frame(fm.get("TaiwanStockPrice", "TAIEX", start, today))
    return not t.empty and t["date"].max().strftime("%Y-%m-%d") > last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wait", action="store_true", help="今天資料還沒出來就直接結束，不重試")
    ap.add_argument("--skip-advice", action="store_true")
    ap.add_argument("--source", choices=["finmind", "yahoo"], default="finmind", help="yahoo＝13:35 暫定資料（見檔頭說明）")
    a = ap.parse_args()
    today = now_tw().date().isoformat()
    if a.source == "yahoo":
        return main_yahoo(a, today)
    import daily_yahoo as dy
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise SystemExit("沒有 FINMIND_TOKEN")
    t0 = now_tw()
    info, prov = None, None
    while True:
        fm = uf.FinMind(token, refresh=True)        # 重試時不能讀到「資料還沒出來」那次的快取
        if finmind_ready(fm, today):
            prov = dy.strip()                       # FinMind 有了才拿掉 Yahoo 暫定列（以 FinMind 為準）
            info = update(fm, today)
        if info is not None or a.no_wait or now_tw().strftime("%H:%M") >= GIVE_UP:
            break
        print(f"{now_tw():%H:%M} FinMind 還沒有今天的資料，{RETRY_MIN} 分鐘後重試", flush=True)
        time.sleep(RETRY_MIN * 60)
    REPORTS.mkdir(exist_ok=True)
    rep = REPORTS / f"{today}.md"
    if info is None:
        msg = f"# {today} 沒有新的交易日資料\n\nTAIEX 沒有比現有資料更新的日子（休市，或 FinMind 到 {GIVE_UP} 仍未更新）。建議沿用前一份" + \
              ("；Yahoo 暫定資料仍留在 data/provisional.json，暫定建議見當天 _暫定.md" if dy.PROV.exists() else "") + "。\n"
        rep.write_text(msg, encoding="utf-8"); print(msg)
        return 0
    rebuild()
    lines = [f"# {today} 每日更新與建議", "",
             f"- 新交易日：{', '.join(info['new_days'])}；{info['n']} 檔中 {info['appended']} 檔接上新資料，FinMind 請求 {info['calls']} 次，耗時 {(now_tw() - t0).seconds // 60} 分鐘",
             f"- 重疊日驗證不一致而整段重抓：{', '.join(info['verify_fail']) or '無'}",
             f"- 除權息／減資／分割而整段重抓：{', '.join(info['events']) or '無'}",
             f"- 新進池：{', '.join(info['report']) or '無'}",
             f"- 沒有到最新一天：{', '.join(info['lag']) or '無'}", ""]
    if prov:
        bad, vol, none = dy.verify(prov)
        lines += [f"- Yahoo 暫定資料驗證（{prov['date']}，{len(prov['sids'])} 檔，以 FinMind 為準）：價格不一致 {len(bad)} 檔"
                  + (f"：{'；'.join(bad)}" if bad else "") + f"；成交量差 >1% {vol} 檔；FinMind 沒有這天：{', '.join(none) or '無'}", ""]
        dy.PROV.unlink()
    if not a.skip_advice:
        lines += account_sections()
        pre = REPORTS / f"{today}_暫定.md"
        if prov and pre.exists():
            old, new = actions(pre.read_text(encoding="utf-8")), actions("\n".join(lines))
            lines += ["## 與 13:35 暫定建議比較", ""] + [f"- {k}：{'相同' if old.get(k) == v else '**不同，以這份為準**'}" for k, v in new.items()] + [""]
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存：{rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
