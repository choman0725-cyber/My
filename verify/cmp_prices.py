import os
"""Task 2+3: compare data/universe/prices/<id>.csv with fresh FinMind fetch; recompute adj_close independently."""
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
SPLIT = pd.DataFrame(json.loads((C/'TaiwanStockSplitPrice_ALL_2000-01-01_2026-10-31.json').read_text())['data'])
se = pd.read_csv(U/'share_events_all.csv', dtype={'stock_id': str})
out_rows, diffs, adj_rows = [], [], []
for sid in (sys.argv[1:] or PRICE30):
    raw = load('TaiwanStockPrice', sid)
    if raw is None: continue
    f = pd.read_csv(U/f'prices/{sid}.csv')
    fm = raw.rename(columns={'max':'high','min':'low','Trading_Volume':'volume'})[['date','open','high','low','close','volume']]
    dupd = fm.date.duplicated().sum()
    m = fm.merge(f, on='date', how='outer', suffixes=('_fm','_f'), indicator=True)
    fm_only = m[m._merge=='left_only']; f_only = m[m._merge=='right_only']; both = m[m._merge=='both']
    # classify fm_only
    zero = fm_only[(fm_only.volume_fm<=0)|(fm_only.close_fm<=0)]
    other = fm_only.drop(zero.index)
    for _, x in other.iterrows():
        diffs.append((sid, x.date, 'FinMind有、檔案無', f"close={x.close_fm} vol={x.volume_fm}"))
    for _, x in f_only.iterrows():
        diffs.append((sid, x.date, '檔案有、FinMind無', f"close={x.close_f}"))
    nval = 0; open0 = 0
    for c in ['open','high','low','close','volume']:
        a, b = both[c+'_fm'].astype(float), both[c+'_f'].astype(float)
        bad = (a.round(4) - b).abs() > (0.5 if c=='volume' else 1e-6)
        for _, x in both[bad].iterrows():
            if c in ('open','high','low') and x[c+'_fm'] <= 0 and abs(x[c+'_f']-x.close_f) < 1e-9:
                open0 += 1; diffs.append((sid, x.date, f'{c}=0→改收盤(程式)', f"FinMind {c}={x[c+'_fm']} 檔案={x[c+'_f']}"))
            else:
                nval += 1; diffs.append((sid, x.date, f'{c}不一致', f"FinMind={x[c+'_fm']} 檔案={x[c+'_f']}"))
    out_rows.append(dict(stock_id=sid, fm_rows=len(fm), fm_dup_dates=dupd, file_rows=len(f), both=len(both),
                         fm_only_zero_vol=len(zero), fm_only_other=len(other), file_only=len(f_only), value_diff=nval, open0_fixed=open0,
                         first_fm=fm.date.min(), first_file=f.date.min(), last_fm=fm.date.max(), last_file=f.date.max()))
    # ---- task 3: independent adj_close ----
    ev = []
    res = load('TaiwanStockDividendResult', sid)
    if res is not None and len(res):
        for _, x in res.iterrows():
            if x.before_price > 0 and x.reference_price > 0: ev.append((x.date, x.reference_price / x.before_price, '除權息'))
    red = load('TaiwanStockCapitalReductionReferencePrice', sid)
    if red is not None and len(red):
        for _, x in red.iterrows():
            k = float(x.PostReductionReferencePrice) / float(x.ClosingPriceonTheLastTradingDay)
            if not any(abs((pd.Timestamp(x.date)-pd.Timestamp(d)).days)<=5 and abs(k/k0-1)<0.01 for d,k0,_ in ev): ev.append((x.date, k, '減資'))
    for _, x in SPLIT[SPLIT.stock_id==sid].iterrows():
        k = x.after_price / x.before_price
        if not any(abs((pd.Timestamp(x.date)-pd.Timestamp(d)).days)<=5 and abs(k/k0-1)<0.01 for d,k0,_ in ev): ev.append((x.date, k, '分割'))
    inf = [(r.date, 1/r.share_ratio, '推定減資') for r in se[(se.stock_id==sid)&(se.kind=='推定減資')].itertuples()]
    d = pd.to_datetime(f.date)
    for label, evs in (('A_FinMind事件', ev), ('B_加推定減資', ev+inf)):
        fac = np.ones(len(f))
        for dt, k, _ in evs: fac[(d < pd.Timestamp(dt)).values] *= k
        mine = f.close.values * fac
        rel = np.abs(mine / f.adj_close.values - 1)
        adj_rows.append(dict(stock_id=sid, version=label, n_events=len(evs), max_rel_diff=rel.max(), days_gt_1e4=(rel>1e-4).sum(),
                             first_day_ratio=f.adj_close.values[0]/mine[0]))
pd.set_option('display.width', 250)
o = pd.DataFrame(out_rows); print(o.to_string()); o.to_csv('data/universe/_verify_cache/task2_summary.csv', index=False)
dd = pd.DataFrame(diffs, columns=['stock_id','date','type','detail']); dd.to_csv('data/universe/_verify_cache/task2_diffs.csv', index=False)
print(dd.type.value_counts().to_string()); print(dd[~dd.type.str.contains('程式')].to_string())
a = pd.DataFrame(adj_rows); a.to_csv('data/universe/_verify_cache/task3_adj.csv', index=False); print(a.to_string())
