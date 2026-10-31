"""修正用的額外 FinMind 資料：每日已發行股數（TaiwanStockShareholding）、減資（per stock）。優先抓有問題的股票。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fm, pandas as pd
S, E = '2006-01-01', '2026-10-31'
U = 'data/universe/'
q = pd.read_csv(U + '_verify_cache/quanxi_without_policy.csv', dtype={'stock_id': str}).stock_id.unique().tolist()
se = pd.read_csv(U + 'share_events_all.csv', dtype={'stock_id': str})
red = se[se.kind.isin(['減資', '推定減資'])].stock_id.unique().tolist()
rights = pd.read_csv(U + '_verify_cache/ref_eq_before.csv', dtype={'stock_id': str}).stock_id.unique().tolist()
allids = sorted(f[:-4] for f in os.listdir(U + 'prices') if f[:4] not in ('0050', '0051', '0056'))
order = list(dict.fromkeys(['2412'] + red + q + rights + allids))
for sid in red:
    fm.get('TaiwanStockCapitalReductionReferencePrice', sid, S, E)
print('reductions done', fm.CALLS, flush=True)
for i, sid in enumerate(order, 1):
    fm.get('TaiwanStockShareholding', sid, S, E)
    if i % 10 == 0: print(i, len(order), 'calls', fm.CALLS, flush=True)
print('ALL DONE', fm.CALLS, flush=True)
