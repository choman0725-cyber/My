"""抓取台股近十年日線資料（預設：廣達 2382）。

用法：
    pip install -r requirements.txt
    python fetch_data.py            # 抓廣達
    python fetch_data.py 2330 10    # 抓台積電近 10 年

優先使用 yfinance（含除權息調整），失敗時改用 FinMind。
輸出：data/<代號>.csv，欄位 date, open, high, low, close, adj_close, volume
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"


def from_yfinance(stock_id: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(f"{stock_id}.TW", start=start, auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError("yfinance 沒有回傳資料")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                            "Adj Close": "adj_close", "Volume": "volume"})
    df.index.name = "date"
    return df[["open", "high", "low", "close", "adj_close", "volume"]].reset_index()


def from_finmind(stock_id: str, start: str) -> pd.DataFrame:
    resp = requests.get(
        "https://api.finmindtrade.com/api/v4/data",
        params={"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    if not rows:
        raise RuntimeError("FinMind 沒有回傳資料")
    df = pd.DataFrame(rows).rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df["adj_close"] = df["close"]  # FinMind 免費版為未調整價
    return df[["date", "open", "high", "low", "close", "adj_close", "volume"]]


def fetch(stock_id: str = "2382", years: int = 10) -> pd.DataFrame:
    start = (date.today() - timedelta(days=365 * years + 10)).isoformat()
    for source in (from_yfinance, from_finmind):
        try:
            df = source(stock_id, start)
            print(f"[{source.__name__}] 取得 {len(df)} 筆，{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")
            break
        except Exception as e:
            print(f"[{source.__name__}] 失敗：{e}")
    else:
        sys.exit("所有資料來源都失敗，請檢查網路")

    df = df[df["volume"] > 0].sort_values("date").reset_index(drop=True)
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"{stock_id}.csv"
    df.to_csv(out, index=False)
    print(f"已存到 {out}")
    return df


if __name__ == "__main__":
    fetch(sys.argv[1] if len(sys.argv) > 1 else "2382",
          int(sys.argv[2]) if len(sys.argv) > 2 else 10)
