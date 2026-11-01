"""每個 ETF 每一期的每一檔成分股，在該期間內是否都有價格資料（沒有的列出來）。"""
import os, pandas as pd
U = 'data/universe/'
cons = pd.concat([pd.read_csv(U + 'constituents.csv', dtype=str)] + [pd.read_csv(U + f, dtype=str) for f in sorted(os.listdir(U)) if f.startswith('constituents_') and f.endswith('.csv')])
span = {f[:-4]: pd.read_csv(U + 'prices/' + f, usecols=['date']).date.agg(['min', 'max']).tolist() for f in os.listdir(U + 'prices')}
bad = []
for etf, g in cons.groupby('etf'):
    eff = sorted(g.effective_date.unique())
    for i, e in enumerate(eff):
        end = eff[i + 1] if i + 1 < len(eff) else '2026-10-30'
        for s in g[g.effective_date == e].stock_id:
            if s not in span:
                bad.append((etf, e, s, '沒有價格檔')); continue
            lo, hi = span[s]
            if lo > end or hi < e:
                bad.append((etf, e, s, f'價格 {lo}~{hi} 與期間 {e}~{end} 不重疊'))
print(f'{cons.etf.nunique()} 個 ETF、{len(cons)} 列；成分股期間沒有價格的：{len(bad)}')
for b in bad[:30]: print('  ', b)
