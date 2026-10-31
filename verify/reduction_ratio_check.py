"""FinMind 減資資料集每一筆：程式算的股數比例 vs FinMind 已發行股數實際比例。"""
import sys, os; sys.path.insert(0, os.getcwd())
import pandas as pd, update_universe_finmind as u
fm = u.FinMind()
div = pd.read_csv('data/universe/dividend_all.csv', dtype={'stock_id': str})
rows = []
for f in sorted(os.listdir('data/universe/_verify_cache/finmind')):
    if not f.startswith('TaiwanStockCapitalReductionReferencePrice_'): continue
    sid = f.split('_')[1]
    red = fm.get('TaiwanStockCapitalReductionReferencePrice', sid, '2006-01-01', '2026-10-31', cached_only=True)
    if red.empty: continue
    p = pd.read_csv(f'data/universe/prices/{sid}.csv', usecols=['date', 'close']); p['date'] = pd.to_datetime(p.date)
    lvl = u.share_levels(fm.get('TaiwanStockShareholding', sid, '2006-01-01', '2026-10-31', cached_only=True))
    for d, r in u.reduction_share_ratios(red, div[div.stock_id == sid], p):
        act = u.shares_ratio_after(lvl, d, 40, up=False)
        x = red[pd.to_datetime(red.date) == d].iloc[0]
        rows.append((sid, f'{d:%Y-%m-%d}', x.ReasonforCapitalReduction, round(r, 4), None if act is None else round(act, 4)))
o = pd.DataFrame(rows, columns=['stock_id', 'date', 'reason', 'program', 'shares_actual'])
o['diff'] = (o.program / o.shares_actual - 1).abs().round(4)
print(o.to_string()); print('筆數', len(o), '；差 >1%：', (o['diff'] > 0.01).sum(), '；無股數資料：', o.shares_actual.isna().sum())
