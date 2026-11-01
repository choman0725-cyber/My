# 在自己電腦上接手（2026-11-01）

## 1. 取得程式與資料
推薦用 git（之後可以直接 pull 更新），不要用 zip 當主要來源：
```
git clone https://github.com/choman0725-cyber/my.git
cd my
git checkout ccr-fca953fb-497q7h      # 主線分支：正式版＋所有 session 的研究都合併在這裡
```
（zip 只是備份；它不含 git 歷史、不含快取與 market.db。）

## 2. 環境
- Python 3.11 以上（雲端用 3.13，pandas 3.0、numpy 2.5）。
```
python -m venv .venv
.venv\Scripts\activate            # Windows；Mac/Linux：source .venv/bin/activate
pip install pandas numpy requests openpyxl
```
- FinMind token（更新資料用）：環境變數 `FINMIND_TOKEN=...`（Windows：`setx FINMIND_TOKEN "..."` 後重開終端機）。回測不需要。

## 3. 第一次跑（約 15 分鐘）
```
python build_db.py                 # 由 CSV 建 data/market.db（可省略，省略就讀 CSV，數字相同）
python -c "import pickle,pandas as pd,portfolio_study as ps;from backtest import RESULTS,ROOT;cons=pd.read_csv(ps.UNI/'constituents.csv',dtype={'stock_id':str,'etf':str});cal=pd.read_csv(ROOT/'data'/'TAIEX.csv',parse_dates=['date'])['date'];dates=pd.DatetimeIndex(cal[cal>=ps.START-pd.Timedelta(days=5)]).sort_values();(RESULTS/'portfolio_prepared.pkl').write_bytes(pickle.dumps(ps.prepare(sorted(cons['stock_id'].unique()),dates)))"
python check_all.py --full         # 全部 PASS 才算環境正確：資料到 2026-10-30、2017-01-03 起 4,854 萬、三段 25.97
python daily_run.py                # 每天看這個：目前持股與明天要做的事
```
`results/portfolio_prepared.pkl` 是必要快取（不進 git，上面那行重建，約 12 分鐘）。研究用的 `portfolio_prepared_2006.pkl`、`portfolio_prepared_2006_all.pkl` 第一次跑 `long_history.py`／`pool_expand_study.py` 時自動建（25／50 分鐘）。

## 4. 更新資料（之後每天／每週）
```
python update_universe_finmind.py          # 需要 FINMIND_TOKEN；抓到最新日線、EPS、股利、股數事件
python build_db.py
del results\portfolio_prepared.pkl results\param_opt_sigs.pkl     # Mac/Linux 用 rm
（重建 prepared.pkl，同第 3 節）
python daily_run.py
python check_all.py                        # 數字會隨新資料變動；先確認變動合理，再把 check_all.py 的 EXPECT 改成新值
```
細節：`HANDOFF.md` 第 3 節、`DATA_HANDOFF.md`（資料 session 的交接）、`data/universe/README.md`。

## 5. 跟本地 Claude Code session 起頭
在 repo 資料夾開終端機，執行 `claude`，第一句話貼這段：

> 這個 repo 是台股殖利率＋技術買點做多策略。先讀 `HANDOFF.md` 第 0 節和 `FINAL_RULES.md` 開頭的「現況一覽」，再讀 `HANDOFF.md` 11.1（已定案、不要再問的事）和 11.2（踩過的坑）。然後跑 `python check_all.py --full`，把結果告訴我。工作規範：在分支 `ccr-fca953fb-497q7h` 上開發、每一步 commit＋push；任何新規則都用 `param_opt.evaluate()`（20 情境＋後 3 年＋配對）和 500 萬路徑驗證，一次只改一件事，表格先講結論；HANDOFF 11.1 列為定案的不要重測。

如果 token 已設好，可以再加一句：「先跑 `python update_universe_finmind.py` 更新到今天，重建快取後跑 `daily_run.py`。」

## 6. 檔案地圖（只列會用到的）
| 檔案 | 用途 |
|---|---|
| `daily_run.py` | 每日程式；正式設定 `FINAL` 在這裡 |
| `FINAL_RULES.md` / `HANDOFF.md` | 規則與交接（開頭都有現況一覽） |
| `REPORT_hedge_2006.md` | 2026-10-31～11-01 全部研究（閒錢、2006 起回測、U1、股票池） |
| `check_all.py` | 一鍵檢查 |
| `portfolio_study.py` | 回測引擎（`run()`） |
| `param_opt.py` / `robust_study.py` / `oos_study.py` | 20 情境＋後 3 年驗證框架 |
| `rules_ext.py` | 成長股相對殖利率、信心分級 |
| `portfolio_electronics.py` | 股票池（分類法） |
| `stock_fit.py` | 個股認證（別人推薦的股票合不合這套） |
| `ledger_report.py` | 對帳單 |
| `update_universe_finmind.py` / `build_db.py` | 資料更新 / SQLite |
| `SHORT_RULES.md` / `COMBO_RULES.md` / `HANDOFF_short.md` | 其他 session 的放空、多空合併研究（已合併進來，未納入正式版） |
| `data/universe/` | 全部原始資料（CSV）；`industry_finmind.csv` 產業分類 |
| `results/` | 研究結果 CSV、對帳單 |
