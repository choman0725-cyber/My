"""研究用設定（2026-11-02 使用者：「回測跟買股的設定檔分開」）。

BASE＝正式版的複本，所有 *_study.py、param_opt.evaluate() 的基準都從這裡拿；要試新想法就在這裡（或各 study 裡）
以 {**rr.BASE, ...} 建候選設定，隨便改都不會影響 rules_live.py，實際建議（daily_run）不受影響。
研究通過後把設定複製進 rules_live.py（流程見該檔開頭）。
回測資料截止日＝下面的 BACKTEST_END（2026-11-02 使用者：先固定，有需要再調，只改這裡）。
"""
from copy import deepcopy

import rules_live as live

BASE = deepcopy(live.FINAL)              # 研究基準＝正式版 E＋D＋U1
BASE_3 = deepcopy(live.FINAL_3)          # 3 檔版差異
BASE_SW18 = deepcopy(live.FINAL_SW18)    # 備案 換股 18%
CANDIDATES = {}                          # 名稱 → 設定；還沒採用的想法可以留在這裡，方便下次接著測

# 回測資料截止日：所有研究程式與 check_all 都用這一天（po.setup() 自動截到這裡），每天更新資料不會動到回測數字。
# 要往前推：改這個日期 → python check_all.py --full → 把六個新數字抄進 check_all.EXPECT → commit。
# 設 None＝自動用 robust_study.backtest_end()（最近一個全池都更新完的交易日，每天跟著走）。
BACKTEST_END = "2026-10-30"
