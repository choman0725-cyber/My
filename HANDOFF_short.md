# HANDOFF：台股殖利率策略（多方正式版＋空方對沖版）交接文件

更新日期：2026-10-31。給接手這個 repo 的人（或下一個對話）看的：這裡有什麼、怎麼跑、為什麼這樣定、哪裡不要碰、還沒做的事。

## 1. 一句話

用「預估殖利率」當估值錨、技術訊號當時機，對 0050／0056 歷年成分股做兩套規則：
**多方正式版**（殖利率 ≥5% 買、獲利 12% 且殖利率 <4.75% 賣，`FINAL_RULES.md`）與
**空方對沖版**（殖利率 <2%＋大盤空頭排列＋出貨訊號放空、跌 5% 回補，`SHORT_RULES.md`）。
兩者各有一支每日執行程式，跑完直接告訴你明天開盤要做什麼。

## 2. 先讀哪些檔

| 順序 | 檔案 | 內容 |
|---|---|---|
| 1 | `FINAL_RULES.md` | 多方正式版規則、為什麼是這組參數、績效、備選 |
| 2 | `SHORT_RULES.md` | 空方對沖版規則（進取版 <2% 為正式、<1.5% 備選）、每條規則的理由、績效、注意事項 |
| 3 | `SHORT_STUDY.md` | 空方研究全紀錄：純技術放空為何不行 → 多空盤 → 殖利率把關 → 逐條出場／進場規則的掃描 |
| 4 | `data/universe/README.md` | 資料包說明：成分股歷史、股價來源、EPS／股利欄位、缺漏清單 |
| 5 | 本檔 | 操作、結構、決策脈絡 |

## 3. 每日操作

```bash
# 多方正式版：目前持股、明天買／加碼／賣、觀察名單（500 萬、2017-01 起；參數見檔頭）
python daily_run.py

# 空方對沖版：回測摘要、逐筆、目前空單、明天放空／回補、觀察名單
python short_strategy.py
```

- 兩支程式都是「從起始日把規則重跑到最新資料日 → 推出今天應有的部位 → 依最新收盤給明天的動作」。沒有狀態檔，部位是算出來的；實際成交若與回測不同（沒成交、價格差），以實際帳戶為準，程式只是建議。
- `--asof YYYY-MM-DD` 可回看任一天當時的建議，用來核對。
- 空方程式第一次執行約 5 分鐘（算 148 檔殖利率），之後讀 `results/short_strategy_prepared.pkl` 幾秒。**資料更新後要刪掉這個 pkl 或加 `--no-cache`**，否則用的是舊殖利率。多方的對應快取是 `results/portfolio_prepared.pkl`，由 `portfolio_electronics.py` 重建（見 `daily_run.py` 檔頭）。
- `daily_short_run.py` 是空方的研究引擎版，結果應與 `short_strategy.py` 逐筆相同（已驗證 48 筆完全一致），改規則時拿它交叉核對。

## 4. 資料更新

資料目前到 **2026-10-29**。更新流程（沒有自動化腳本，都是手動）：

1. 日線：`data/universe/prices/<代號>.csv`（欄位 date, open, high, low, close, adj_close, volume）。原本用 yfinance `.TW` `auto_adjust=False` 抓（`fetch_data.py` 是單檔版，可參考）。下市股用 FinMind，adj_close 自己算（README 有公式）。
2. 加權指數：`data/TAIEX.csv`（空方的多空盤判斷全靠它）；`data/SOX.csv` 只有研究用。
3. EPS：`data/universe/eps_all.csv`（FinMind TaiwanStockFinancialStatements，type=EPS）。date 是季末，程式自己依法定公布期限（5/15、8/14、11/14、3/31）決定何時「已知」。
4. 股利：`dividend_all.csv`（股利政策）、`dividend_result_all.csv`（除權息結果；空方用它算最後回補日）。
5. 成分股：`constituents.csv`（etf, effective_date, stock_id, name），每次 0050／0056 調整後補一期。`constituents_notes.md` 記錄來源與疑點。
6. 更新後：刪 `results/short_strategy_prepared.pkl` 與 `results/portfolio_prepared.pkl`，重跑兩支每日程式，檢查歷史逐筆沒有變（若變了，通常是 adj_close 整批重算導致，屬正常）。

已知資料缺口（README 有完整清單）：1704、3474 沒 EPS；股東會日期沒有（空方的股東會前停券沒模擬）；2026Q3 EPS 尚未公布。

## 5. 程式結構

共用底層
- `indicators.py`：所有技術指標與訊號。`STRATEGIES`～`KD_PV_STRATEGIES` 是多頭策略（回傳 買,賣）；`SHORT_STRATEGIES` S1～S10 是放空專用（回傳 放空,回補，**方向相反，別混用**）。
- `backtest.py`：`load()`（含還原價換算）、單檔多頭引擎 `run()`、成本常數 `BUY_COST`／`SELL_COST`。
- `portfolio_study.py`：多股票組合引擎 `run()`、資料準備（`load_prices`、`eps_table`、`dividend_events`、`forward_dividend`＝預估殖利率算法、`membership`）。**預估殖利率算法只在這裡，多空兩邊共用。**

多方
- 正式引擎參數 `param_opt.BASE_A` + `{"hold_yield": 4.75, "target": 0.12}`（見 `daily_run.py` 的 `FINAL`）。
- `daily_run.py` 每日執行；`ledger_report.py` 對帳單；其餘 `*_study.py` 是歷次研究，`run_all.sh` 可全部重跑（很久）。

