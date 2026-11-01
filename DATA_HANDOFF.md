# 資料交接文件（DATA_HANDOFF）

最後更新：2026-11-01。分支 `claude/data-audit-verify`，交接時最後一個資料相關 commit 是 `5d7aaf7`（減資規則 v2，資料未重建）。
寫給接手整合的 session。策略本身的交接看 `HANDOFF.md`；資料驗證的完整紀錄與數字看 `VERIFY_REPORT.md`（第 10 節是修正內容）。

---

## 0. 交接當下的狀態（先看這節）

**做到一半、被使用者喊停。** 下面「未完成」的事情都還沒做，資料庫裡的檔案仍是「修正規則 v2 之前」的版本。

| 項目 | 狀態 |
|---|---|
| 0050／0056 成分股（constituents.csv）188 檔股票 | ✅ 已修正、已全面比對 FinMind（日線、EPS、股利、除權息逐筆一致；adj_close 獨立重算一致） |
| 0051 成分股（constituents_0051.csv，另一個 session 建立）168 檔新股票 | ⚠️ 日線已比對 89 檔（一致）；其餘 79 檔未比對。股數變動由另一個 session 用修正規則 v1 算出，其中 18 筆減資「類型未查證」 |
| 0052 成分股（constituents_0052.csv） | ✅ 已建立：富邦每日持股 2006-08-28～2026-10-30，102 期、134 檔，全部已在價格資料庫裡 |
| ETF 本身：0050、0051、0052、0056、00679B、00687B、00719B | ✅ 價格、配息都有，已比對 FinMind、adj_close 獨立驗證 |
| SQLite 資料庫 `build_db.py` | ✅ 可用（尚未用 v2 規則重建後的資料再產生一次） |
| 減資規則 v2（commit `5d7aaf7`） | ⚠️ **只改了程式與人工表，資料尚未重建** |
| 交接文件 | ✅ 本檔 |

### 未完成的待辦（照順序做）

1. **抓齊 FinMind 資料（約 450 次請求）**：
   ```bash
   export FINMIND_TOKEN=...   # 或環境變數 KEY；沒有 token 每小時約 300 次
   python -I verify/fetch_full.py
   ```
   抓 360 檔的日線、除權息結果、財報、股利政策、**已發行股數（TaiwanStockShareholding）**，以及有減資紀錄股票的減資資料。快取在 `data/universe/_verify_cache/finmind/`（不進 git，**換環境要重抓**）。中斷可重跑，會從快取接續。交接時停在第 190／360 檔。
2. **用 v2 規則重算 adj_close 與 share_events**（不重抓日線，OHLCV 不會變）：
   ```bash
   python update_universe_finmind.py --local
   ```
   需要第 1 步的已發行股數。會改動 0051 那批股票裡 18 筆「類型未查證」的減資（見第 5 節），以及新加進人工表的 5 筆。
3. **全部檢查**（第 4 節的指令全部跑一遍），預期：日線 0 筆無法解釋的差異；adj_close 獨立重算全部吻合；除權息日還原報酬全部符合參考價。
4. **重建資料庫**：`python build_db.py`。
5. **重跑正式版**（確認結果不變；正式版只用 0050＋0056 成分股，預期仍是 2,668 萬）：
   ```bash
   rm -f results/portfolio_prepared.pkl
   python -c "import pickle,pandas as pd,portfolio_study as ps;from backtest import RESULTS,ROOT;cons=pd.read_csv(ps.UNI/'constituents.csv',dtype={'stock_id':str,'etf':str});cal=pd.read_csv(ROOT/'data'/'TAIEX.csv',parse_dates=['date'])['date'];dates=pd.DatetimeIndex(cal[cal>=ps.START-pd.Timedelta(days=5)]).sort_values();(RESULTS/'portfolio_prepared.pkl').write_bytes(pickle.dumps(ps.prepare(sorted(cons['stock_id'].unique()),dates)))"
   python ledger_report.py
   ```
   建快取約 25 分鐘、對帳單約 30 分鐘。
6. 更新 `VERIFY_REPORT.md`、`data/universe/README.md` 的數字，commit、push。

---

## 1. 資料清單與來源

