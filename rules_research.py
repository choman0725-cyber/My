"""研究用設定（2026-11-02 使用者：「回測跟買股的設定檔分開」）。

BASE＝正式版的複本，所有 *_study.py、param_opt.evaluate() 的基準都從這裡拿；要試新想法就在這裡（或各 study 裡）
以 {**rr.BASE, ...} 建候選設定，隨便改都不會影響 rules_live.py，實際建議（daily_run）不受影響。
研究通過後把設定複製進 rules_live.py（流程見該檔開頭）。
回測資料截止日：robust_study.backtest_end()（最近一個全池都更新完的交易日，自動）；check_all 自己指定固定日期。
"""
from copy import deepcopy

import rules_live as live

BASE = deepcopy(live.FINAL)              # 研究基準＝正式版 E＋D＋U1
BASE_3 = deepcopy(live.FINAL_3)          # 3 檔版差異
BASE_SW18 = deepcopy(live.FINAL_SW18)    # 備案 換股 18%
CANDIDATES = {}                          # 名稱 → 設定；還沒採用的想法可以留在這裡，方便下次接著測
