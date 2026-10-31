"""由元大投信每日 PCF（申購買回清單）重建 0050／0056 在 2006-01 ~ 2015 年的成分股，接到現有 constituents.csv 前面。

步驟：
  1. 抓 0050（2006-01-02 起）、0056（2007-12-20 上市起）到 2016-01-15 每個工作日的 PCF，快取在 data/universe/_pcf_cache/（不進 git）。
     元大網站的憑證鏈 Python 3.13 嚴格模式不接受（Missing Subject Key Identifier），所以用 curl 下載（curl 正常驗證憑證）。
  2. 每日持股 = 實物申購清單 ∪ 權重清單。個股除權息、暫停交易時會改現金替代而暫時不在清單裡，缺席 ≤ 20 個交易日補回。
  3. 同一次調整 ETF 會分幾天買賣（2013 年起明顯），相鄰 5 個交易日內的變動合併成一次；
     若該月第三個週五後首個交易日（指數生效日）落在首次變動日的前 3 ～ 後 2 個交易日內，生效日用指數生效日，否則用 PCF 首次變動日（特殊事件）。
  4. 只取現有名單第一期（0050 2015-09-21、0056 2015-12-21）之前的期間，與現有名單接上；接點差異會印出來檢查。

用法：python build_constituents_pcf.py            # 抓 PCF、重建並改寫 constituents.csv
      python build_constituents_pcf.py --dry-run  # 只印異動表
"""
import json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

UNI = Path(__file__).parent / "data" / "universe"
OUT = UNI / "_pcf_cache"
GAP = 20
ORIGINAL_START = {"0050": "2015-09-21", "0056": "2015-12-21"}  # 原名單第一期
URL = ("https://etfapi.yuantaetfs.com/ectranslation/api/bridge?APIType=ETFAPI&CompanyName=YUANTAFUNDS&PageName=/x"
       "&DeviceId=null&FuncId=PCF/Daily&AppName=ETF&Device=3&Platform=ETF&ticker={etf}&date={d}")
def one(job):
    etf, d = job
    f = OUT / f"{etf}_{d:%Y%m%d}.json"
    if f.exists(): return
    for k in range(5):
        try:
            r = subprocess.run(["curl", "-sS", "-f", "-m", "30", URL.format(etf=etf, d=f"{d:%Y%m%d}")],
                               capture_output=True, check=True, text=True)
            json.loads(r.stdout)
            f.write_text(r.stdout, encoding="utf-8"); return
        except Exception as e:
            time.sleep(2 ** k)
    print("fail", etf, d.date(), flush=True)


def fetch_all():
    OUT.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range("2006-01-02", "2016-01-15")
    jobs = [(e, d) for e in ("0050", "0056") for d in days if not (e == "0056" and d < pd.Timestamp("2007-12-20"))]
    with ThreadPoolExecutor(4) as ex:
        for i, _ in enumerate(ex.map(one, jobs)):
            if i % 500 == 0: print(f"PCF {i}/{len(jobs)}", flush=True)


def parse():
    import glob
    rows = []
    for f in sorted(glob.glob(str(OUT / "*.json"))):
        etf, d = Path(f).stem.split("_")
        try: j = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception: continue
        if not j or not j.get("PCF"): continue
        comp = (j.get("InKind") or {}).get("FundComposition") or []
        sw = (j.get("FundWeights") or {}).get("StockWeights") or []
        rows.append({"etf": etf, "req": d, "anndate": j["PCF"].get("anndate"), "trandate": j["PCF"].get("trandate"),
                     "inkind": tuple(sorted(c["stkcd"].strip() for c in comp)),
                     "names": {c["stkcd"].strip(): c["name"].strip() for c in comp},
                     "weights": tuple(sorted(w.get("code", "").strip() for w in sw)),
                     "cil": tuple(sorted(c["stkcd"].strip() for c in comp if c.get("cashinlieu") == "Y"))})
    df = pd.DataFrame(rows)
    return df


