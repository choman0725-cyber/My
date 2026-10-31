"""Task 3/5 輔助：(a) before_price 是否等於檔案前一日收盤；(b) reference_price==before_price 的「權」事件（多為現金增資）；
(c) 除權息結果有「權息」但股利政策沒有配股列（share_events 漏記配股）；(d) 股利政策有除權息日但除權息結果沒有（adj_close 漏調）。"""
import pandas as pd
U = 'data/universe/'
r = pd.read_csv(U + 'dividend_result_all.csv', dtype={'stock_id': str}); r['d'] = pd.to_datetime(r.date)
d = pd.read_csv(U + 'dividend_all.csv', dtype={'stock_id': str})
d['sd'] = pd.to_datetime(d.StockExDividendTradingDate, errors='coerce'); d['cd'] = pd.to_datetime(d.CashExDividendTradingDate, errors='coerce')
d['st'] = d.StockEarningsDistribution.fillna(0) + d.StockStatutorySurplus.fillna(0)
d['cash'] = d.CashEarningsDistribution.fillna(0) + d.CashStatutorySurplus.fillna(0)
P = {}
def px(s):
    if s not in P:
        try: P[s] = pd.read_csv(U + f'prices/{s}.csv', usecols=['date', 'close'])
        except FileNotFoundError: P[s] = None
    return P[s]
# (a)
tot = bad = 0
for _, x in r.iterrows():
    p = px(x.stock_id)
    if p is None or x.date > p.date.max(): continue
    pp = p[p.date < x.date].tail(1)
    if pp.empty: continue
    tot += 1; bad += abs(pp.close.iloc[0] / x.before_price - 1) > 0.001
print(f'(a) before_price vs 檔案前一日收盤：{tot} 筆，不一致 {bad} 筆')
# (b)
b = r[(r.reference_price - r.before_price).abs() < 1e-9].copy()
def kind(x):
    g = d[(d.stock_id == x.stock_id) & ((d.sd - x.d).abs() <= pd.Timedelta(days=5))]
    if g.empty: return '無股利政策列'
    if (g.st > 0).any(): return '配股'
    if (g.TotalNumberOfCashCapitalIncrease.fillna(0) > 0).any(): return '現金增資'
    return '政策列但無配股'
b['kind'] = b.apply(kind, axis=1); b['after_gap'] = 1 - b.after_price / b.before_price
print(f'(b) reference_price == before_price：{len(b)} 筆', b.kind.value_counts().to_dict(),
      '；after_price 比 before 低 平均 %.2f%%、最大 %.2f%%；2017 年後 %d 筆' % (100 * b.after_gap.mean(), 100 * b.after_gap.max(), (b.date >= '2017').sum()))
b.to_csv('data/universe/_verify_cache/ref_eq_before.csv', index=False)
# (c)
c = []
for _, x in r[r.stock_or_cache_dividend == '權息'].iterrows():
    g = d[(d.stock_id == x.stock_id) & ((d.sd - x.d).abs() <= pd.Timedelta(days=5)) & (d.st > 0)]
    if not g.empty: continue
    cash = d[(d.stock_id == x.stock_id) & ((d.cd - x.d).abs() <= pd.Timedelta(days=5))]
    if len(cash):
        k = (x.before_price - cash.cash.sum()) / x.reference_price
        if abs(k - 1) < 0.002: continue  # 有配息列、隱含配股≈0（多為同日現增），不算漏記
        c.append((x.stock_id, x.date, x.before_price, x.reference_price, round(k, 4), '有配息列'))
    else:
        c.append((x.stock_id, x.date, x.before_price, x.reference_price, None, '無任何股利政策列'))
c = pd.DataFrame(c, columns=['stock_id', 'date', 'before', 'reference', 'implied_ratio', 'note'])
c.to_csv('data/universe/_verify_cache/quanxi_without_policy.csv', index=False)
print(f'(c) 「權息」但股利政策無配股列：{len(c)} 筆，{c.stock_id.nunique()} 檔；年分分布', c.date.str[:4].value_counts().sort_index().to_dict())
print(c[c.stock_id.isin(['2412', '2330', '2357', '2382', '2880', '2317'])].to_string())
