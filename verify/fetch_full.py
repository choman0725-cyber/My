"""全部股票重抓：日線、除權息結果（188 檔），財報、股利政策（個股）。有快取就跳過。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fm
S, E = '2006-01-01', '2026-10-31'
ids = sorted(f[:-4] for f in os.listdir('data/universe/prices'))
print('token', 'yes' if fm._TOKEN else 'no', flush=True)
for i, sid in enumerate(ids, 1):
    fm.get('TaiwanStockPrice', sid, S, E)
    fm.get('TaiwanStockDividendResult', sid, S, E)
    if sid not in ('0050', '0051', '0052', '0056', '00679B', '00687B', '00719B'):
        fm.get('TaiwanStockFinancialStatements', sid, S, E)
        fm.get('TaiwanStockDividend', sid, S, E)
        fm.get('TaiwanStockShareholding', sid, S, E)
    if i % 10 == 0: print(i, len(ids), 'calls', fm.CALLS, flush=True)
import pandas as pd
se = pd.read_csv('data/universe/share_events_all.csv', dtype={'stock_id': str})
for sid in sorted(se[se.kind.str.startswith('減資')].stock_id.unique()):
    fm.get('TaiwanStockCapitalReductionReferencePrice', sid, S, E)
print('ALL DONE', fm.CALLS, flush=True)
