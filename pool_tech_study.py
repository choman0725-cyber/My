"""股票池再精挑成科技股（2026-11-01 使用者：「如果股票池再精挑為科技股呢」），正式版 5 檔規則不變，只縮小可買的股票。
細分類用證交所產業別（data/universe/industry_twse_elec.csv：上市中取 TWSE OpenAPI t187ap03_L，已下市依下市前分類手填）：
  半導體 29／電腦及週邊 18／電子零組件 13／光電 13／其他電子 7／通信網路 7／電子通路 3／資訊服務 1
版本（配對相對正式版 91 檔）：
  去光電（面板、鏡頭、LED）／去光電＋通路＋資訊服務＋其他電子／半導體＋電腦及週邊／只有半導體
市場中位數門檻照舊用 0050＋0056 全部成分股。注意：產業分類是今天的分類、挑「科技」本身帶有事後之見（近年半導體、AI 伺服器大漲）。
用法：python pool_tech_study.py　輸出：results/pool_tech_eval.csv、pool_tech_money.csv
     python pool_tech_study.py hist：2006 起快取，每年 1 月起跑、算到 2016 年底（AI 行情之前，檢查是否只是事後挑中近年強勢產業）
       與算到最新　輸出：results/pool_tech_hist.csv
     python pool_tech_study.py add [hist]：以「半導體＋電腦及週邊」47 檔為基準，分別加回零組件／通信／其他電子、三類全加
       （配對相對 47 檔）　輸出：results/pool_tech_add_*.csv
     python pool_tech_study.py single [hist]：47 檔個別加入台達電／國巨／欣興／啟碁／鴻海（使用者 2026-11-01）　輸出：results/pool_tech_single_*.csv"""
import sys
import numpy as np
import pandas as pd

import rules_research as rr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

IND = pd.read_csv(ps.UNI / "industry_twse_elec.csv", dtype=str).set_index("stock_id")["industry"]
CORE = {"半導體業", "電腦及週邊設備業", "電子零組件業", "通信網路業"}
POOLS = {"正式版（電子 91 檔）": None,
         "去光電": set(IND.index[IND != "光電業"]),
         "半導體＋電腦＋零組件＋通信": set(IND.index[IND.isin(CORE)]),
         "半導體＋電腦及週邊": set(IND.index[IND.isin({"半導體業", "電腦及週邊設備業"})]),
         "只有半導體": set(IND.index[IND == "半導體業"])}
SC = {"半導體業", "電腦及週邊設備業"}
POOLS_ADD = {"半導體＋電腦（47 檔）": set(IND.index[IND.isin(SC)]),
             "＋電子零組件": set(IND.index[IND.isin(SC | {"電子零組件業"})]),
             "＋通信網路": set(IND.index[IND.isin(SC | {"通信網路業"})]),
             "＋其他電子": set(IND.index[IND.isin(SC | {"其他電子業"})]),
             "＋三類全加": set(IND.index[IND.isin(SC | {"電子零組件業", "通信網路業", "其他電子業"})])}
SINGLE = {"2308": "台達電", "2327": "國巨", "3037": "欣興", "6285": "啟碁", "2317": "鴻海"}
POOLS_SINGLE = {"半導體＋電腦（47 檔）": POOLS_ADD["半導體＋電腦（47 檔）"],
                **{f"＋{n}": POOLS_ADD["半導體＋電腦（47 檔）"] | {sid} for sid, n in SINGLE.items()}}
OUT = "pool_tech"
if "add" in sys.argv:
    POOLS, OUT = POOLS_ADD, "pool_tech_add"
elif "single" in sys.argv:
    POOLS, OUT = POOLS_SINGLE, "pool_tech_single"


rs.POOL = rs.ELECTRONICS      # 這個研究從電子 90 檔往下縮，基準不是正式版池子


