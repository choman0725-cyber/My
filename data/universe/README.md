# 0050 / 0056 歷年成分股資料包

產生日期 2026-10-30。所有 CSV 皆為 UTF-8、LF 換行。

## 檔案

| 檔案 | 內容 | 筆數 |
|---|---|---|
| constituents.csv | etf, effective_date, stock_id, name；每期每檔一列 | 2,988（0050 37 期、0056 31 期，149 檔） |
| constituents_notes.md | 每次調整的新增/刪除、來源網址、推算與否、有疑慮的期間 | — |
| prices/<stock_id>.csv | date, open, high, low, close, adj_close, volume | 151 檔（149 檔成分股 + 0050、0056），共 412,373 筆 |
| prices_manifest.csv | 每檔股價的來源、筆數、起訖日、EPS/股利筆數、SHA-256 | 151 |
| eps_all.csv | stock_id, date, value（FinMind TaiwanStockFinancialStatements，只取 type=EPS） | 6,549 |
| dividend_all.csv | FinMind TaiwanStockDividend 原始欄位 | 1,769 |
| dividend_result_all.csv | FinMind TaiwanStockDividendResult 原始欄位 | 1,760 |
| financials_all.csv（選用） | date, stock_id, type, value, origin_name；FinMind TaiwanStockFinancialStatements 的 Revenue／GrossProfit／OperatingIncome／IncomeAfterTaxes／NetIncome／EPS 單季值，`python fetch_financials.py` 產生，YIELD_MODE=margin 時用 | — |

期間 2015-01-01～2026-10-29。

## 成分股

- 調整紀錄取自 FTSE Russell 官方公告（2016-09 前在證交所新聞，2016-11 起在臺灣指數公司新聞）。
- 起始名單取自元大投信 2016-01-04 的申購買回清單（PCF）。
- 之後各期由公告往後推，再與元大 2015-06～2026-10-30 每個交易日的 PCF（約 4,900 天）逐日比對，全部相符。
- 0056 部分期間不足 30/50 檔是真實檔數：期中刪除不遞補（離開臺灣50+中型100 母體或零股利規則）。
  - 29 檔：2015-12-21、2017-03-20、2018-04-18、2019-01-24、2022-03-21、2022-09-19
  - 27 檔：2021-03-22
  - 49 檔：2023-09-18、2024-09-23、2026-03-23
- effective_date 依指數公告。ETF 實際換股有三次比指數晚：
  - 0050 買進 2408（2025-12-31，指數 2025-12-22）
  - 0050 買進 3037（2026-04-14，指數 2026-03-23）
  - 0056 賣出 4763（2025-07-11，指數 2025-06-23）
- 有疑慮的地方：2311 換成 3711 的日期（2018-04-30）只由 ETF 持股推得；0056 從 3/9 月改為 6/12 月審核沒找到規則變更公告。詳見 constituents_notes.md。
- 149 檔全部是上市股（兩個指數規則都只選上市股）。

## 日線

- 141 檔現存股 + 0050、0056：yfinance `.TW`、auto_adjust=False。已去除成交量 0 的日子，價格四捨五入到小數 4 位。
- 8 檔下市或合併股 yfinance 抓不到，改用 FinMind TaiwanStockPrice 原始日線（high/low = max/min，volume = Trading_Volume 股數）。
  adj_close 由 FinMind 還原股價是付費資料，所以自行計算：
  - 公式：adj_close = close × Π(除權息參考價 ÷ 除權息前收盤價)，乘積涵蓋該日之後的每次除權息，用 dividend_result_all.csv。
  - 以 2382 驗證，各時點的係數與 Yahoo 的 adj_close/close 到小數 4 位完全一致。

| stock_id | 名稱 | 最後交易日 | 去向 |
|---|---|---|---|
| 1704 | 榮化 | 2019-01-23 | 下市 |
| 2311 | 日月光 | 2018-04-17 | 與矽品換股成日月光投控 3711 |
| 2325 | 矽品 | 2018-04-17 | 同上 |
| 2809 | 京城銀 | 2025-09-17 | 停止交易（原因未查證） |
| 2823 | 中壽 | 2021-12-17 | 併入開發金（2883，現凱基金） |
| 2888 | 新光金 | 2025-07-11 | 併入台新金（2887，現台新新光金） |
| 3474 | 華亞科 | 2016-11-29 | 美光收購下市 |
| 5264 | 鎧勝-KY | 2021-01-06 | 停止交易（原因未查證） |

回測時這些股票在最後交易日後沒有價格，換股合併的轉換比例不在本資料包內。

- 上市較晚的股票從上市日開始：2633 台灣高鐵、2645 長榮航太、6669 緯穎、6770 力積電、6919 康霈*、7769 鴻勁 等。起訖日見 prices_manifest.csv。

## 財報與股利缺漏（FinMind 本身沒有）

- EPS 為單季數字，date 是季末日期，不是公布日；可用日請用法定期限（Q1 5/15、Q2 8/14、Q3 11/14、Q4 次年 3/31）。2026Q3 尚未公布。
- EPS 0 筆：1704 榮化、3474 華亞科。
- 股利政策 0 筆：1704、2311、2325、2823、3474。除權息結果有 1704、2311、2325、2823 的紀錄，可用來補。3474 在期間內沒有除權息。
- 除權息結果 0 筆：3474、6919（康霈* 未曾除權息）。
- 同一檔股利政策可能缺個別年度（例如 2382 缺 99 年）。用殖利率時請以 dividend_result_all.csv 交叉核對。
