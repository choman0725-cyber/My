import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fm
from sample import PRICE30
INF = ['2014','2301','2303','2337','2352','2357','2379','2401','2408','2412','2475','2610','2618','2633','2707','3045','3665','4904','5880','6116']
S, E = '2006-01-01', '2026-10-31'
fm.get('TaiwanStockPrice', 'TAIEX', S, E)
fm.get('TaiwanStockSplitPrice', '', '2000-01-01', '2026-10-31')   # 全市場分割（免 data_id）
fm.get('TaiwanStockMonthRevenue', '2382', '2015-01-01', '2026-10-31')
for sid in PRICE30:
    fm.get('TaiwanStockPrice', sid, S, E)
    fm.get('TaiwanStockDividendResult', sid, S, E)
    if sid not in ('0050','0051','0056'):
        fm.get('TaiwanStockCapitalReductionReferencePrice', sid, S, E)
        fm.get('TaiwanStockFinancialStatements', sid, S, E)
        fm.get('TaiwanStockDividend', sid, S, E)
    print(sid, 'done; calls', fm.CALLS, flush=True)
for sid in INF:
    fm.get('TaiwanStockCapitalReductionReferencePrice', sid, S, E)
    fm.get('TaiwanStockDividendResult', sid, S, E)
    fm.get('TaiwanStockDividend', sid, S, E)
print('ALL DONE calls', fm.CALLS, flush=True)