def periods(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["anndate"])
    df = df.drop_duplicates(["etf", "date"]).sort_values(["etf", "date"])
    out, names = [], {}
    for etf, g in df.groupby("etf"):
        g = g[g.apply(lambda r: len(r.inkind) + len(r.weights) > 0, axis=1)]
        days = list(g["date"])
        for n in g["names"]: names.update(n)
        stocks = sorted(set().union(*[set(a) | set(b) for a, b in zip(g.inkind, g.weights)]))
        pres = pd.DataFrame(False, index=days, columns=stocks)
        for d, a, b in zip(g.date, g.inkind, g.weights):
            pres.loc[d, list(set(a) | set(b))] = True
        for s in stocks:
            v = pres[s].values.copy(); idx = [i for i, x in enumerate(v) if x]
            for i, j in zip(idx, idx[1:]):
                if 1 < j - i <= GAP + 1: v[i:j] = True
            pres[s] = v
        prev = None
        for d, row in pres.iterrows():
            cur = frozenset(row.index[row.values])
            if cur != prev:
                out.append((etf, d, cur)); prev = cur
    res = pd.DataFrame(out, columns=["etf", "effective_date", "members"])
    res["n"] = res.members.map(len)
    return res, names


def finalize(per, names, pcf, dry):
    cons = pd.read_csv(UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    # 只保留原本（2016 PCF＋公告）整理的期間；重跑時去掉上次由本程式加的舊期間
    cons = cons[cons["effective_date"] >= cons["etf"].map(ORIGINAL_START)]
    cons["effective_date"] = pd.to_datetime(cons["effective_date"])
    cur_names = cons.drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    pcf = pcf.assign(date=pd.to_datetime(pcf["anndate"]))
    def review_day(d, days):
        """d 所在月份第三個星期五之後的第一個交易日。"""
        fr = pd.date_range(d.replace(day=1), periods=31, freq="D"); fr = fr[(fr.month == d.month) & (fr.weekday == 4)][2]
        return next(x for x in days if x > fr)

    rows, report = [], []
    for etf, g in per.groupby("etf"):
        days = sorted(pcf.loc[pcf.etf == etf, "date"].unique())
        pos = {d: i for i, d in enumerate(days)}
        g = g.sort_values("effective_date").reset_index(drop=True)
        # 把變動分群：相鄰變動相差 ≤ 5 個交易日為同一群
        clusters, cl = [], [0]
        for i in range(1, len(g)):
            if i > 1 and pos[g.effective_date[i]] - pos[g.effective_date[cl[-1]]] <= 5: cl.append(i)
            else:
                if i > 1: clusters.append(cl)
                cl = [i]
        clusters.append(cl)
        periods = [(g.effective_date[0], g.members[0], "PCF 起始（2006-01-02 已在名單）")]
        for cl in clusters:
            if cl == [0]: continue
            start, end = g.effective_date[cl[0]], g.effective_date[cl[-1]]
            rv = review_day(start, days)
            if -3 <= pos[rv] - pos[start] <= 2: eff, kind = rv, "定期審核（第三個週五後首個交易日）"
            else: eff, kind = start, "非定期（依 PCF 首次變動日）"
            mem = g.members[cl[-1]]
            periods.append((eff, mem, kind))
        first_existing = cons.loc[cons.etf == etf, "effective_date"].min()
        exist0 = frozenset(cons.loc[(cons.etf == etf) & (cons.effective_date == first_existing), "stock_id"])
        prev = None
        for eff, mem, kind in periods:
            if eff >= first_existing:
                if prev is not None:
                    report.append(f"{etf} 接點：PCF 在 {first_existing:%Y-%m-%d} 前最後一期 vs 現有第一期 → "
                                  f"PCF 多 {sorted(prev - exist0)}、現有多 {sorted(exist0 - prev)}")
                break
            add = sorted(mem - prev) if prev is not None else []; rm = sorted(prev - mem) if prev is not None else []
            report.append(f"| {etf} | {eff:%Y-%m-%d} | {len(mem)} | {kind} | {'、'.join(s + ' ' + names.get(s, '') for s in add) or '-'} | {'、'.join(s + ' ' + names.get(s, '') for s in rm) or '-'} |")
            for s in sorted(mem):
                rows.append({"etf": etf, "effective_date": f"{eff:%Y-%m-%d}", "stock_id": s, "name": cur_names.get(s, names.get(s, ""))})
            prev = mem
    old = pd.DataFrame(rows)
    out = pd.concat([old, cons.assign(effective_date=cons.effective_date.dt.strftime("%Y-%m-%d"))], ignore_index=True)
    out = out.sort_values(["etf", "effective_date", "stock_id"], kind="stable")
    if not dry:
        out.to_csv(UNI / "constituents.csv", index=False, lineterminator="\n")
    print("\n".join(report)); print(len(old), "新增列；全部", len(out), "；新股票",
          sorted(set(old.stock_id) - set(cons.stock_id)))


if __name__ == "__main__":
    fetch_all()
    pcf = parse()
    per, names = periods(pcf)
    finalize(per, names, pcf, "--dry-run" in sys.argv)
