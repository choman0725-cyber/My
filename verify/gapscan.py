import pandas as pd, glob, os
r=pd.read_csv('data/universe/dividend_result_all.csv',dtype={'stock_id':str}); r['d']=pd.to_datetime(r.date)
se=pd.read_csv('data/universe/share_events_all.csv',dtype={'stock_id':str}); se['d']=pd.to_datetime(se.date)
for f in sorted(glob.glob('data/universe/prices/*.csv')):
    s=os.path.basename(f)[:-4]; p=pd.read_csv(f); p['d']=pd.to_datetime(p.date)
    for i in range(1,len(p)):
        g=(p.d[i]-p.d[i-1]).days
        if g<7: continue
        k=p.open[i]/p.close[i-1]; kc=p.close[i]/p.close[i-1]
        if max(k,kc)-1>0.06:
            near=lambda df: ((df[df.stock_id==s].d-p.d[i]).abs()<=pd.Timedelta(days=10)).any()
            if not near(r) and not near(se):
                print(s,p.date[i-1],p.close[i-1],'->',p.date[i],'open',p.open[i],'close',p.close[i],'gap',g,'k_open %.3f k_close %.3f'%(k,kc))
