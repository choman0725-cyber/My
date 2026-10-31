"""DATA_AUDIT §2：c942660 舊 close vs 現行 FinMind close，重疊期差 >0.5% 的天數分布。"""
import io, subprocess, pandas as pd
ls = subprocess.run(['git', 'ls-tree', '--name-only', 'c942660', 'data/universe/prices/'], capture_output=True, text=True).stdout.split()
rows = []
for p in ls:
    s = p.split('/')[-1][:-4]
    o = pd.read_csv(io.StringIO(subprocess.run(['git', 'show', f'c942660:{p}'], capture_output=True, text=True).stdout))
    try: n = pd.read_csv(p)
    except FileNotFoundError: continue
    j = o.merge(n, on='date', suffixes=('_o', '_n')); r = (j.close_o / j.close_n - 1).abs()
    rows.append((s, len(j), int((r > 0.005).sum()), float(r.max())))
d = pd.DataFrame(rows, columns=['sid', 'overlap', 'days_gt', 'max'])
print('舊檔', len(ls), '檔；至少 1 天 >0.5%：', (d.days_gt > 0).sum(), '；>100 天：', (d.days_gt > 100).sum(), '；>1000 天：', (d.days_gt > 1000).sum())
print(d.sort_values('max', ascending=False).head(10).to_string())
