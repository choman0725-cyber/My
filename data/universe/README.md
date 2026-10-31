# 0050 / 0056 歷年成分股資料包

更新日期 2026-10-31。所有 CSV 皆為 UTF-8、LF 換行。期間 2006-01-02～2026-10-30。
獨立驗證與修正紀錄見 repo 根目錄 `VERIFY_REPORT.md`。

## 檔案與來源

| 檔案 | 內容 | 筆數 | 來源 |
|---|---|---|---|
| constituents.csv | etf, effective_date, stock_id, name；每期每檔一列 | 5,194（0050 67 期、0056 55 期，186 檔） | **非 FinMind**（FinMind 沒有成分股資料）：2015-09／2015-12 前由元大每日 PCF 重建，之後依 FTSE 公告＋PCF |
| constituents_notes.md | 每次調整的新增/刪除、來源、疑點 | — | 文件 |
| prices/<stock_id>.csv | date, open, high, low, close, adj_close, volume | 188 檔（186 檔成分股＋0050、0056），共 857,521 筆 | OHLCV：FinMind TaiwanStockPrice 原始價；adj_close：自算（見下） |
| prices_manifest.csv | 每檔來源、筆數、起訖日、EPS/股利筆數、SHA-256 | 188 | 衍生 |
| eps_all.csv | stock_id, date, value（單季 EPS） | 13,463（177 檔） | FinMind TaiwanStockFinancialStatements type=EPS |
| dividend_all.csv | 股利政策原始欄位 | 3,183（170 檔） | FinMind TaiwanStockDividend |
| dividend_result_all.csv | 除權息結果原始欄位 | 3,447（186 檔） | FinMind TaiwanStockDividendResult |
| share_events_all.csv | stock_id, date, kind, share_ratio（變動後÷變動前股數） | 1,063（172 檔） | 由 FinMind 衍生（股利政策、除權息結果、減資、分割、已發行股數）＋ capital_reductions_manual.csv |
| capital_reductions_manual.csv | 2011 年以前減資的類型、退還現金、官方比例、來源網址 | 19 | **非 FinMind**：新聞／公告（FinMind 減資資料集只有 2011-01 起） |
| update_report.csv、update_warnings.txt | 最近一次更新的逐檔摘要、需要人工確認的事件 | — | 衍生 |

`data/TAIEX.csv`（交易日曆）＝FinMind TaiwanStockPrice TAIEX；`data/SOX.csv`＝FinMind USStockPrice ^SOX；`data/2382*.csv`＝FinMind（單檔舊研究用）。

## 成分股

- 2006-01-02（0050）／2007-12-26（0056）～2015：由元大每日 PCF 重建（build_constituents_pcf.py），方法與異動表見 constituents_notes.md 文末；抽查 34 份 PCF 全部相符（VERIFY_REPORT.md §6）。
- 以下說明是 2015-09 之後的段落：
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
- 186 檔在成分股期間都是上市股（兩個指數規則都只選上市股）；日線可能包含上市前的上櫃／興櫃期間。

## 日線

- open/high/low/close/volume：FinMind TaiwanStockPrice 原始成交價（high/low＝max/min，volume＝Trading_Volume 股數）。
  程式只做三種清理：刪成交量 0 的日子、開高低為 0 時改用收盤（第一天或恢復交易日）、刪單日錯價（例：8454 2014-09-09 收盤 3.43）。
- adj_close＝close × Π(參考價 ÷ 前一日收盤)，乘積涵蓋該日之後的每個事件：
  1. 除權息結果（TaiwanStockDividendResult）的參考價；現金增資除權時 FinMind 的參考價等於除權前價，改用 after_price（理論除權價）。
  2. 股利政策有、除權息結果沒有的除權息（多半在上市前）：參考價＝(P − 現金股利) ÷ (1 + 配股/10)。
  3. 減資：2011-01 起用 FinMind TaiwanStockCapitalReductionReferencePrice；之前由 FinMind 已發行股數（TaiwanStockShareholding）減少＋個股停牌判斷，
     類型與退還現金見 capital_reductions_manual.csv，參考價＝(P − 退還現金) ÷ 股數比例。
  4. 分割、面額變更（TaiwanStockSplitPrice，含 ETF，例 0050 2025-06-18 一拆四）。
