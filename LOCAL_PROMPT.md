# 本地 Claude Code 一鍵接手 prompt

在空資料夾開終端機執行 `claude`，整段貼上：

---

你要接手一個台股「殖利率＋技術買點」做多策略的 repo，從零把它在這台電腦上建起來、驗證、更新到今天，然後給我今天的操作建議。全程自己做，遇到問題自己查自己修，只有需要我給 FinMind token 或要做不可逆的事才問我。做完給我一份摘要：每一步的結果、check_all 是否全部通過、今天 daily_run 的持股與明天動作、有沒有任何數字和文件寫的不一樣。

步驟：

1. 取得程式：在目前資料夾執行
   `git clone https://github.com/choman0725-cyber/my.git .`（如果資料夾不是空的就 clone 到子目錄 `my` 再 cd 進去），然後 `git checkout ccr-fca953fb-497q7h`。這是主線分支，所有 session 的研究都已合併在這裡。
2. 先讀 `LOCAL_START.md`、`HANDOFF.md` 第 0 節、`FINAL_RULES.md` 開頭的「現況一覽」、`HANDOFF.md` 11.1（已定案、不要再問的事）與 11.2（踩過的坑）。不要改任何規則或參數。
3. 環境：確認 Python 3.11 以上；建立 venv 並 `pip install pandas numpy requests openpyxl`。之後所有指令都用這個 venv。
4. 建必要快取：照 `LOCAL_START.md` 第 3 節的指令重建 `results/portfolio_prepared.pkl`（約 12 分鐘），再 `python build_db.py`。
5. 驗證：`python check_all.py --full`。預期全部 PASS，關鍵值：資料到 2026-10-30、2017-01-03 起 4,854 萬、2016-12-28 起 3,828 萬、20 情境三段 25.97、最差 10% 21.69、標準差 2.25、daily_run 持股 7 檔。任何一項 FAIL 先停下來查原因並告訴我，不要改 EXPECT 去配合。
6. 更新資料到今天：需要 FinMind token。先檢查環境變數 `FINMIND_TOKEN` 有沒有；沒有就問我要，拿到後設成環境變數（不要寫進任何會 commit 的檔案）。然後 `python update_universe_finmind.py`，接著 `python build_db.py`，刪掉 `results/portfolio_prepared.pkl` 與 `results/param_opt_sigs.pkl`，重建 prepared.pkl（同第 4 步），再 `python check_all.py`。數字會因新資料改變：列出變動（資料最後日、兩條路徑期末、持股），判斷是否合理（只多了幾個交易日、持股變動有對應的買賣原因），合理才把 `check_all.py` 的 EXPECT 更新成新值並在 commit 訊息寫明。
7. 每日建議：`python daily_run.py`，把「目前持股」表和「明天開盤要做的事」原文貼給我，另外用 `python ledger_report.py` 重產對帳單。
8. 收尾：把這次的變動（資料更新、EXPECT、對帳單）commit 並 `git push -u origin ccr-fca953fb-497q7h`，在 `HANDOFF.md` 11.5 加一行「2026-MM-DD 本地接手，資料更新到 YYYY-MM-DD，check_all 通過」。

之後的工作規範：在分支 `ccr-fca953fb-497q7h` 上開發、每一步 commit＋push；任何新規則都要用 `param_opt.evaluate()`（20 情境＋後 3 年＋配對）和 500 萬兩個起跑日的路徑驗證，一次只改一件事，表格先講結論、標準差是否決條件；`HANDOFF.md` 11.1 列為定案的不要重測、不要再問；commit 訊息不要寫模型名稱。

---
