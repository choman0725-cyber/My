import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import random, pandas as pd
from pcf_check import pcf, cons
rng = random.Random(7)
effs = cons[(cons.effective_date < '2015-09-21') & ~((cons.etf=='0050')&(cons.effective_date=='2006-01-02')) & ~((cons.etf=='0056')&(cons.effective_date<='2007-12-26'))][['etf','effective_date']].drop_duplicates()
sel = effs.sample(5, random_state=7)
for etf, eff in sel.values:
    e = pd.Timestamp(eff)
    for off in (-1, 0, 3, 6):
        d = e + pd.offsets.BDay(off)
        ann, s = pcf(etf, f"{d:%Y%m%d}")
        if s is None: print(etf, eff, off, 'none'); continue
        c = cons[cons.etf == etf]
        e2 = c[c.effective_date <= f"{d:%Y-%m-%d}"].effective_date.max()
        m = set(c[c.effective_date == e2].stock_id)
        print(f"{etf} eff={eff} day{off:+d} {d:%Y-%m-%d} PCF={len(s)} cons={len(m)} PCF-only={sorted(s-m)} cons-only={sorted(m-s)}")