def restrict(G, full, pool):
    keep = set(full["sub"]) if pool is None else set(full["sub"]) & pool
    G["sub"] = {s: d for s, d in full["sub"].items() if s in keep}
    G["member"] = {s: v for s, v in full["member"].items() if s in keep}
    G["sig"] = {e: {s: v for s, v in m.items() if s in keep} for e, m in full["sig"].items()}
    G["zone"] = {e: {s: v for s, v in m.items() if s in keep} for e, m in full["zone"].items()}
    po._applied["buy"] = None
    return keep


def hist():
    import long_history as lh
    lh.POOL = lh.ELECTRONICS
    G = lh.setup(); d = G["dates"]
    full = {k: G[k] for k in ("sub", "member", "sig", "zone")}
    e16 = d.get_indexer([pd.Timestamp("2016-12-30")], method="ffill")[0]
    rows = []
    for name, pool in POOLS.items():
        keep = restrict(G, full, pool)
        po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
        for yr in range(2007, 2017):
            s = d.get_indexer([pd.Timestamp(yr, 1, 1)], method="bfill")[0]
            tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, start_n=s, **kw)
            q16 = eq.loc[:d[e16]]; v16 = q16.iloc[-1] / q16.iloc[0]          # eq 從起跑日開始
            rows.append(dict(版本=name, 檔數=len(keep), 起跑=yr,
                             至2016年底IRR=round(irr([CAPITAL], [d[s]], v16 * CAPITAL, d[e16]), 1) if yr < 2016 else np.nan,
                             至2016年底回撤=round(100 * (q16 / q16.cummax() - 1).min(), 1),
                             至今IRR=round(irr([CAPITAL], [d[s]], eq.iloc[-1] / eq.iloc[0] * CAPITAL, d[-1]), 1), 至今萬=round(eq.iloc[-1] / eq.iloc[0] * CAPITAL / 1e4)))
        print(f"  {name} 完成", flush=True)
    t = pd.DataFrame(rows); t.to_csv(RESULTS / f"{OUT}_hist.csv", index=False, encoding="utf-8-sig")
    base = t[t["版本"] == next(iter(POOLS))].set_index("起跑")
    summ = {}
    for name, g in t.groupby("版本", sort=False):
        g = g.set_index("起跑")
        d16 = (g["至2016年底IRR"] - base["至2016年底IRR"]).dropna(); dn = g["至今IRR"] - base["至今IRR"]
        summ[name] = dict(至2016平均IRR=round(g["至2016年底IRR"].mean(), 1), 至2016最差=g["至2016年底IRR"].min(), 至2016配對=f"{(d16 > .05).sum()}/{(d16.abs() <= .05).sum()}/{(d16 < -.05).sum()}",
                          至2016最差回撤=g["至2016年底回撤"].min(), 至今平均IRR=round(g["至今IRR"].mean(), 1), 至今配對=f"{(dn > .05).sum()}/{(dn.abs() <= .05).sum()}/{(dn < -.05).sum()}")
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(pd.DataFrame(summ).T.to_string()); print(t.pivot(index="起跑", columns="版本", values="至2016年底IRR").to_string())


def main():
    if "hist" in sys.argv:
        return hist()
    po.setup(); G = rs.G; dates = G["dates"]
    full = {k: G[k] for k in ("sub", "member", "sig", "zone")}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money = {}, {}
    for i, (name, pool) in enumerate(POOLS.items()):
        keep = restrict(G, full, pool)
        cfg = rr.BASE
        po.apply(cfg); kw = po.to_kw(cfg)
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], f"{OUT}_{i}").loc[name]
        if i:
            for k_, val in paired_from_files(f"{OUT}_0", f"{OUT}_{i}").items():
                m[k_] = val
        m["檔數"] = len(keep)
        results[name] = m
        po.apply(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0))
        print(f"  {name}（{len(keep)} 檔）完成：三段 {m['三段平均']:.2f}", flush=True)
    out = pd.DataFrame(results).T
    show = [c for c in ["檔數", "前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / f"{OUT}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"{OUT}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob(f"param_opt_{OUT}_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
