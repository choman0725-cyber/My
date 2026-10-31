"""把 data/SOX.csv、data/2382.csv 換成 FinMind 資料（先比對重疊期再寫檔）。
SOX：USStockPrice ^SOX（欄位 Open/High/Low/Close/Volume）。2382：data/universe/prices/2382.csv（FinMind 原始價＋自算 adj_close），期間同舊檔起點。"""
import json, pandas as pd
old = pd.read_csv('data/SOX.csv')
fm = pd.DataFrame(json.load(open('data/universe/_verify_cache/finmind/USStockPrice_^SOX_2015-01-01_2026-10-31.json'))['data'])
fm = fm.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})[['date', 'open', 'high', 'low', 'close', 'volume']]
j = old.merge(fm, on='date', how='outer', suffixes=('_o', '_f'), indicator=True)
b = j[j._merge == 'both']
print('SOX 舊', len(old), 'FinMind', len(fm), j._merge.value_counts().to_dict(),
      {c: float((b[c + '_o'] / b[c + '_f'] - 1).abs().max()) for c in ['open', 'high', 'low', 'close']})
print('  舊有 FinMind 無：', j[j._merge == 'left_only'].date.tolist(), '；FinMind 有舊無：', j[j._merge == 'right_only'].date.tolist()[:10])
fm.to_csv('data/SOX.csv', index=False, lineterminator='\n')
o2 = pd.read_csv('data/2382.csv'); u = pd.read_csv('data/universe/prices/2382.csv')
new = u[u.date >= o2.date.min()].reset_index(drop=True)
print('2382 舊', len(o2), o2.date.min(), o2.date.max(), '→ 新', len(new), new.date.min(), new.date.max())
new.to_csv('data/2382.csv', index=False, lineterminator='\n')
