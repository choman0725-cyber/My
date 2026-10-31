"""DATA_AUDIT.md 第 9 節 9.1/9.2/9.3/9.8 與第 2 節 6669 倍數。"""
import io, subprocess, pandas as pd
g = lambda p, **k: pd.read_csv(io.StringIO(subprocess.run(['git', 'show', 'c942660:' + p], capture_output=True, text=True).stdout), **k)
old = g('data/universe/prices/2880.csv'); new = pd.read_csv('data/universe/prices/2880.csv')
res = pd.read_csv('data/universe/dividend_result_all.csv', dtype={'stock_id': str})
for _, x in res[(res.stock_id == '2880') & (res.date >= '2023')].iterrows():
    print('9.1/9.2', x.date, x.stock_or_cache_dividend, 'before', x.before_price, '舊', old[old.date < x.date].close.iloc[-1], '新', new[new.date < x.date].close.iloc[-1])
o = g('data/universe/prices/6669.csv'); n = pd.read_csv('data/universe/prices/6669.csv')
j = o.merge(n, on='date', suffixes=('_o', '_n')); j['r'] = (j.close_n / j.close_o).round(3)
print('6669 新/舊 收盤比的分段：'); print(j.groupby('r').date.agg(['min', 'max', 'count']).sort_values('min').to_string())
p = n[(n.date >= '2017-11-13') & (n.date < '2019-03-27')]
bad = p[(p.open > p.high) | (p.open < p.low) | (p.close > p.high) | (p.close < p.low)]
print(f'6669 2017-11-13~2019-03-26（興櫃期）{len(p)} 列，開/收盤落在高低價外 {len(bad)} 列；2019-03-27 起 {(n.date >= "2019-03-27").sum()} 列')
L = g('results/對帳單_正式版.csv', dtype={'代號': str}); H = g('results/對帳單_正式版_年底持股.csv', dtype={'代號': str})
sign = L['動作'].map(lambda a: 1 if '賣' in a else -1)
c = (sign * L['金額']).groupby(L['代號']).sum()
last = H[(H['年底'] == H['年底'].max()) & (H['代號'] != '合計')]
c = c.add(last.set_index('代號')['市值'], fill_value=0).sort_values(ascending=False)
print('9.8 舊對帳單貢獻前 3：', c.head(3).round(0).to_dict())
eps = pd.read_csv('data/universe/eps_all.csv', dtype={'stock_id': str}); e = eps[eps.stock_id == '6669'].set_index('date').value
ttm = e['2019-06-30':'2020-03-31'].sum(); payout = 22.998816 / e['2019-03-31':'2019-12-31'].sum()
print(f'9.3 6669 2020-08-10：近四季 EPS(2019Q2~2020Q1)={ttm:.2f}，配息率(108年)={payout:.4f}，預估股利={ttm*payout:.2f}，收盤 838 → 殖利率 {100*ttm*payout/838:.2f}%')
