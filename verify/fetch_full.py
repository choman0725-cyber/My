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
    if sid not in ('0050', '0051', '0056'):
        fm.get('TaiwanStockFinancialStatements', sid, S, E)
        fm.get('TaiwanStockDividend', sid, S, E)
    if i % 10 == 0: print(i, len(ids), 'calls', fm.CALLS, flush=True)
print('ALL DONE', fm.CALLS, flush=True)
