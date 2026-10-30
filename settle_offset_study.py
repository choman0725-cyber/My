"""每半年「補虧結算」：賣掉有賺的，用本期已實現獲利去認列虧損部位（合計仍 >= 0），其餘續抱，之後照規則重新選股。
檢查每半年的已實現損益是否都 >= 0，以及對長期績效的影響。"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS, SELL_COST
from portfolio_contrib import irr

def half_table(tr, eq, cap, kw, G, dates):
    half=eq.resample("6ME").last().dropna()*cap; rows=[]; prev=cap
    cl=tr[tr["出場"].notna()].copy(); cl["實現"]=(cl["回收"]-cl["投入"])*cap
    for end,v in half.items():
        st=end-pd.DateOffset(months=6); m=(cl["出場"]>st)&(cl["出場"]<=end)
        e_n=dates.get_indexer([end],method="ffill")[0]
        _,eq_h=ps.run(G["sub"],G["member"],dates,capital=cap,end_n=e_n,**kw); pos=eq_h.attrs["positions"]
        unreal=sum(q["shares"]*G["sub"][s]["close_ff"][e_n]*(1-SELL_COST)-q["cost"] for s,q in pos.items())*cap
        rows.append(dict(半年底=end.date(),期末資產萬=round(v/1e4),半年報酬pct=round(100*(v/prev-1),1),已實現萬=round(cl[m]["實現"].sum()/1e4),賣出筆數=int(m.sum()),
                         未實現萬=round(unreal/1e4),持股=len(pos),現金萬=round(eq_h.attrs["cash"]*cap/1e4))); prev=v
    return pd.DataFrame(rows)

def main():
    po.setup(); G=rs.G; dates=G["dates"]; cap=5e6
    C={"正式版（不結算）":{}, "半年補虧：賣有賺的＋認列小虧":{"settle":(6,"offset")}, "半年補虧：賣有賺的＋優先認列大虧":{"settle":(6,"offset_big")},
       "半年補虧：只賣達12%的＋認列小虧":{"settle":(6,"offset_target")}, "每年補虧：賣有賺的＋認列小虧":{"settle":(12,"offset")}, "半年全部出清（對照）":{"settle":(6,"all")}}
    names=[]
    for n,x in C.items(): po.CONFIGS[n]={**dr.FINAL,**x}; names.append(n)
    pd.set_option("display.width",300); pd.set_option("display.unicode.east_asian_width",True)
    tabs={}
    for n in names:
        po.apply(po.CONFIGS[n]); kw=po.to_kw(po.CONFIGS[n]); tr,eq=ps.run(G["sub"],G["member"],dates,capital=cap,**kw)
        H=half_table(tr,eq,cap,kw,G,dates); tabs[n]=(H,tr,eq)
        H.to_csv(RESULTS/f"settle_offset_half_{names.index(n)}.csv",index=False,encoding="utf-8-sig")
    for n in ("半年補虧：賣有賺的＋認列小虧","半年補虧：只賣達12%的＋認列小虧"):
        print(f"\n【{n}：每半年報表】"); print(tabs[n][0].to_string(index=False))
    m=po.evaluate(names,"settleoff")
    print("\n【穩健度】"); print(m.loc[names][po.SHOW].round(1).to_string())
    rows=[]
    for n,(H,tr,eq) in tabs.items():
        cl=tr[tr["出場"].notna()]
        rows.append(dict(版本=n,期末萬=round(eq.iloc[-1]*cap/1e4),IRR=round(irr([cap],[dates[1]],eq.iloc[-1]*cap,dates[-1]),1),最大回撤=round(100*(eq/eq.cummax()-1).min(),1),
                         筆數=len(tr),勝率=round(100*(cl["報酬%"]>0).mean(),1),已實現為負期數=int((H["已實現萬"]<0).sum()),已實現為零期數=int((H["已實現萬"]==0).sum()),
                         帳面為負期數=int((H["半年報酬pct"]<0).sum()),半年最差pct=H["半年報酬pct"].min()))
    M=pd.DataFrame(rows); M.to_csv(RESULTS/"settle_offset_money.csv",index=False,encoding="utf-8-sig")
    print("\n【500萬 2017起】"); print(M.to_string(index=False))

if __name__=="__main__": main()
