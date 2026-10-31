import pandas as pd
U='data/universe/'
d=pd.read_csv(U+'dividend_all.csv',dtype={'stock_id':str})
r=pd.read_csv(U+'dividend_result_all.csv',dtype={'stock_id':str}); r['date']=pd.to_datetime(r.date)
rows=[]
for _,x in d.iterrows():
    sid=x.stock_id
    try: p=pd.read_csv(U+f'prices/{sid}.csv',usecols=['date','close','adj_close'])
    except FileNotFoundError: continue
    p['date']=pd.to_datetime(p.date)
    st=(x.StockEarningsDistribution or 0)+(x.StockStatutorySurplus or 0)
    cash=(x.CashEarningsDistribution or 0)+(x.CashStatutorySurplus or 0)
    for kind,amt,col in (('stock',st,'StockExDividendTradingDate'),('cash',cash,'CashExDividendTradingDate')):
        if not (amt>0) or pd.isna(x[col]): continue
        dt=pd.Timestamp(x[col])
        if dt<p.date.min() or dt>p.date.max(): continue
        rr=r[(r.stock_id==sid)&((r.date-dt).abs()<=pd.Timedelta(days=5))]
        if rr.empty:
            # price before/after and adj ret
            b=p[p.date<dt].tail(1); a=p[p.date>=dt].head(1)
            ret=a.close.iloc[0]/b.close.iloc[0]-1 if len(a) and len(b) else None
            aret=a.adj_close.iloc[0]/b.adj_close.iloc[0]-1 if len(a) and len(b) else None
            rows.append((sid,x.year,kind,round(amt,4),dt.date(),b.close.iloc[0] if len(b) else None,a.close.iloc[0] if len(a) else None,round(ret,4) if ret is not None else None,round(aret,4) if aret is not None else None))
out=pd.DataFrame(rows,columns=['stock_id','year','kind','amount','ex_date','close_before','close_on','raw_ret','adj_ret']).drop_duplicates()
print(len(out)); print(out.to_string())
out.to_csv('data/universe/_verify_cache/missing_result_events.csv',index=False)
