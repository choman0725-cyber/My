"""把 data/ 底下的 CSV 一鍵匯入 SQLite：data/market.db（不進 git；CSV 才是 git 裡的原始資料）。

用法：python build_db.py            # 重建 data/market.db
      sqlite3 data/market.db "select * from prices where stock_id='2330' order by date desc limit 5"

資料表（主鍵避免重複；匯入時若有重複主鍵會直接報錯）：
  securities(stock_id PK, name, kind, source, rows, first_date, last_date)    ← prices_manifest.csv＋ETF 名稱
  prices(stock_id, date, open, high, low, close, adj_close, volume)  PK(stock_id, date)   ← prices/*.csv
  constituents(etf, effective_date, stock_id, name)  PK(etf, effective_date, stock_id)   ← constituents.csv＋constituents_*.csv（所有 ETF 併成一張表）
  eps(stock_id, date, value)  PK(stock_id, date)                                        ← eps_all.csv
  dividend(...FinMind 原始欄位)  PK(stock_id, date, year)                                ← dividend_all.csv
  dividend_result(...FinMind 原始欄位)  PK(stock_id, date)                               ← dividend_result_all.csv
  share_events(stock_id, date, kind, share_ratio)  PK(stock_id, date, kind)              ← share_events_all.csv
  capital_reductions_manual(...)  PK(stock_id, date)                                     ← capital_reductions_manual.csv
  index_prices(index_id, date, open, high, low, close, volume)  PK(index_id, date)      ← data/TAIEX.csv、data/SOX.csv
另建 view：constituent_days（每個 ETF 每一期的生效起訖日）。
"""
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
UNI = DATA / "universe"
DB = DATA / "market.db"
ETF_NAMES = {"0050": "元大台灣50", "0051": "元大中型100", "0052": "富邦科技", "0056": "元大高股息",
             "00679B": "元大美債20年", "00687B": "國泰20年美債", "00719B": "元大美債1-3"}

SCHEMA = """
CREATE TABLE securities(stock_id TEXT PRIMARY KEY, name TEXT, kind TEXT, source TEXT, rows INTEGER, first_date TEXT, last_date TEXT);
CREATE TABLE prices(stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume INTEGER,
                    PRIMARY KEY(stock_id, date)) WITHOUT ROWID;
CREATE TABLE constituents(etf TEXT, effective_date TEXT, stock_id TEXT, name TEXT, PRIMARY KEY(etf, effective_date, stock_id));
CREATE TABLE eps(stock_id TEXT, date TEXT, value REAL, PRIMARY KEY(stock_id, date));
CREATE TABLE share_events(stock_id TEXT, date TEXT, kind TEXT, share_ratio REAL, PRIMARY KEY(stock_id, date, kind));
CREATE TABLE index_prices(index_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(index_id, date));
"""
VIEWS = """
CREATE VIEW constituent_days AS
SELECT etf, effective_date AS start_date,
       (SELECT MIN(c2.effective_date) FROM (SELECT DISTINCT etf, effective_date FROM constituents) c2
         WHERE c2.etf = p.etf AND c2.effective_date > p.effective_date) AS end_date_exclusive,
       COUNT(*) AS n_stocks
FROM constituents p GROUP BY etf, effective_date;
"""


def insert(con, table, df, pk):
    dup = df.duplicated(pk)
    if dup.any():
        raise SystemExit(f"{table}: 主鍵 {pk} 重複 {int(dup.sum())} 筆，例：{df[dup].head(3).to_dict('records')}")
    cols = list(df.columns)
    q = f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
    con.executemany(q, df.astype(object).where(df.notna(), None).itertuples(index=False, name=None))
    return len(df)


def create_from_frame(con, table, df, pk):
    cols = ", ".join(f'"{c}"' for c in df.columns)
    con.execute(f'CREATE TABLE {table}({cols}, PRIMARY KEY({", ".join(pk)}))')
    return insert(con, table, df, pk)


def main():
    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    n = {}
    rows = []
    for f in sorted((UNI / "prices").glob("*.csv")):
        d = pd.read_csv(f)
        d.insert(0, "stock_id", f.stem)
        rows.append(d)
    n["prices"] = insert(con, "prices", pd.concat(rows, ignore_index=True), ["stock_id", "date"])
    cons = [pd.read_csv(UNI / "constituents.csv", dtype=str)] + [pd.read_csv(f, dtype=str) for f in sorted(UNI.glob("constituents_*.csv"))]
    n["constituents"] = insert(con, "constituents", pd.concat(cons, ignore_index=True)[["etf", "effective_date", "stock_id", "name"]],
                               ["etf", "effective_date", "stock_id"])
    n["eps"] = insert(con, "eps", pd.read_csv(UNI / "eps_all.csv", dtype={"stock_id": str}), ["stock_id", "date"])
    n["share_events"] = insert(con, "share_events", pd.read_csv(UNI / "share_events_all.csv", dtype={"stock_id": str}),
                               ["stock_id", "date", "kind"])
    n["dividend"] = create_from_frame(con, "dividend", pd.read_csv(UNI / "dividend_all.csv", dtype={"stock_id": str, "year": str}),
                                      ["stock_id", "date", "year"])
    n["dividend_result"] = create_from_frame(con, "dividend_result", pd.read_csv(UNI / "dividend_result_all.csv", dtype={"stock_id": str}),
                                             ["stock_id", "date"])
    man = UNI / "capital_reductions_manual.csv"
    if man.exists():
        n["capital_reductions_manual"] = create_from_frame(con, "capital_reductions_manual", pd.read_csv(man, dtype={"stock_id": str}),
                                                           ["stock_id", "date"])
    idx = []
    for name in ("TAIEX", "SOX"):
        p = DATA / f"{name}.csv"
        if p.exists():
            d = pd.read_csv(p)
            d.insert(0, "index_id", name)
            idx.append(d[["index_id", "date", "open", "high", "low", "close", "volume"]])
    n["index_prices"] = insert(con, "index_prices", pd.concat(idx, ignore_index=True), ["index_id", "date"])
    m = pd.read_csv(UNI / "prices_manifest.csv", dtype=str)
    names = pd.concat(cons).drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    sec = pd.DataFrame({"stock_id": m.stock_id,
                        "name": [ETF_NAMES.get(s) or names.get(s) or nm for s, nm in zip(m.stock_id, m.name)],
                        "kind": ["ETF" if s in ETF_NAMES else "股票" for s in m.stock_id],
                        "source": m.source, "rows": m.rows.astype(int), "first_date": m.first_date, "last_date": m.last_date})
    n["securities"] = insert(con, "securities", sec, ["stock_id"])
    con.executescript(VIEWS)
    con.execute("CREATE INDEX constituents_stock ON constituents(stock_id)")
    con.commit()
    # 自我檢查：每張表筆數要等於 CSV 筆數
    for t, k in n.items():
        got = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert got == k, (t, got, k)
    con.execute("VACUUM")
    con.close()
    tmp.replace(DB)
    print(f"{DB.relative_to(ROOT)}（{DB.stat().st_size / 1e6:.1f} MB）：" + "、".join(f"{t} {k:,}" for t, k in n.items()))


if __name__ == "__main__":
    main()
