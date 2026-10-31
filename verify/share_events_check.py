"""Task 5: share_events_all.csv 每一筆能否由來源重算；6669/0050/2412/2357 明細。"""
import json, pandas as pd
U = 'data/universe/'
se = pd.read_csv(U + 'share_events_all.csv', dtype={'stock_id': str}); se['d'] = pd.to_datetime(se.date)
d = pd.read_csv(U + 'dividend_all.csv', dtype={'stock_id': str})
d['sd'] = pd.to_datetime(d.StockExDividendTradingDate, errors='coerce'); d['st'] = d.StockEarningsDistribution.fillna(0) + d.StockStatutorySurplus.fillna(0)
r = pd.read_csv(U + 'dividend_result_all.csv', dtype={'stock_id': str}); r['d'] = pd.to_datetime(r.date)
sp = pd.DataFrame(json.load(open(U + '_verify_cache/finmind/TaiwanStockSplitPrice_ALL_2000-01-01_2026-10-31.json'))['data']); sp['d'] = pd.to_datetime(sp.date)
bad = []
for _, x in se.iterrows():
    if x.kind == '配股':
        g = d[(d.stock_id == x.stock_id) & (d.sd == x.d) & (d.st > 0)]
        exp = 1 + g.st.sum() / 10 if len(g) else None
    elif x.kind == '分割':
        g = sp[(sp.stock_id == x.stock_id) & (sp.d == x.d)]; exp = (g.before_price / g.after_price).iloc[0] if len(g) else None
    elif x.kind == '配股或分割（除權結果）':
        g = r[(r.stock_id == x.stock_id) & (r.d == x.d)]; exp = (g.before_price / g.reference_price).iloc[0] if len(g) else None
    else:
        continue
    if exp is None or abs(exp / x.share_ratio - 1) > 1e-5: bad.append((x.stock_id, x.date, x.kind, x.share_ratio, exp))
print('配股/分割/除權結果 共', (se.kind.isin(['配股', '分割', '配股或分割（除權結果）'])).sum(), '筆，與來源重算不符：', bad)
# 股利政策裡有配股、但 share_events 沒有（例如同日同時有分割而被去重）
miss = []
for _, x in d[d.st > 0].iterrows():
    if pd.isna(x.sd): miss.append((x.stock_id, x.year, x.st, 'no ex date')); continue
    if se[(se.stock_id == x.stock_id) & ((se.d - x.sd).abs() <= pd.Timedelta(days=5))].empty:
        miss.append((x.stock_id, x.year, x.st, str(x.sd.date())))
print('股利政策有配股但 share_events 無：', len(miss), miss[:20])
print('分割資料集（FinMind 全市場）中本資料庫的股票：', sp[sp.stock_id.isin(se.stock_id.unique())][['date', 'stock_id', 'type', 'before_price', 'after_price']].values.tolist())
print(se[se.kind == '分割'][['stock_id', 'date', 'share_ratio']].values.tolist())
for s in ('6669', '0050', '2412', '2357'):
    print(s, se[se.stock_id == s][['date', 'kind', 'share_ratio']].values.tolist())