| 檔案 | 內容 | 來源 |
|---|---|---|
| `data/universe/prices/<代號>.csv`（360 檔） | date, open, high, low, close, adj_close, volume；2006-01-02～2026-10-30 | OHLCV＝**FinMind** TaiwanStockPrice 原始價；adj_close＝自算（第 3 節） |
| `data/universe/eps_all.csv` | 單季 EPS | **FinMind** TaiwanStockFinancialStatements（type=EPS） |
| `data/universe/dividend_all.csv` | 股利政策原始欄位 | **FinMind** TaiwanStockDividend（幾乎缺整個 2009 年） |
| `data/universe/dividend_result_all.csv` | 除權息結果原始欄位 | **FinMind** TaiwanStockDividendResult |
| `data/universe/share_events_all.csv` | 股數變動（變動後÷變動前），殖利率換算同一股數基準用 | 由 FinMind 衍生＋人工表 |
| `data/universe/capital_reductions_manual.csv` | 2011 前減資的類型、退還現金、官方比例、**來源網址**（24 筆） | **非 FinMind**：新聞／公告（FinMind 減資資料只有 2011-01 起） |
| `data/universe/constituents.csv` | 0050、0056 歷年成分股（**正式版只讀這個**） | **非 FinMind**：2015 前元大 PCF，之後 FTSE 公告＋PCF |
| `data/universe/constituents_0051.csv` | 0051 歷年成分股 | **非 FinMind**：元大 PCF（`build_constituents_pcf.py --etf 0051`） |
| `data/universe/constituents_0052.csv` | 0052 歷年成分股 | **非 FinMind**：富邦每日基金投資組合頁（`build_constituents_fubon.py`） |
| `data/TAIEX.csv` | 加權指數（回測交易日曆） | **FinMind** |
| `data/SOX.csv` | 費城半導體指數 | **FinMind** USStockPrice ^SOX |
| `data/2382*.csv` | 舊的單檔研究用 | **FinMind** |
| `data/market.db` | SQLite，`python build_db.py` 產生，不進 git | 由上面 CSV 匯入 |
| `data/universe/update_warnings.txt` | 最近一次更新需要人工確認的事件 | 程式輸出 |

FinMind 沒有 ETF 持股／成分股資料，所以成分股一律來自發行商（元大 PCF、富邦投資組合頁），無法用 FinMind 驗證。

---

## 2. 怎麼更新

```bash
python update_universe_finmind.py                 # 重抓全部（日線、財報、股利、減資、分割、已發行股數）並重建
python update_universe_finmind.py --local         # 只用現有 FinMind 資料重算 adj_close、share_events（不重抓日線、財報）
python update_universe_finmind.py --only 2330 0052 --skip-taiex   # 只更新幾檔
python build_constituents_pcf.py --etf 0051       # 元大 ETF 成分股（每日 PCF，curl 抓）
python build_constituents_fubon.py --end 2026-10-30   # 0052 成分股（富邦，每日一頁，約 5,300 次，1.5 小時）
python build_db.py                                # 產生 data/market.db
```
- 股票清單＝constituents.csv＋constituents_*.csv 的所有股票＋ETF 清單（`ETFS`：0050、0051、0052、0056、00679B、00687B、00719B）。
- token：環境變數 `FINMIND_TOKEN` 或 `KEY`（只放在 request header，不寫檔、不印出）。
- 快取：`data/universe/_finmind_cache/`、`_verify_cache/`、`_pcf_cache/`、`_fubon_cache/`，都不進 git。

---

## 3. 資料處理規則（修正後）

**adj_close**＝close × Π(參考價 ÷ 前一日收盤)，乘積涵蓋該日之後的每個事件：
1. 除權息結果的參考價；現金增資除權時 FinMind 參考價＝除權前價（未調整），改用 after_price（理論除權價）。
2. 股利政策有、除權息結果沒有的配股配息（多半在上市前）：(P − 現金) ÷ (1 + 配股/10)。減資、分割日 ±5 天內不補（停牌期間的除息已含在減資參考價裡）。不從股利政策補現增除權（日期不可靠）。
3. 減資：2011-01 起用 FinMind 減資資料集。之前：FinMind 已發行股數持續減少 >2%，且有個股停牌（大盤有交易 ≥3 天，排除春節）→ 減資。類型、退還現金、官方比例查人工表；人工表沒有的（v2）：看「彌補虧損」或「現金減資」哪個參考價能讓恢復日開盤落在漲跌幅內；都不行就用恢復日開盤當參考價（已發行股數可能因同期私募／現增失真）。
4. 分割、面額變更（含 ETF）。

**share_events（股數比例）**：配股 1＋配股元/10；股利政策缺漏時用 (除權前價 − 配息) ÷ 參考價，或已發行股數增加比例；現增除權用除權前價 ÷ 理論除權價；現金退還型減資 (收盤 − 停牌期間配息 − 10) ÷ (參考價 − 10)；2357 華碩 2010 分割和碩取價值等值 0.2239。

**殖利率引擎（portfolio_study.dividend_events）**：股利政策缺整檔或缺個別年度時，用除權息結果補；「權息」的現金＝除權前價 − 參考價 × 配股比例。

**日線清理**（`finmind_price_frame`）：刪成交量 0、開高低 0 改收盤、刪單日錯價（腰斬／翻倍且隔天回到原水準）。

---

## 4. 驗證工具（`verify/`，都在 repo 根目錄執行）

