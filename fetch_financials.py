"""抓取 0050／0056 歷年成分股的季度損益表（FinMind TaiwanStockFinancialStatements），供利潤率模式用。

輸出 data/universe/financials_all.csv，欄位 date, stock_id, type, value, origin_name（同 data/2382_financials.csv），
只保留 Revenue、GrossProfit、OperatingIncome、IncomeAfterTaxes、NetIncome、EPS 六種 type。

用法：
  python fetch_financials.py                 # 抓 constituents.csv 全部 149 檔，已抓過的跳過
  python fetch_financials.py 2382 2330       # 只抓指定代號（會覆蓋該檔舊資料）
  FINMIND_TOKEN=xxx python fetch_financials.py   # 有 FinMind 帳號可帶 token 提高流量上限
抓完後：YIELD_MODE=margin python portfolio_study.py 重建 results/portfolio_prepared_margin.pkl。
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from portfolio_study import UNI

OUT = UNI / "financials_all.csv"
KEEP = ("Revenue", "GrossProfit", "OperatingIncome", "IncomeAfterTaxes", "NetIncome", "EPS")
START = "2014-01-01"
SLEEP = 1.0   # 每檔之間停一下，免費額度約每小時 600 次請求


def fetch_one(stock_id):
    headers = {"Authorization": f"Bearer {os.environ['FINMIND_TOKEN']}"} if os.environ.get("FINMIND_TOKEN") else {}
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data", headers=headers, timeout=30,
                             params={"dataset": "TaiwanStockFinancialStatements", "data_id": stock_id, "start_date": START})
            r.raise_for_status()
            rows = r.json().get("data", [])
            break
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  {stock_id} 失敗（{e}），{2 ** attempt * 5} 秒後重試")
            time.sleep(2 ** attempt * 5)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df[df["type"].isin(KEEP)][["date", "stock_id", "type", "value", "origin_name"]]


def main(ids):
    old = pd.read_csv(OUT, dtype={"stock_id": str}) if OUT.exists() else pd.DataFrame(columns=["date", "stock_id", "type", "value", "origin_name"])
    if not ids:
        cons = pd.read_csv(UNI / "constituents.csv", dtype=str)
        ids = [s for s in sorted(cons["stock_id"].unique()) if s not in set(old["stock_id"])]
    else:
        old = old[~old["stock_id"].isin(ids)]
    print(f"要抓 {len(ids)} 檔")
    parts = [old]
    for i, sid in enumerate(ids, 1):
        df = fetch_one(sid)
        print(f"[{i}/{len(ids)}] {sid}：{len(df)} 筆" + ("" if len(df) else "（無資料）"))
        if len(df):
            parts.append(df)
            pd.concat(parts).sort_values(["stock_id", "date", "type"]).to_csv(OUT, index=False)   # 每檔存一次，中斷可續
        time.sleep(SLEEP)
    print(f"完成，已存到 {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
