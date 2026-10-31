"""Task 1: TAIEX.csv = 舊檔 (c942660) 列 + FinMind 列？重疊日是否一致？SOX/2382 是否改過？"""
import io, json, subprocess, pandas as pd
old = pd.read_csv(io.StringIO(subprocess.run(['git', 'show', 'c942660:data/TAIEX.csv'], capture_output=True, text=True).stdout))
cur = pd.read_csv('data/TAIEX.csv')
fm = pd.DataFrame(json.load(open('data/universe/_verify_cache/finmind/TaiwanStockPrice_TAIEX_2006-01-01_2026-10-31.json'))['data']).rename(columns={'max': 'high', 'min': 'low', 'Trading_Volume': 'volume'})
C = ['open', 'high', 'low', 'close', 'volume']
m = old.merge(cur, on='date', how='outer', indicator=True, suffixes=('_o', '_c'))
b = m[m._merge == 'both']
print('舊 vs 現行：', m._merge.value_counts().to_dict(), '；舊列是否原封不動：', all((b[c + '_o'] == b[c + '_c']).all() for c in C), old.date.min(), '~', old.date.max())
new = cur[~cur.date.isin(old.date)]
print('新增列', len(new), new.date.min(), '~', new.date.max(), '（2015 後：', new[new.date > '2015'].date.tolist(), '）')
for name, part in (('新增列', new), ('舊列（重疊期）', old)):
    j = part.merge(fm, on='date', suffixes=('', '_fm'))
    print(f'{name} vs FinMind：{len(part)} 列，對到 {len(j)} 列，五欄最大相對差', {c: float(((j[c] / j[c + "_fm"]) - 1).abs().max()) for c in C})
print('FinMind TAIEX', len(fm), fm.date.min(), fm.date.max(), '；FinMind 有現行無', sorted(set(fm.date) - set(cur.date))[:10], '；現行有 FinMind 無', sorted(set(cur.date) - set(fm.date))[:10])
for f in ('data/SOX.csv', 'data/2382.csv'):
    a = subprocess.run(['git', 'show', f'c942660:{f}'], capture_output=True).stdout
    print(f, '與 c942660 相同：', a == open(f, 'rb').read())
o = pd.read_csv('data/2382.csv'); f2 = pd.DataFrame(json.load(open('data/universe/_verify_cache/finmind/TaiwanStockPrice_2382_2006-01-01_2026-10-31.json'))['data'])
j = o.merge(f2, on='date', how='left'); r = (j.close_x / j.close_y - 1).abs()
print('data/2382.csv vs FinMind：', len(o), '列，收盤差 >0.1%', j[r > 0.001][['date', 'close_x', 'close_y']].values.tolist(), '；volume 相同比例 %.3f' % (j.volume == j.Trading_Volume).mean())
rv = pd.DataFrame(json.load(open('data/universe/_verify_cache/finmind/TaiwanStockMonthRevenue_2382_2015-01-01_2026-10-31.json'))['data'])
o = pd.read_csv('data/2382_revenue.csv'); m = o.merge(rv, on=['date', 'revenue_year', 'revenue_month'], how='left', suffixes=('', '_fm'))
print('data/2382_revenue.csv vs FinMind：', len(o), '列，對到', int(m.revenue_fm.notna().sum()), '，不同', int((m.revenue != m.revenue_fm).sum()))
C2 = 'data/universe/_verify_cache/finmind/'
for t, ds, k in (('2382_dividend', 'TaiwanStockDividend', ['date', 'year']), ('2382_dividend_result', 'TaiwanStockDividendResult', ['date'])):
    a = pd.read_csv(f'data/{t}.csv', dtype=str); b = pd.DataFrame(json.load(open(C2 + f'{ds}_2382_2006-01-01_2026-10-31.json'))['data']).astype(str)
    j = a.merge(b, on=k, how='left', suffixes=('', '_fm'), indicator=True)
    num = [c for c in a.columns if c not in k and c + '_fm' in j and c != 'stock_id']
    diff = sum(int((pd.to_numeric(j[c], errors='coerce') - pd.to_numeric(j[c + '_fm'], errors='coerce')).abs().gt(1e-6).sum()) for c in num)
    print(f'data/{t}.csv：{len(a)} 列，FinMind 沒有的 {int((j._merge == "left_only").sum())} 列，數值差異 {diff}')
fin = pd.read_csv('data/2382_financials.csv'); b = pd.DataFrame(json.load(open(C2 + 'TaiwanStockFinancialStatements_2382_2006-01-01_2026-10-31.json'))['data'])
j = fin.merge(b, on=['date', 'type', 'origin_name'], how='left')
print('data/2382_financials.csv：', len(fin), '列，對到', int(j.value_y.notna().sum()), '，數值差異', int(((j.value_x - j.value_y).abs() > 1e-6).sum()))