- 已不再使用 yfinance：yfinance 的 close 對配股／分割做過調整，不是當天真實價。

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

另有 2006–2015 年被剔除的舊成分股（例 3009 奇美電、5854 合庫），最後交易日見 prices_manifest.csv。回測時這些股票在最後交易日後沒有價格，換股合併的轉換比例不在本資料包內。

- 上市（或櫃轉市）較晚的股票，FinMind 日線從較早的興櫃／上櫃期間就開始（例：6669 緯穎 2017-11-13 起是興櫃價格，2019-03-27 才上市；2633 高鐵 2016-10-27 前是興櫃）。興櫃期間沒有漲跌幅限制、價格不受升降單位限制，部分日子開盤落在高低價之外。

## 股數變動（share_events_all.csv）

殖利率引擎用它把 EPS、股利、原始股價換到同一股數基準（portfolio_study.share_basis）。
- 配股：1 + 配股元/10（股利政策）；股利政策缺漏（FinMind 幾乎沒有 2009 年發放的股利政策）時：有配息紀錄用 (除權前價 − 配息) ÷ 參考價，沒有就用已發行股數增加比例（含員工分紅配股，2009～2011 年中位誤差 0、平均 +0.6%）。
- 現金增資除權：除權前價 ÷ 理論除權價（只算認股權的價值部分）。
- 減資：彌補虧損＝收盤 ÷ 參考價；現金退還＝(收盤 − 停牌期間配息 − 10) ÷ (參考價 − 10)（與已發行股數實際比例相符，49 筆中 42 筆差 <1%）。2011 前見 capital_reductions_manual.csv。
- 2357 華碩 2010-06-24 分割和碩：股數比例取價值等值 0.2239（50.4 ÷ 官方參考價 225.1），不是字面上的 0.15，避免舊 EPS（含和碩）配新股價。
- 未能推出比例、未記錄的 4 筆見 update_warnings.txt（2353 2010-07-19、2542 2009-07-29、6271 2010-06-07、8008 2007-10-15）。

## 財報與股利缺漏（FinMind 本身沒有）

- EPS 為單季數字，date 是季末日期，不是公布日；可用日請用法定期限（Q1 5/15、Q2 8/14、Q3 11/14、Q4 次年 3/31）。2026Q3 尚未公布。
- EPS 0 筆：1704 榮化、3474 華亞科。
- 股利政策 0 筆：1704、2311、2325、2823、3474。除權息結果有 1704、2311、2325、2823 的紀錄，可用來補。3474 在期間內沒有除權息。
- 除權息結果 0 筆：3474、6919（康霈* 未曾除權息）。
- 同一檔股利政策可能缺個別年度（例如 2382 缺 99 年），而且幾乎整年缺 2009 年（97 年度）發放的股利政策；股數變動已用除權息結果與已發行股數補上（見上節），但 dividend_all.csv 本身沒有補，殖利率引擎的配息率以 dividend_result_all.csv 交叉核對。

## 更新（update_universe_finmind.py）

- `python update_universe_finmind.py [--start 2006-01-01] [--end 今天]`：用 FinMind 重抓全部日線、財報、股利、減資、分割、已發行股數，重建 prices 與 share_events。
- `python update_universe_finmind.py --local`：不重抓日線與財報，只用現有 FinMind 資料重算 adj_close 與 share_events（需要已發行股數，沒有快取時會抓）。
- token：環境變數 FINMIND_TOKEN 或 KEY（只放在 request header）。原始回應快取在 `_finmind_cache/`、`_verify_cache/`（不進 git）。

## 0051（元大中型100）成分股股價

- `constituents_0051.csv` 共 325 檔。其中原本沒有資料的 167 檔，加上 0051 本身，共 168 檔，用 FinMind 補齊。prices/ 合計 356 檔。
- 168 檔裡有 138 檔資料到 2026-10-30；其餘已下市或被合併。
- 這些檔不影響正式版：正式版只讀 `constituents.csv`。
- 0051 本身在 2016-12-27 有一筆成交量很小的漲停（25.20 → 27.72），隔天回到 25.35。我判斷是真實成交，予以保留。拿 0051 當比較基準時要注意這天。