空方
- `short_study.py`：放空引擎 `run_short()`（成本、借券費、斷頭、平盤下禁空、除息停券、轉多有賺）、純技術放空研究、多空盤研究 `regime_study()`、`regime_defs()`（10 種空頭盤定義）。
- `short_yield_study.py`：鏡像放空研究全部掃描（`targets`／`hold`／`add`／`gap`／`flip`／`filters`／`confirm` 子命令）、5 檔組合引擎 `run_portfolio()`、資料準備 `prepare()`。
- **`short_strategy.py`：正式程式，獨立實作**，規則常數在檔頭（`MAX_YIELD`、`BIAS_LO/HI`、`TARGET`、`FLIP_GAIN`、`FLIP_CONFIRM`、`MIN_DAYS_TO_FORCE`…）。要改規則改這裡，然後用 `daily_short_run.py` 核對。

輸出
- `results/`：所有研究 CSV 與 log（檔名前綴對應程式）。空方正式逐筆 `short_strategy_trades.csv`、權益 `short_strategy_equity.csv`。`results_raw/` 是不含股利的對照版（幾乎沒再用）。

## 6. 空方規則與理由（摘要，細節在 SHORT_RULES.md）

| 規則 | 定的理由 | 掃過的替代方案 |
|---|---|---|
| 殖利率 <2% | 貴的股票才空；不看殖利率每筆 −6%，<2.5% 又太鬆（87%） | 不看／2.5／2／1.5 |
| 大盤空頭排列 MA5<20<60 | 10 種空頭盤定義裡，只有含「空頭排列」的在期間內指數真的在跌 | 指數<年線、死亡交叉、跌幅、回落幅度… |
| 指數對月線乖離 −10%～+1% | 不空恐慌低點（2025-04、2020-03）、不空已站回月線的盤 | 上下界各掃；上界 +1% 敏感 |
| 四個鏡像技術訊號 | 直接拿正式版四個買點反過來 | 45 個既有策略反向、10 個 S 系列都試過，純技術全負 |
| 距最後回補日 ≥30 天 | 不進場就快被制度逼平倉的單 | 15／30／45／60 幾乎相同 |
| 停利 5% | 抓的是誘多反彈，跌 5% 幾週內到；拉高停利勝率、IRR 都降 | 7.5／10／12.5／15 |
| 轉多且賺 ≥2%、連 2 個收盤回補 | 進場理由消失且有賺就收；連 2 日擋單日假訊號 | 一律轉多就補（大錯）、門檻 0.5～4%、連 1／3 日 |
| 不停損、不加碼、無持有上限 | 停損以跳空成交救不回；加碼補給輸家；上限切掉晚到的停利 | 停損 10%、20～120 日上限、漲 5% 加碼一次 |

結論鏈：純技術放空在這個股票池是負期望值（14 萬筆交易，每筆 −2.7%）→ 只在空頭盤做仍負（−0.6%）→ 加殖利率 <2% 才轉正（+3.7%）→ 逐條加上面規則到 48 筆全贏。

## 7. 關鍵數字（500 萬、2017-01-03～2026-10-29）

| | 多方正式版 | 空方進取版 <2% | 空方保守版 <1.5% |
|---|---|---|---|
| 筆數／勝率 | 67／97% | 48／100% | 32／100% |
| 期末（萬） | 4,104 | 853 | 710 |
| IRR | 23.9% | 5.6% | 3.6% |
| 最大回撤 | −31% | −16%（浮虧） | −8% |
| 有部位時間 | 高 | 20% | ~20% |

## 8. 不要碰／要小心的地方

- **預估殖利率算法**（`portfolio_study.forward_dividend`）是兩套規則的共同地基，改它要兩邊重跑。
- **還原價**：回測全用還原價（含現金股利再投入）。對空方而言等於放空者賠付股利，方向正確；但顯示給人看的價位（停利價、觀察名單收盤）用原始價，程式已換算，別把兩者混在一起比。
- **空方 100% 勝率是樣本內**，三個數字（乖離上界 +1%、轉多門檻 2%、連 2 日）是看著個別輸家定的，雖都在平坦區，實盤請預期 90% 上下。空單虧損無上限，每檔名目 1/5 是把單筆最壞情況壓在總資產 −10% 以內的設計。
- **訊號成立 → 隔天開盤成交**是所有程式的共同假設；盤中看到訊號不要提前動作。
- 平盤下禁空的判斷（前日跌 ≥3.5% 且開盤低於前收就放棄）要人在開盤時執行，程式只會標註。
- 2008、2020-03、2022-10 這類全市場禁空期沒模擬；股東會前停券沒模擬。
- `results*/portfolio_prepared.pkl`、`short_prepared.pkl`、`short_strategy_prepared.pkl` 是快取，已 gitignore，不要 commit。

## 9. 還沒做／可以做的事

1. 資料更新自動化（抓價、EPS、股利、成分股）目前全手動。
2. 股東會日期資料：補進去可讓空方的停券與強制回補模擬完整。
3. 空方規則的樣本外追蹤：從 2026-11 起把每一筆實際建議記下來，一年後對照回測勝率。
4. 多空合併記帳：目前兩套獨立算，若同一帳戶操作，融券保證金會占用現金，`daily_run.py` 不知道這件事。
5. 多方正式版的研究結果檔很多（`results/` 下 300+ 個），可以整理歸檔。

## 10. 環境

- Python 3.13、pandas 3.0、numpy 2.5（`requirements.txt` 另列 requests、yfinance 供抓資料）。
- 所有程式從 repo 根目錄執行；輸出目錄 `results/` 不存在會自動建。
- Git：開發分支 `claude/sharp-johnson-yzcmqp`，每次研究一個 commit，commit 訊息寫結論。
