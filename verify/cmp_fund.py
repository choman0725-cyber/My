import os
"""Task 4: EPS / dividend / dividend result vs fresh FinMind."""
import json, sys
from pathlib import Path
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample import PRICE30
C = Path('data/universe/_verify_cache/finmind'); U = Path('data/universe')
S, E = '2006-01-01', '2026-10-31'
def load(ds, sid):
    f = C / f"{ds}_{sid}_{S}_{E}.json"
    return pd.DataFrame(json.loads(f.read_text())['data']) if f.exists() else None
FUND20 = [s for s in PRICE30 if s not in ('0050','0056')][:20]
eps = pd.read_csv(U/'eps_all.csv', dtype={'stock_id': str}); div = pd.read_csv(U/'dividend_all.csv', dtype={'stock_id': str})
res = pd.read_csv(U/'dividend_result_all.csv', dtype={'stock_id': str})
rows, issues = [], []
def cmp(sid, name, fm, db, keys, num):
    fm = fm.copy(); db = db.copy()
    for k in keys: fm[k] = fm[k].astype(str); db[k] = db[k].astype(str)
    dupfm = fm.duplicated(keys).sum(); dupdb = db.duplicated(keys).sum()
    m = fm.merge(db, on=keys, how='outer', suffixes=('_fm','_db'), indicator=True)
    for _, x in m[m._merge!='both'].iterrows():
        issues.append((sid, name, 'FinMind有、DB無' if x._merge=='left_only' else 'DB有、FinMind無', '/'.join(str(x[k]) for k in keys)))
    nv = 0
    b = m[m._merge=='both']
    for c in num:
        a1 = pd.to_numeric(b[c+'_fm'], errors='coerce'); a2 = pd.to_numeric(b[c+'_db'], errors='coerce')
        bad = ~(((a1-a2).abs() <= 1e-6*np.maximum(1,a1.abs())) | (a1.isna() & a2.isna()))
        for _, x in b[bad].iterrows():
            nv += 1; issues.append((sid, name, f'{c}不一致', f"{'/'.join(str(x[k]) for k in keys)} FinMind={x[c+'_fm']} DB={x[c+'_db']}"))
    return dict(stock_id=sid, table=name, fm=len(fm), db=len(db), both=len(b), fm_only=(m._merge=='left_only').sum(), db_only=(m._merge=='right_only').sum(),
                value_diff=nv, dup_fm=dupfm, dup_db=dupdb)
for sid in FUND20:
    fin = load('TaiwanStockFinancialStatements', sid)
    if fin is None: continue
    fe = fin[fin.type=='EPS'][['stock_id','date','value']] if len(fin) else pd.DataFrame(columns=['stock_id','date','value'])
    rows.append(cmp(sid, 'eps', fe, eps[eps.stock_id==sid], ['date'], ['value']))
    dv = load('TaiwanStockDividend', sid)
    if dv is not None:
        num = ['StockEarningsDistribution','StockStatutorySurplus','CashEarningsDistribution','CashStatutorySurplus','TotalNumberOfCashCapitalIncrease']
        cols = ['date','year','StockExDividendTradingDate','CashExDividendTradingDate'] + num
        dvf = dv[cols] if len(dv) else pd.DataFrame(columns=cols)
        dbd = div[div.stock_id==sid][cols].copy()
        for c in ('StockExDividendTradingDate','CashExDividendTradingDate'):
            dvf = dvf.assign(**{c: dvf[c].replace('', np.nan)})
        rows.append(cmp(sid, 'dividend', dvf, dbd, ['date','year'], num))
    rs = load('TaiwanStockDividendResult', sid)
    if rs is not None:
        cols = ['date','before_price','after_price','stock_and_cache_dividend','reference_price']
        rsf = rs[cols] if len(rs) else pd.DataFrame(columns=cols)
        rows.append(cmp(sid, 'div_result', rsf, res[res.stock_id==sid][cols], ['date'], cols[1:]))
pd.set_option('display.width', 250)
o = pd.DataFrame(rows); print(o.to_string()); o.to_csv('data/universe/_verify_cache/task4_summary.csv', index=False)
i = pd.DataFrame(issues, columns=['stock_id','table','type','detail']); i.to_csv('data/universe/_verify_cache/task4_issues.csv', index=False); print(i.to_string())
print('FUND20', FUND20)
