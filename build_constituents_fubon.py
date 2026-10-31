"""由富邦投信每日「基金投資組合」頁重建 0052 富邦科技（上市 2006-09）的歷年成分股 → constituents_0052.csv。

來源：https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx?stkId=0052&ddate=YYYYMMDD&lan=TW
  · 一般 GET、帶 ddate；頁面上的「資料日期：YYYY/MM/DD」才是實際資料日（非交易日會回最近一個交易日，依它去重）。
  · 第二個表格是股票：股票代碼｜股票名稱｜股數｜金額｜權重(%)，最後一列「股票合計」略過。
  · 只把解析後的持股存成小 JSON（data/universe/_fubon_cache/，不進 git），不存整頁 HTML（每頁約 200 KB）。
方法同 build_constituents_pcf.py --etf：每日持股；缺席 ≤ 20 個交易日補回；分批換股合併、生效日取指數生效日（第三個週五後首個交易日）。
FinMind 沒有 ETF 持股資料，這份名單無法由 FinMind 驗證。

用法：python build_constituents_fubon.py [--start 2006-08-28] [--end 2026-10-30] [--dry-run]
"""
import json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import build_constituents_pcf as pcf

UNI = Path(__file__).parent / "data" / "universe"
OUT = UNI / "_fubon_cache"
ETF = "0052"
URL = "https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx?stkId={etf}&ddate={d}&lan=TW"
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
TAG = re.compile(r"<[^>]+>")


def parse(html):
    """→ {"date": 資料日期, "stocks": [[代碼, 名稱, 股數, 權重], ...]}；沒有資料日期回 None。"""
    m = re.search(r"資料日期：\s*(\d{4}/\d{2}/\d{2})", html)
    if not m:
        return None
    stocks, in_stock = [], False
    for row in ROW.findall(html):
        cells = [TAG.sub("", c).replace("&nbsp;", " ").strip() for c in CELL.findall(row)]
        if not cells:
            continue
        if cells[0] == "股票代碼":
            in_stock = True
            continue
        if in_stock:
            if cells[0].startswith("股票合計") or len(cells) < 5:
                in_stock = False
                continue
            try:
                stocks.append([cells[0], cells[1], int(cells[2].replace(",", "")), float(cells[4].replace(",", ""))])
            except ValueError:
                pass
    return {"date": m.group(1).replace("/", "-"), "stocks": stocks}


def one(d):
    f = OUT / f"{ETF}_{d:%Y%m%d}.json"
    if f.exists():
        return
    for k in range(5):
        try:
            r = subprocess.run(["curl", "-sS", "-f", "-m", "40", URL.format(etf=ETF, d=f"{d:%Y%m%d}")],
                               capture_output=True, check=True)
            p = parse(r.stdout.decode("utf-8", errors="replace"))
            if p is None:
                raise ValueError("no 資料日期")
            f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.2)
            return
        except Exception:
            time.sleep(2 ** k)
    print("fail", d.date(), flush=True)


def fetch(start, end):
    OUT.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    with ThreadPoolExecutor(8) as ex:
        for i, _ in enumerate(ex.map(one, days)):
            if i % 250 == 0:
                print(f"{ETF} {i}/{len(days)}", flush=True)


def load():
    rows = []
    for f in sorted(OUT.glob(f"{ETF}_*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if not p["stocks"]:
            continue
        codes = tuple(sorted(s[0] for s in p["stocks"] if s[2] > 0))
        rows.append({"etf": ETF, "req": f.stem.split("_")[1], "anndate": p["date"].replace("-", ""),
                     "inkind": codes, "weights": (), "names": {s[0]: s[1] for s in p["stocks"]}})
    df = pd.DataFrame(rows).drop_duplicates("anndate").sort_values("anndate").reset_index(drop=True)
    return df


def main():
    a = sys.argv
    start = a[a.index("--start") + 1] if "--start" in a else "2006-08-28"
    end = a[a.index("--end") + 1] if "--end" in a else pd.Timestamp.today().strftime("%Y-%m-%d")
    fetch(start, end)
    raw = load()
    per, names = pcf.periods(raw)
    days = sorted(pd.to_datetime(raw["anndate"]).unique())
    cons = pd.read_csv(UNI / "constituents.csv", dtype={"stock_id": str})
    cur = cons.drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    rows, report, prev = [], [], None
    for eff, mem, kind in pcf.merge_changes(per, days, "上市初期（富邦最早資料日）"):
        report.append(pcf.table_row(ETF, eff, mem, kind, prev, names))
        rows += [{"etf": ETF, "effective_date": f"{eff:%Y-%m-%d}", "stock_id": s, "name": cur.get(s, names.get(s, ""))}
                 for s in sorted(mem)]
        prev = mem
    out = pd.DataFrame(rows)
    counts = out.groupby("effective_date").size()
    print("\n".join(report))
    print(f"{ETF}：資料日 {len(days)} 天（{days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}），{counts.size} 期、{out['stock_id'].nunique()} 檔；"
          f"每期檔數 {counts.min()}～{counts.max()}")
    if "--dry-run" not in a:
        out.to_csv(UNI / f"constituents_{ETF}.csv", index=False, lineterminator="\n")
        hdr = "| etf | effective_date | count | type | additions 納入 | deletions 刪除 |\n|---|---|---|---|---|---|\n"
        (UNI / f"constituents_{ETF}_notes.md").write_text(
            f"# {ETF} 富邦科技 歷年成分股（{days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}）\n\n"
            f"由 `build_constituents_fubon.py` 從富邦投信每日基金投資組合頁（{URL.format(etf=ETF, d='YYYYMMDD')}）重建，"
            f"方法同 constituents_notes.md「2006-01 ~ 2015 延伸」（每日持股；缺席 ≤ {pcf.GAP} 個交易日補回；分批換股合併到指數生效日）。"
            f"這份名單沒有逐筆核對指數公告，也無法由 FinMind 驗證（FinMind 沒有 ETF 持股資料）。\n\n{hdr}" + "\n".join(report) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
