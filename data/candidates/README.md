# 候選股資料夾（認證別人推薦的股票用）

`python stock_fit.py <代號>` 會先在 `data/universe/` 找資料，找不到才來這裡。0050／0056 的 149 檔成分股已在 universe，
不必再放；只有**池子以外**的股票才需要放到這裡。格式與 `data/universe/` 完全相同，請不要改 universe（它有 manifest 與 SHA-256 核對）。

| 檔案 | 內容 | 來源 |
|---|---|---|
| `prices/<代號>.csv` | `date,open,high,low,close,adj_close,volume`，去除成交量 0 的日子 | yfinance `<代號>.TW`，`auto_adjust=False`（adj_close 要含現金股利還原） |
| `eps_all.csv` | `stock_id,date,value`；單季 EPS，date 為季末日 | FinMind `TaiwanStockFinancialStatements`，只取 `type == "EPS"` |
| `dividend_all.csv` | FinMind `TaiwanStockDividend` 原始欄位（可多檔疊在同一個檔） | FinMind |
| `dividend_result_all.csv` | FinMind `TaiwanStockDividendResult` 原始欄位 | FinMind |
| `names.csv`（選用） | `stock_id,name` | 自填 |

最低要求：價格 ≥ 260 筆、EPS ≥ 8 季、股利資料 ≥ 2 筆；要做十年統計，價格與 EPS 請從 2015-01 抓起。
雲端工作階段連不到金融網站，請在本機抓（`fetch_data.py` 可抓價格；EPS／股利用 FinMind API），再 commit 進來。
檢查資料齊不齊：`python stock_fit.py --check <代號>`。
