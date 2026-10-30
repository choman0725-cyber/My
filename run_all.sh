#!/usr/bin/env bash
# 重跑所有研究。用法：./run_all.sh        （含股利，結果在 results/）
#                    PRICE_MODE=raw ./run_all.sh （不含股利，結果在 results_raw/）
set -e
cd "$(dirname "$0")"
mkdir -p results results_raw
python3 backtest.py 2382 7
python3 wick_study.py
python3 validate.py
python3 reverse_study.py
python3 short_study.py
python3 short_yield_study.py
python3 -c "import combo_study as c, indicators as i
for g, tag in [('MACD_KD_STRATEGIES','macd_kd'),('KD_MACD_STRATEGIES','kd_macd'),('KD_BOLLINGER_STRATEGIES','kd_bollinger'),('ZONE_PV_STRATEGIES','zone_pv'),('KD_PV_STRATEGIES','kd_pv')]:
    c.main('2382', 7, getattr(i, g), tag)"
python3 win_rate_ranking.py
python3 meanrev_study.py
python3 robustness.py
python3 scale_in_study.py
python3 yield_study.py
python3 partial_exit_study.py
python3 yield_entry_study.py
python3 trail_exit_study.py
python3 ma60_filter_study.py
python3 market_filter_study.py
python3 wick_filter_study.py
python3 compare_versions.py
python3 final_strategy.py
python3 strategy_a.py
python3 fill_study.py
python3 portfolio_electronics.py
python3 portfolio_contrib.py
