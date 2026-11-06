"""籌碼每日更新與報表：全市場融資餘額、全市場三大法人、個股融資／三大法人（股票池 ∪ 持股 ∪ 觀察名單）。

2026-11-06 使用者：「搜尋之前的每天融資餘額，在報告中列出減少百分比、減少的數量、餘額多少；每日的三大法人買賣超股票也詳盡記錄。」
背景：MARKET_BOTTOM_STUDY.md 的大盤落底規則用到全市場融資（20 日均 ÷ 240 日均 ≤ −8% 或離一年高點 ≤ −30%）；資料原本只抓到 2026-10-30。

資料：data/extra/<dataset>/<代號 或 ALL>.csv，與 fetch_bottom_extra.py 同格式，每天接著增量（逐日原始列就是「詳盡記錄」）。
  TaiwanStockTotalMarginPurchaseShortSale/ALL.csv   全市場融資券（張與金額）
  TaiwanStockTotalInstitutionalInvestors/ALL.csv     全市場三大法人買賣金額
  TaiwanStockPrice/TAIEX.csv                          加權指數成交金額（落底規則的放量條件）
  TaiwanStockMarginPurchaseShortSale/<sid>.csv        個股融資券
  TaiwanStockInstitutionalInvestorsBuySell/<sid>.csv  個股三大法人
  chips_table/<日期>.csv                              當天個股籌碼表（報表同內容）
FinMind 一次查全市場要贊助會員，所以逐檔抓：每天約 3 ＋ 2 × 檔數（約 50 檔 → 100 次）。
融資餘額證交所約 21:00 後才公布，所以 16:00 的 daily_update 只用磁碟上的資料印表（融資會是前一天），
Windows 排程 22:30 run_chips.ps1 跑 --update --report 補當天並把報告裡的籌碼段換掉。

用法：
  python chips_daily.py --update            # 增量抓到今天（需 FINMIND_TOKEN 環境變數）
  python chips_daily.py --report            # 用磁碟資料印籌碼報表 → my_reports/<今天>_籌碼.md，並替換 my_reports/<今天>.md 的籌碼段
  python chips_daily.py --update --report
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
EXTRA = ROOT / "data" / "extra"
REPORTS = ROOT / "my_reports"
API = "https://api.finmindtrade.com/api/v4/data"
TW = timezone(timedelta(hours=8))
MARK_S, MARK_E = "<!-- chips start -->", "<!-- chips end -->"
OVERLAP_DAYS = 10          # 增量抓時往前多抓幾天，重疊的以新資料為準（FinMind 會事後修正）
WAIT_LIMIT, MAX_WAIT = 300, 3600
BLUE_IDS = ("0050", "0051")


def today_tw():
    return datetime.now(TW).date().isoformat()


# ---------------------------------------------------------------- 抓資料
class FM:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.calls = 0

    def get(self, dataset, data_id, start, end):
        p = {"dataset": dataset, "start_date": start, "end_date": end}
        if data_id:
            p["data_id"] = data_id
        waited = 0
        while True:
            try:
                r = self.s.get(API, params=p, timeout=60)
                body = r.json()
            except (requests.RequestException, ValueError) as e:
                print(f"    連線錯誤 {e}，30 秒後重試", flush=True)
                time.sleep(30)
                continue
            st = body.get("status", r.status_code)
            if st == 402 or r.status_code == 402:
                if waited >= MAX_WAIT:
                    raise RuntimeError("FinMind 流量限制等超過 60 分鐘，放棄")
                print(f"    FinMind 流量限制（已抓 {self.calls} 次），5 分鐘後續抓", flush=True)
                time.sleep(WAIT_LIMIT)
                waited += WAIT_LIMIT
                continue
            if st != 200:
                raise RuntimeError(f"{dataset} {data_id}: {st} {body.get('msg', '')}")
            self.calls += 1
            time.sleep(0.3)
            return pd.DataFrame(body.get("data", []))


def _merge(path, new, keys):
    """接到既有檔：重疊的日子以新資料為準，依日期排序寫回。回傳新增的日數。"""
    if new is None or new.empty:
        return 0
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=new.columns)
    new = new.astype(str)
    cols = list(old.columns) if len(old.columns) else list(new.columns)
    for c in new.columns:
        if c not in cols:
            cols.append(c)
    out = pd.concat([old.reindex(columns=cols), new.reindex(columns=cols)], ignore_index=True)
    out = out.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    return len(set(new["date"]) - set(old["date"]))


def _last_date(path):
    if not path.exists():
        return None
    d = pd.read_csv(path, usecols=["date"], dtype=str)["date"]
    return d.max() if len(d) else None


def stock_ids():
    """股票池 ∪ 兩個帳戶持股 ∪ 觀察名單（daily_update.yahoo_ids 的集合）。"""
    sys.path.insert(0, str(ROOT))
    from portfolio_electronics import POOL
    ids = set(map(str, POOL))
    try:
        import daily_update as du
        ids |= set(map(str, du.yahoo_ids()))
    except Exception as e:  # noqa: BLE001
        print(f"  觀察名單取不到（{e}），只抓股票池", flush=True)
    return sorted(ids)


def update(token, today=None, ids=None):
    today = today or today_tw()
    fm = FM(token)
    log = []
    jobs = [("TaiwanStockTotalMarginPurchaseShortSale", None, ["date", "name"]),
            ("TaiwanStockTotalInstitutionalInvestors", None, ["date", "name"]),
            ("TaiwanStockPrice", "TAIEX", ["date"])]
    for sid in (ids or stock_ids()):
        jobs.append(("TaiwanStockMarginPurchaseShortSale", sid, ["date", "stock_id"]))
        jobs.append(("TaiwanStockInstitutionalInvestorsBuySell", sid, ["date", "stock_id", "name"]))
    for ds, sid, keys in jobs:
        path = EXTRA / ds / f"{sid or 'ALL'}.csv"
        last = _last_date(path)
        if last == today:
            continue
        start = (pd.Timestamp(last) - pd.Timedelta(days=OVERLAP_DAYS)).strftime("%Y-%m-%d") if last else "2005-01-01"
        new = fm.get(ds, sid, start, today)
        n = _merge(path, new, keys)
        if n:
            log.append(f"{ds.replace('TaiwanStock', '')} {sid or 'ALL'} +{n} 日")
    # 0050／0051 不在 daily_update 的名單，落底規則的「績優股跌深」要用（2026-11-06 發現停在 10-30，報表 −9.9% 是舊的）。
    # 走 update_universe_finmind 整檔重抓（每檔 7 次），還原價才會含除息、分割。
    stale = [s for s in BLUE_IDS if _last_date(ROOT / "data" / "universe" / "prices" / f"{s}.csv") != _last_date(ROOT / "data" / "TAIEX.csv")]
    if stale:
        subprocess.run([sys.executable, "update_universe_finmind.py", "--only", *stale, "--skip-taiex"], cwd=ROOT, check=True)
    print(f"籌碼更新：FinMind 請求 {fm.calls} 次；{len(log)} 個檔有新日子；重抓 {', '.join(stale) or '無'}", flush=True)
    return dict(calls=fm.calls, log=log)


# ---------------------------------------------------------------- 報表
def _fmt(x, nd=1, pct=False, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    return s + ("%" if pct else "")


def market_margin():
    p = EXTRA / "TaiwanStockTotalMarginPurchaseShortSale" / "ALL.csv"
    df = pd.read_csv(p, parse_dates=["date"])
    money = df[df["name"] == "MarginPurchaseMoney"].drop_duplicates("date", keep="last").set_index("date")["TodayBalance"].astype(float).sort_index() / 1e8
    lots = df[df["name"] == "MarginPurchase"].drop_duplicates("date", keep="last").set_index("date")["TodayBalance"].astype(float).sort_index() / 1e3
    short = df[df["name"] == "ShortSale"].drop_duplicates("date", keep="last").set_index("date")["TodayBalance"].astype(float).sort_index() / 1e3
    d = money.index[-1]
    m = money.iloc[-1]
    hi = money.iloc[-250:].max(); hi_d = money.iloc[-250:].idxmax()
    ma20, ma240 = money.iloc[-20:].mean(), money.iloc[-240:].mean()
    rows = []
    for k, lab in ((1, "1 日"), (5, "5 日"), (20, "20 日"), (60, "60 日")):
        if len(money) > k:
            prev = money.iloc[-1 - k]
            rows.append(f"| 較 {lab}前 | {_fmt(m - prev, 1, sign=True)} 億 | {_fmt((m / prev - 1) * 100, 2, pct=True, sign=True)} | {_fmt(prev, 0)} 億（{money.index[-1 - k]:%m-%d}） |")
    L = [f"**全市場融資餘額（{d:%Y-%m-%d}）：{_fmt(m, 0)} 億元、{_fmt(lots.iloc[-1], 0)} 萬張**（融券 {_fmt(short.iloc[-1] / 10, 1)} 萬張）", "",
         "| 比較 | 增減金額 | 增減 | 基準 |", "|---|---|---|---|"] + rows + [
         f"| 離一年最高 | {_fmt(m - hi, 1, sign=True)} 億 | {_fmt((m / hi - 1) * 100, 1, pct=True, sign=True)} | {_fmt(hi, 0)} 億（{hi_d:%Y-%m-%d}） |",
         f"| 20 日均 ÷ 240 日均 | | {_fmt((ma20 / ma240 - 1) * 100, 1, pct=True, sign=True)} | 落底規則門檻 ≤ −8%（或離高 ≤ −30%） |", ""]
    L += ["最近 10 個交易日：", "", "| 日期 | 餘額（億） | 日增減（億） | 日增減 |", "|---|---|---|---|"]
    for i in range(-10, 0):
        if len(money) + i - 1 < 0:
            continue
        L.append(f"| {money.index[i]:%m-%d} | {_fmt(money.iloc[i], 0)} | {_fmt(money.iloc[i] - money.iloc[i - 1], 1, sign=True)} | {_fmt((money.iloc[i] / money.iloc[i - 1] - 1) * 100, 2, pct=True, sign=True)} |")
    L.append("")
    return L, d


def bottom_rule_status():
    """MARKET_BOTTOM_STUDY 四條件今天各自成立否（market_bottom_study.rule 的拆解）。"""
    try:
        import market_bottom_study as mbs
        t = mbs.load()
        # mbs.load 經由資料庫讀 0050 且 ffill 5 天：資料庫沒重建時舊價會被當成今天。這裡直接讀 csv，還原價算跌幅。
        px0050 = pd.read_csv(ROOT / "data" / "universe" / "prices" / "0050.csv", parse_dates=["date"]).set_index("date")["adj_close"]
        t["p0050"] = px0050.reindex(t.index).ffill(limit=1)
        f = mbs.features(t)
        _, bdd, _ = mbs.blue(t, f, "0050")
        mg = t["margin"]
        ma = mg.rolling(20).mean() / mg.rolling(240).mean() - 1
        panic_day = (f["ret1"] <= -0.015) & (f["mo_ratio"] >= 1.3)
        p60 = panic_day.rolling(60).max().astype(bool)
        last_panic = panic_day[panic_day].index.max() if panic_day.any() else None
        i = -1
        c1 = bool((f["m_hi"].iloc[i] <= -0.30) or (ma.iloc[i] <= -0.08))
        c2 = bool(bdd.iloc[i] <= -0.20)
        c3 = bool(p60.iloc[i])
        c4 = bool(f["near_low60"].iloc[i] <= 0.12)
        ok = lambda b: "✅" if b else "—"  # noqa: E731
        d = f.index[i]
        lag = [n for n, x in (("0050", px0050), ("成交金額", t["money"]), ("融資", mg.where(mg.diff() != 0))) if x.dropna().index[-1] < d]
        pool = bool(mbs.pool_rule(t, f).iloc[i])
        L = [f"**大盤落底規則（MARKET_BOTTOM_STUDY，{f.index[i]:%Y-%m-%d}）：{'四條件全部成立 → 訊號' if all([c1, c2, c3, c4]) else '未成立'}**", "",
             "| 條件 | 今天 | 門檻 | 成立 |", "|---|---|---|---|",
             f"| 融資大減 | 離一年高 {_fmt(f['m_hi'].iloc[i] * 100, 1, pct=True, sign=True)}；20 日均÷240 日均 {_fmt(ma.iloc[i] * 100, 1, pct=True, sign=True)} | ≤ −30% 或 ≤ −8% | {ok(c1)} |",
             f"| 0050 跌深 | 離一年高 {_fmt(bdd.iloc[i] * 100, 1, pct=True, sign=True)} | ≤ −20% | {ok(c2)} |",
             f"| 近 60 日放量下跌 | 最近一次 {last_panic.date() if last_panic is not None else '—'} | 跌 ≥1.5% 且額 ≥60 日均 1.3 倍 | {ok(c3)} |",
             f"| 離 60 日低點 | {_fmt(f['near_low60'].iloc[i] * 100, 1, pct=True, sign=True)} | ≤ 12% | {ok(c4)} |", "",
             f"股票池止跌版（第二條規則）：{'成立' if pool else '未成立'}。" + (f" **注意：{'、'.join(lag)} 還沒有 {d:%m-%d} 的資料，上表該列是舊值。**" if lag else ""), ""]
        return L
    except Exception as e:  # noqa: BLE001
        return [f"（落底規則狀態算不出來：{e}）", ""]


def _streak(s):
    """連續同號天數（正＝連買，負＝連賣）。"""
    s = s.dropna()
    if s.empty:
        return 0
    sign = np.sign(s.iloc[-1])
    n = 0
    for v in s.iloc[::-1]:
        if np.sign(v) == sign and v != 0:
            n += 1
        else:
            break
    return int(n * sign)


def market_inst():
    p = EXTRA / "TaiwanStockTotalInstitutionalInvestors" / "ALL.csv"
    df = pd.read_csv(p, parse_dates=["date"])
    df["net"] = (df["buy"].astype(float) - df["sell"].astype(float)) / 1e8
    piv = df.drop_duplicates(["date", "name"], keep="last").pivot(index="date", columns="name", values="net").sort_index()
    d = piv.index[-1]
    L = [f"**全市場三大法人買賣超（{d:%Y-%m-%d}，億元）**", "", "| 法人 | 當日 | 近 5 日 | 近 20 日 | 連續 |", "|---|---|---|---|---|"]
    groups = [("外資（含外資自營）", ["Foreign_Investor", "Foreign_Dealer_Self"]), ("投信", ["Investment_Trust"]),
              ("自營商（自行＋避險）", ["Dealer_self", "Dealer_Hedging"]), ("合計", ["total"])]
    for lab, cols in groups:
        cols = [c for c in cols if c in piv.columns]
        if not cols:
            continue
        s = piv[cols].sum(axis=1)
        st = _streak(s)
        L.append(f"| {lab} | {_fmt(s.iloc[-1], 1, sign=True)} | {_fmt(s.iloc[-5:].sum(), 1, sign=True)} | {_fmt(s.iloc[-20:].sum(), 1, sign=True)} | {'連買' if st > 0 else '連賣'} {abs(st)} 日 |")
    L.append("")
    return L, d


def stock_table(ids, names, holdings):
    rows = []
    d_inst, d_mg = None, None
    for sid in ids:
        pm = EXTRA / "TaiwanStockMarginPurchaseShortSale" / f"{sid}.csv"
        pi = EXTRA / "TaiwanStockInstitutionalInvestorsBuySell" / f"{sid}.csv"
        pp = ROOT / "data" / "universe" / "prices" / f"{sid}.csv"
        r = dict(代號=sid, 名稱=names.get(sid, ""), 持有="★" if sid in holdings else "")
        if pp.exists():
            px = pd.read_csv(pp, usecols=["date", "close"]).dropna()
            r["收盤"] = float(px["close"].iloc[-1])
        if pm.exists():
            m = pd.read_csv(pm, parse_dates=["date"]).drop_duplicates("date", keep="last").set_index("date").sort_index()
            bal = m["MarginPurchaseTodayBalance"].astype(float)
            d_mg = max(d_mg, bal.index[-1]) if d_mg is not None else bal.index[-1]
            r["融資日期"] = bal.index[-1].strftime("%m-%d")
            r["融資餘額(張)"] = bal.iloc[-1]
            r["融資日增減(張)"] = bal.iloc[-1] - bal.iloc[-2] if len(bal) > 1 else np.nan
            r["融資5日%"] = (bal.iloc[-1] / bal.iloc[-6] - 1) * 100 if len(bal) > 5 and bal.iloc[-6] > 0 else np.nan
            r["融資20日%"] = (bal.iloc[-1] / bal.iloc[-21] - 1) * 100 if len(bal) > 20 and bal.iloc[-21] > 0 else np.nan
            hi = bal.iloc[-250:].max()
            r["融資離一年高%"] = (bal.iloc[-1] / hi - 1) * 100 if hi > 0 else np.nan
            r["融券餘額(張)"] = float(m["ShortSaleTodayBalance"].iloc[-1])
        if pi.exists():
            x = pd.read_csv(pi, parse_dates=["date"])
            x["net"] = (x["buy"].astype(float) - x["sell"].astype(float)) / 1000
            piv = x.drop_duplicates(["date", "name"], keep="last").pivot(index="date", columns="name", values="net").sort_index().fillna(0)
            d_inst = max(d_inst, piv.index[-1]) if d_inst is not None else piv.index[-1]
            z = pd.Series(0.0, index=piv.index)
            fo = piv.get("Foreign_Investor", z) + piv.get("Foreign_Dealer_Self", z)
            it = piv.get("Investment_Trust", z)
            de = piv.get("Dealer_self", z) + piv.get("Dealer_Hedging", z)
            tot = fo + it + de
            r["法人日期"] = piv.index[-1].strftime("%m-%d")
            r["外資(張)"] = fo.iloc[-1]; r["投信(張)"] = it.iloc[-1]; r["自營(張)"] = de.iloc[-1]; r["三大合計(張)"] = tot.iloc[-1]
            r["外資5日(張)"] = fo.iloc[-5:].sum(); r["投信5日(張)"] = it.iloc[-5:].sum(); r["合計20日(張)"] = tot.iloc[-20:].sum()
            r["外資連續"] = _streak(fo); r["投信連續"] = _streak(it)
        rows.append(r)
    t = pd.DataFrame(rows)
    if "三大合計(張)" in t:
        t = t.sort_values("三大合計(張)", ascending=False)
    return t.reset_index(drop=True), d_inst, d_mg


def _table_md(t):
    cols = ["持有", "代號", "名稱", "收盤", "融資餘額(張)", "融資日增減(張)", "融資5日%", "融資20日%", "融資離一年高%",
            "外資(張)", "投信(張)", "自營(張)", "三大合計(張)", "外資5日(張)", "投信5日(張)", "合計20日(張)", "外資連續", "投信連續"]
    cols = [c for c in cols if c in t.columns]
    L = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r.get(c)
            if c in ("持有", "代號", "名稱"):
                cells.append(str(v) if pd.notna(v) else "")
            elif c in ("外資連續", "投信連續"):
                cells.append("" if pd.isna(v) else (f"買{int(v)}" if v > 0 else f"賣{int(-v)}" if v < 0 else "0"))
            elif c == "收盤":
                cells.append(_fmt(v, 1))
            elif c.endswith("%"):
                cells.append(_fmt(v, 1, sign=True))
            else:
                cells.append(_fmt(v, 0, sign=c != "融資餘額(張)"))
        L.append("| " + " | ".join(cells) + " |")
    return L


def _holdings():
    out = set()
    try:
        import daily_update as du
        for _, acc_f, hold_f in du.ACCOUNTS:
            if acc_f.exists():
                h = ROOT / json.loads(acc_f.read_text(encoding="utf-8")).get("holdings", hold_f.name)
                if h.exists():
                    out |= set(pd.read_csv(h, dtype=str)["代號"])
    except Exception:  # noqa: BLE001
        pass
    return out


def text(today=None):
    """籌碼段全文（含標記），給 daily_update 直接接在報告後面。"""
    today = today or today_tw()
    names = pd.read_csv(ROOT / "data" / "universe" / "constituents.csv", dtype=str).drop_duplicates("stock_id").set_index("stock_id")["name"].to_dict()
    holdings = _holdings()
    ids = sorted({p.stem for p in (EXTRA / "TaiwanStockInstitutionalInvestorsBuySell").glob("*.csv")} | holdings)
    L = [MARK_S, "## 籌碼（融資餘額、三大法人）", ""]
    try:
        a, _ = market_margin(); L += a
    except Exception as e:  # noqa: BLE001
        L += [f"（全市場融資讀不到：{e}）", ""]
    L += bottom_rule_status()
    try:
        b, _ = market_inst(); L += b
    except Exception as e:  # noqa: BLE001
        L += [f"（全市場三大法人讀不到：{e}）", ""]
    t, d_inst, d_mg = stock_table(ids, names, holdings)
    (EXTRA / "chips_table").mkdir(parents=True, exist_ok=True)
    t.to_csv(EXTRA / "chips_table" / f"{today}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    L += [f"**個股籌碼（股票池 ∪ 持股；法人到 {d_inst.date() if d_inst is not None else '—'}、融資到 {d_mg.date() if d_mg is not None else '—'}；單位張；依三大法人當日合計排序；★＝持有）**", ""]
    L += _table_md(t)
    L += ["", f"逐日原始資料：data/extra/TaiwanStockMarginPurchaseShortSale/、TaiwanStockInstitutionalInvestorsBuySell/（每檔一個 csv）；當天表：data/extra/chips_table/{today}.csv", MARK_E]
    return L


def write_report(today=None):
    today = today or today_tw()
    L = text(today)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{today}_籌碼.md").write_text(f"# {today} 籌碼\n\n" + "\n".join(L[1:-1]) + "\n", encoding="utf-8")
    rep = REPORTS / f"{today}.md"
    if rep.exists():
        s = rep.read_text(encoding="utf-8")
        block = "\n".join(L)
        if MARK_S in s and MARK_E in s:
            s = s[:s.index(MARK_S)] + block + s[s.index(MARK_E) + len(MARK_E):]
        else:
            s = s.rstrip("\n") + "\n\n" + block + "\n"
        rep.write_text(s, encoding="utf-8")
    print("\n".join(L[1:-1]))
    print(f"\n已存：{REPORTS / f'{today}_籌碼.md'}" + (f"；已更新 {rep} 的籌碼段" if rep.exists() else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--date", default=None)
    a = ap.parse_args()
    today = a.date or today_tw()
    if a.update:
        tok = os.environ.get("FINMIND_TOKEN")
        if not tok:
            raise SystemExit("沒有 FINMIND_TOKEN")
        update(tok, today)
    if a.report or not a.update:
        write_report(today)


if __name__ == "__main__":
    main()
