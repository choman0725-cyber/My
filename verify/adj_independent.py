"""修正後 adj_close 的獨立重算（不 import update_universe_finmind），30 檔抽樣＋全部 188 檔。
事件：
  a. 除權息結果：參考價÷前收；參考價＝前收而 after_price 不同時（現增除權）用 after_price。
  b. 股利政策有、除權息結果（±5 天）沒有的配股配息：(P−現金)÷(1+配股/10)÷P；減資／分割日 ±5 天內不補。
  c. FinMind 減資資料集：參考價÷前收。 d. 分割：after÷before。
  e. 2011 前減資：人工表（參考價、或 (P−退還現金)÷官方比例；現金減資沒寫金額＝10×(1−比例)）；
     人工表沒有、share_events 標「類型未查證」的：1÷比例。
"""
import json, os, sys
import numpy as np, pandas as pd
U = 'data/universe/'; C = U + '_verify_cache/finmind/'
res = pd.read_csv(U + 'dividend_result_all.csv', dtype={'stock_id': str})
dv = pd.read_csv(U + 'dividend_all.csv', dtype={'stock_id': str})
man = pd.read_csv(U + 'capital_reductions_manual.csv', dtype={'stock_id': str})
se = pd.read_csv(U + 'share_events_all.csv', dtype={'stock_id': str})
sp = pd.DataFrame(json.load(open(C + 'TaiwanStockSplitPrice_ALL_2000-01-01_2026-10-31.json'))['data'])
def red(sid):
    f = C + f'TaiwanStockCapitalReductionReferencePrice_{sid}_2006-01-01_2026-10-31.json'
    return pd.DataFrame(json.load(open(f))['data']) if os.path.exists(f) else pd.DataFrame()
ids = sys.argv[1:] or sorted(f[:-4] for f in os.listdir(U + 'prices'))
worst = []
for sid in ids:
    p = pd.read_csv(U + f'prices/{sid}.csv'); dates = pd.to_datetime(p.date); close = p.close.values
    def prev_close(d):
        i = dates.searchsorted(d); return (dates[i] if i < len(dates) else None), (close[i - 1] if 0 < i <= len(dates) else None)
    ev = []
    r = res[res.stock_id == sid]
    for x in r.itertuples():
        ref = x.after_price if abs(x.reference_price - x.before_price) < 1e-9 and abs(x.after_price / x.before_price - 1) > 0.0005 else x.reference_price
        ev.append((pd.Timestamp(x.date), ref / x.before_price))
    rd = red(sid)
    hard = []
    for x in rd.itertuples():
        ev.append((pd.Timestamp(x.date), float(x.PostReductionReferencePrice) / float(x.ClosingPriceonTheLastTradingDay))); hard.append(pd.Timestamp(x.date))
    for x in sp[sp.stock_id == sid].itertuples():
        ev.append((pd.Timestamp(x.date), x.after_price / x.before_price)); hard.append(pd.Timestamp(x.date))
    for m in man[man.stock_id == sid].itertuples():
        t, P = prev_close(pd.Timestamp(m.date))
        ratio = m.share_ratio if pd.notna(m.share_ratio) else float(se[(se.stock_id == sid) & (se.date == m.date)].share_ratio.iloc[0])
        ref = m.ref_price if pd.notna(m.ref_price) else (P - (m.cash_per_share if pd.notna(m.cash_per_share) else (10 * (1 - ratio) if '現金' in m.type else 0))) / ratio
        ev.append((t, ref / P)); hard.append(t)
    for x in se[(se.stock_id == sid) & se.kind.str.contains('類型未查證')].itertuples():
        ev.append((pd.Timestamp(x.date), 1 / x.share_ratio)); hard.append(pd.Timestamp(x.date))
    g = dv[dv.stock_id == sid]; agg = {}
    for x in g.itertuples():
        st = (x.StockEarningsDistribution or 0) + (x.StockStatutorySurplus or 0); cs = (x.CashEarningsDistribution or 0) + (x.CashStatutorySurplus or 0)
        if pd.notna(x.StockExDividendTradingDate) and st > 0: agg.setdefault(pd.Timestamp(x.StockExDividendTradingDate), [0, 0])[0] += st
        if pd.notna(x.CashExDividendTradingDate) and cs > 0: agg.setdefault(pd.Timestamp(x.CashExDividendTradingDate), [0, 0])[1] += cs
    rdates = pd.to_datetime(r.date)
    for d, (st, cs) in agg.items():
        if ((rdates - d).abs() <= pd.Timedelta(days=5)).any() or d <= dates.iloc[0] or d > dates.iloc[-1]: continue
        t, P = prev_close(d)
        if any(abs((t - h).days) <= 5 for h in hard): continue
        ev.append((t, (P - cs) / (1 + st / 10) / P))
    fac = np.ones(len(p))
    for d, k in ev: fac[(dates < d).values] *= k
    rel = np.abs(close * fac / p.adj_close.values - 1)
    worst.append((sid, len(ev), float(rel.max()), int((rel > 1e-4).sum())))
w = pd.DataFrame(worst, columns=['stock_id', 'events', 'max_rel_diff', 'days_gt_1e-4'])
print(f'{len(w)} 檔；最大相對差 {w.max_rel_diff.max():.2e}；有任何一天差 >1e-4 的檔數 {(w["days_gt_1e-4"] > 0).sum()}')
print(w[w['days_gt_1e-4'] > 0].to_string())