| 指令 | 檢查什麼 |
|---|---|
| `python -I verify/fetch_full.py` | 抓齊比對用的 FinMind 原始資料 |
| `python -I verify/cmp_prices.py ALL --no-adj` | 每檔日線逐列比對 FinMind，區分「程式刻意改的」和「無法解釋的」 |
| `python -I verify/cmp_fund.py ALL` | EPS、股利政策、除權息結果逐筆比對 FinMind |
| `python -I verify/adj_independent.py` | 不引用更新程式、獨立重寫一遍 adj_close，比對全部檔案 |
| `python -I verify/post_fix_checks.py <基準commit>` | OHLCV 沒被動、adj 變化點都對得上事件、除權息日還原報酬＝參考價、2011 前減資開盤在漲跌幅內 |
| `python -I verify/share_events_check.py` | 配股／分割比例能由來源重算 |
| `python -I verify/reduction_ratio_check.py` | FinMind 減資股數比例 vs 已發行股數 |
| `python -I verify/constituent_coverage.py` | 每期成分股在該期間都有價格 |
| `python -I verify/taiex_check.py` | TAIEX、SOX、2382 vs FinMind |
| `python -I verify/pcf_check.py`、`pcf_check2.py` | 0050／0056 成分股 vs 元大 PCF 抽查 |

**交接時的檢查結果**（v1 資料）：
- 0050＋0056 的 188 檔：日線 857,521 列 0 筆無法解釋差異；EPS 13,463、股利政策 3,183、除權息結果 3,447 筆完全一致；adj_close 獨立重算全部吻合。
- 已比對的 277 檔（含 0051 新增 89 檔）：日線 1,214,050 列 0 筆無法解釋差異；270 檔財報股利筆數一致。
- 成分股期間覆蓋：21,263 列只有 1 筆沒價格（0050 2018-04-18～04-30 的 2311 日月光，已於 04-17 下市換股成 3711，生效日本來就有疑慮）。
- 正式版在修正後資料：2,668 萬、IRR 18.6%、57 筆，與修正前相同。

---

## 5. 已知問題（待查）

1. **0051 新股票的 2011 前減資有 18 筆類型未查證**（v2 規則會自動判斷，資料尚未重建）：
   - 已有來源並加入人工表：2332 友訊、2342 茂矽、2388 威盛、2887 台新金、3051 力特。
   - 已發行股數明顯失真（開盤是參考價的 1.6～3.9 倍）：2539 櫻花建 2008-03-26、2812 台中銀 2007-04-20、2837 萬泰銀 2010-01-28 → v2 改用恢復日開盤當參考價。
   - 找不到來源：2014 中鴻、2540 金尚昌、2820 華票、2834 臺企銀、2837 萬泰銀 2008、2838 聯邦銀、2845 遠東銀、2847 大眾銀、2849 安泰銀、3049 和鑫。要查官方換股比例需要開放 `mops.twse.com.tw` 網域（公開資訊觀測站）。
2. 4 筆「權息」推不出配股比例、未記錄（2353 2010-07-19、2542 2009-07-29、6271 2010-06-07、8008 2007-10-15）。
3. 2009 年用已發行股數推算的配股含員工分紅配股，略為高估（2330 約 0.5%），連帶低估當年現金股利。只影響 2009～2012 年殖利率。
4. 6669 2018-02-08 現金增資沒有調整（FinMind 沒有除權結果；股利政策的現增日期不可靠）。
5. FinMind 減資股數比例與已發行股數差 >1% 的 3 筆：2327 2013、2609 2017、3481 2022，原因未查。
6. 0050 2018-04 日月光換成日月光投控的生效日只由 ETF 持股推得。
7. 0052 2025-09 審核 ETF 提前 3 天換股，名單記的是 ETF 實際換股日（0051 規則相同）。
8. FINAL_RULES.md 的 20 情境穩健度數字沒有在修正後資料重跑。

---

## 6. 環境與操作注意（踩過的坑）

- **FinMind 額度**：有 token 約每小時 600 次，無 token 約 300 次；同一個環境的多個 session 共用。遇到 402 程式會自動等 5～7 分鐘。
- **網路**：需要開放的網域：`api.finmindtrade.com`、`etfapi.yuantaetfs.com`（元大 PCF）、`websys.fsit.com.tw`（富邦）、`taiwanindex.com.tw`（指數公司）。`mops.twse.com.tw` 目前沒開。
- **元大 PCF 用 curl 抓**：Python 3.13 對它的憑證鏈會報 Missing Subject Key Identifier，不要關閉憑證檢查。
- **環境變數**要開新 session 才生效（`KEY` 在設定後第一個 session 讀不到）。
- 背景程式：`pkill -f <字串>` 會連自己的 shell 一起砍掉；等待程式不要用 `pgrep -f` 比對自己的命令列，改用 `until grep -q 完成字樣 log`。
- `update_report.csv` 只記錄「最近一次執行」的股票，部分更新（`--only`）會覆蓋掉其他股票的紀錄。
- 正式版的 `results/portfolio_prepared.pkl` 不進 git；資料改了要刪掉重建。

---

## 7. 分支

- `claude/data-audit-verify`（本分支）：資料驗證與修正、0052、債券 ETF、資料庫、本文件。已合併 `claude/youthful-carson-jhzz24` 到 `a46dbfa` 為止的內容（含 0051）。
- `claude/youthful-carson-jhzz24`：另一個 session（0051、策略研究）。它也改過 `update_universe_finmind.py`，整合時注意衝突；本分支之後新增的是減資 v2 規則（`_guess_type`）、ETF 清單、`--local` 等。
