import json, random, subprocess, time
from pathlib import Path
import pandas as pd
OUT = Path('data/universe/_verify_cache/pcf')
URL = ("https://etfapi.yuantaetfs.com/ectranslation/api/bridge?APIType=ETFAPI&CompanyName=YUANTAFUNDS&PageName=/x"
       "&DeviceId=null&FuncId=PCF/Daily&AppName=ETF&Device=3&Platform=ETF&ticker={etf}&date={d}")
def pcf(etf, d):
    f = OUT / f"{etf}_{d}.json"
    if not f.exists():
        r = subprocess.run(["curl", "-sS", "-f", "-m", "30", URL.format(etf=etf, d=d)], capture_output=True, text=True, check=True)
        f.write_text(r.stdout); time.sleep(0.5)
    j = json.loads(f.read_text())
    if not j or not j.get('PCF'): return None, None
    comp = (j.get("InKind") or {}).get("FundComposition") or []
    sw = (j.get("FundWeights") or {}).get("StockWeights") or []
    s = {c["stkcd"].strip() for c in comp} | {w.get("code", "").strip() for w in sw}
    return j['PCF']['anndate'], s
cons = pd.read_csv('data/universe/constituents.csv', dtype=str)
rng = random.Random(42)
days = pd.bdate_range('2006-01-02', '2015-09-18')
pick = sorted(rng.sample(list(days), 10))
for d in pick:
    for etf in ('0050', '0056'):
        if etf == '0056' and d < pd.Timestamp('2007-12-26'): continue
        ds = f"{d:%Y%m%d}"
        ann, s = pcf(etf, ds)
        if s is None: print(etf, ds, 'no PCF (holiday?)'); continue
        c = cons[cons.etf == etf]
        eff = c[c.effective_date <= f"{d:%Y-%m-%d}"].effective_date.max()
        m = set(c[c.effective_date == eff].stock_id)
        print(f"{etf} {ds} ann={ann} PCF={len(s)} cons(eff {eff})={len(m)} PCF-only={sorted(s-m)} cons-only={sorted(m-s)}")
