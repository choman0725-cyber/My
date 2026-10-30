"""每半年結算：(1) 正式版本身每半年的帳面與已實現損益長什麼樣；(2) 若強制每半年結算（賣出有賺的／達停利的／全部），績效會變怎樣。"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS, SELL_COST
from portfolio_contrib import irr

def main():
    po.setup(); G=rs.G; dates=G["dates"]; cap=5e6
    po.apply(dr.FINAL); kw=po.to_kw(dr.FINAL)
    tr,eq=ps.run(G["sub"],G["member"],dates,capital=cap,**kw)
    # (1) 半年報表：期末資產、半年報酬、已實現損益、未實現損益、期末現金
    half=eq.resample("6ME").last().dropna()*cap
    rows=[]; prev=cap
    closed=tr[tr["出場"].notna()].copy(); closed["實現損益"]=(closed["回收"]-closed["投入"])*cap
    for end,v in half.items():
        start=end-pd.DateOffset(months=6)
        realized=closed[(closed["出場"]>start)&(closed["出場"]<=end)]["實現損益"].sum()
        n_sell=((closed["出場"]>start)&(closed["出場"]<=end)).sum()
        e_n=dates.get_indexer([end],method="ffill")[0]
        _,eq_h=ps.run(G["sub"],G["member"],dates,capital=cap,end_n=e_n,**kw)
        pos=eq_h.attrs["positions"]; cash=eq_h.attrs["cash"]*cap
        unreal=sum(q["shares"]*G["sub"][s]["close_ff"][e_n]*(1-SELL_COST)-q["cost"] for s,q in pos.items())*cap
        rows.append(dict(半年底=end.date(),期末資產萬=round(v/1e4),半年報酬pct=round(100*(v/prev-1),1),已實現損益萬=round(realized/1e4),賣出筆數=int(n_sell),
                         未實現損益萬=round(unreal/1e4),持股檔數=len(pos),現金萬=round(cash/1e4)))
        prev=v
    H=pd.DataFrame(rows); H.to_csv(RESULTS/"settle_half_year_report.csv",index=False,encoding="utf-8-sig")
    pd.set_option("display.width",300); pd.set_option("display.unicode.east_asian_width",True)
    print("【正式版 500萬：每半年報表】"); print(H.to_string(index=False))
    print(f"半年報酬為負的期數：{(H['半年報酬pct']<0).sum()}/{len(H)}；該半年沒有任何賣出的期數：{(H['賣出筆數']==0).sum()}")
    # (2) 強制結算變體
    C={"正式版（不結算）":{}, "每半年賣出有賺的":{"settle":(6,"profit")}, "每半年賣出達12%的（不管殖利率）":{"settle":(6,"target")},
       "每半年全部出清":{"settle":(6,"all")}, "每年賣出有賺的":{"settle":(12,"profit")}, "每年全部出清":{"settle":(12,"all")}}
    names=[]
    for n,x in C.items(): po.CONFIGS[n]={**dr.FINAL,**x}; names.append(n)
    m=po.evaluate(names,"settle")
    print("\n【穩健度】"); print(m.loc[names][po.SHOW].round(1).to_string())
    money=[]
    for n in names:
        po.apply(po.CONFIGS[n]); k=po.to_kw(po.CONFIGS[n]); tr,eq=ps.run(G["sub"],G["member"],dates,capital=cap,**k)
        h=eq.resample("6ME").last().dropna(); hr=h.pct_change(); hr.iloc[0]=h.iloc[0]-1
        cl=tr[tr["出場"].notna()]
        money.append(dict(版本=n,期末萬=round(eq.iloc[-1]*cap/1e4),IRR=round(irr([cap],[dates[1]],eq.iloc[-1]*cap,dates[-1]),1),最大回撤=round(100*(eq/eq.cummax()-1).min(),1),
                          筆數=len(tr),勝率=round(100*(cl["報酬%"]>0).mean(),1),半年為負期數=int((hr<0).sum()),半年報酬最差=round(100*hr.min(),1),半年報酬中位=round(100*hr.median(),1)))
    M=pd.DataFrame(money); M.to_csv(RESULTS/"settle_money.csv",index=False,encoding="utf-8-sig")
    print("\n【500萬 2017起】"); print(M.to_string(index=False))

if __name__=="__main__": main()
