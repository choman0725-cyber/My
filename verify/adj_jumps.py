"""9.5：還原日報酬絕對值超過漲跌幅（2015-06 前 7%、之後 10%，各加 0.1% 容差）的日子。"""
import glob, os, pandas as pd
rows = []
for f in sorted(glob.glob('data/universe/prices/*.csv')):
    s = os.path.basename(f)[:-4]; p = pd.read_csv(f); r = p.adj_close.pct_change()
    lim = pd.Series(0.10, index=p.index); lim[p.date < '2015-06-01'] = 0.07
    for i in p.index[r.abs() > lim + 0.001]:
        rows.append((s, p.date[i], round(r[i], 4), p.close[i - 1], p.close[i], (pd.Timestamp(p.date[i]) - pd.Timestamp(p.date[i - 1])).days))
d = pd.DataFrame(rows, columns=['stock_id', 'date', 'adj_ret', 'prev_close', 'close', 'gap_days'])
d.to_csv('data/universe/_verify_cache/adj_jumps.csv', index=False)
print(len(d), '天；', d.stock_id.nunique(), '檔'); print(d.groupby('stock_id').date.agg(['count', 'min', 'max']).sort_values('count', ascending=False).to_string())
for s, dt in (('0050', '2025-06-18'), ('6669', '2026-09-02')):
    p = pd.read_csv(f'data/universe/prices/{s}.csv'); i = p.index[p.date == dt][0]; print(s, dt, '還原日報酬 %.4f' % (p.adj_close[i] / p.adj_close[i - 1] - 1))
