"""「一律用推估、公告後對照預期」的規則比較。

殖利率：進場與續抱一律用推估值（近四季 EPS × 近 3 年平均配息率），年配股已公告的股利不拿來當殖利率（＝yield_variant_study 的 A0）。
公告對照：年配股每次股利公告時，把公告金額和公告前一天的推估值比較；低於推估值 × (1 − 容忍度) 就標記「不如預期」，
  標記從公告日持續到除息日；持股被標記後依 miss_exit 出場：
    伺機＝出現爆量上影線或爆量長黑、且扣成本不賠錢就賣（同「被移出成分股」的做法）；隔天賣＝隔天開盤直接賣。
  符合預期或更好：不做任何事，照原本的續抱條件（獲利 ≥ 12% 且推估殖利率 < 4.75% 才賣）。
  半年配、季配的股票沒有「一年一次公告 vs 年度推估」的對應關係，不做對照。
另測一組用「下一年推估」（近四季 EPS × (1＋近 2 季營收年增) × 利潤率係數，yield_variant_study 的 H5）當預期值。
用法：python miss_study.py [main|ext|ext2|cut]（需 results/portfolio_prepared.pkl 與 data/universe/financials_all.csv）
"""
import pickle

import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

TOLS = (0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
VARIANTS = {"正式版（已公告用公告值）": dict(est="A", miss=None),
            "A0 一律推估、不對照": dict(est="A0", miss=None)}
for tol in TOLS:
    for mode, mname in (("tech_profit", "伺機出場"), ("immediate", "隔天賣")):
        VARIANTS[f"A0＋低於預期{tol:.0%}→{mname}"] = dict(est="A0", miss=(tol, mode))
VARIANTS["H5 下一年推估＋低於預期10%→伺機出場"] = dict(est="H5", miss=(0.10, "tech_profit"))
VARIANTS["H5 下一年推估＋低於預期10%→隔天賣"] = dict(est="H5", miss=(0.10, "immediate"))
# 第二輪（python miss_study.py ext）：容忍度往外推，以及把對照規則蓋在正式版殖利率（已公告用公告值）上
EXT_TOLS = (0.25, 0.30, 0.40)
EXT = {"正式版（已公告用公告值）": dict(est="A", miss=None)}
for tol in (0.20, 0.30):
    for mode, mname in (("tech_profit", "伺機出場"), ("immediate", "隔天賣")):
        EXT[f"正式版殖利率＋低於預期{tol:.0%}→{mname}"] = dict(est="A", miss=(tol, mode))
for tol in EXT_TOLS:
    for mode, mname in (("tech_profit", "伺機出場"), ("immediate", "隔天賣")):
        EXT[f"A0＋低於預期{tol:.0%}→{mname}"] = dict(est="A0", miss=(tol, mode))
# 第三輪（python miss_study.py ext2）：正式版殖利率＋對照規則，容忍度 20% 的相鄰值 15%／25%
EXT2 = {"正式版（已公告用公告值）": dict(est="A", miss=None)}
for tol in (0.15, 0.25):
    for mode, mname in (("tech_profit", "伺機出場"), ("immediate", "隔天賣")):
        EXT2[f"正式版殖利率＋低於預期{tol:.0%}→{mname}"] = dict(est="A", miss=(tol, mode))
# 第四輪（python miss_study.py cut）：「不如預期」改看有沒有真的砍股利（公告低於去年實際股利），正式版殖利率＋伺機出場
CUT = {"正式版（已公告用公告值）": dict(est="A", miss=None)}
for ct in (0.0, 0.10, 0.20):
    CUT[f"正式版殖利率＋砍股利{ct:.0%}以上→伺機出場"] = dict(est="A", miss=(0.0, "tech_profit"), kind="cut", cut_tol=ct)
for tol in (0.10, 0.20):
    CUT[f"正式版殖利率＋低於推估{tol:.0%}且低於去年→伺機出場"] = dict(est="A", miss=(tol, "tech_profit"), kind="both")
CUT["正式版殖利率＋砍股利10%以上→隔天賣"] = dict(est="A", miss=(0.0, "immediate"), kind="cut", cut_tol=0.10)
SETS = {"main": VARIANTS, "ext": EXT, "ext2": EXT2, "cut": CUT}


def build(data, dates):
    """回傳三種推估殖利率陣列 {est: {sid: array}} 與年配股公告事件表（含公告前推估值 A0／H5、去年股利、除息日）。"""
    eps_all = pd.read_csv(ps.UNI / "eps_all.csv")
    div_all = pd.read_csv(ps.UNI / "dividend_all.csv")
    res_all = pd.read_csv(ps.UNI / "dividend_result_all.csv")
    fin_all = pd.read_csv(ps.UNI / "financials_all.csv")
    est, events = {"A": {}, "A0": {}, "H5": {}}, []
    for sid in data:
        df, raw_close = ps.load_prices(sid)
        eps, div = ps.eps_table(eps_all, sid), ps.dividend_events(div_all, sid, res_all)
        mt = ps.margin_table(fin_all, sid)
        f5 = ps.margin_factor(df.index, mt) * ps.growth_factor(df.index, eps, mt, kind="rev").fillna(1.0)
        dps = {"A": ps.forward_dividend(df.index, eps, div),
               "A0": ps.forward_dividend(df.index, eps, div, use_announced=False),
               "H5": ps.forward_dividend(df.index, eps, div, factor=f5, use_announced=False)}
        for k, v in dps.items():
            est[k][sid] = (100 * v / raw_close).reindex(dates).values
        if not len(div) or not (div.groupby("fy").size() == 1).all():
            continue
        by = div.groupby("fy")["cash"].sum()
        for _, r in div.iterrows():
            if pd.isna(r["ex_date"]):
                continue
            row = dict(代號=sid, 年度=r["fy"], 公告=r["announced"], 除息=r["ex_date"], 公告值=r["cash"], 去年股利=by.get(r["fy"] - 1, np.nan))
            for k in ("A0", "H5"):
                before = dps[k][dps[k].index < r["announced"]].dropna()
                row[f"推估_{k}"] = before.iloc[-1] if len(before) else np.nan
            events.append(row)
    ev = pd.DataFrame(events)
    ev["差異"] = 100 * (ev["公告值"] / ev["推估_A0"] - 1)
    ev["對去年"] = 100 * (ev["公告值"] / ev["去年股利"] - 1)
    return est, ev


def flags(ev, dates, est_key, kind, tol, cut_tol=0.0):
    """依規則把事件轉成每檔每日的「不如預期」標記（公告日到除息日）。
    kind="est"：公告值 < 推估 × (1 − tol)；"cut"：公告值 < 去年股利 × (1 − cut_tol)；"both"：兩者皆是。"""
    e = ev.dropna(subset=[f"推估_{est_key}"])
    below_est = e["公告值"] < e[f"推估_{est_key}"] * (1 - tol)
    cut = (e["去年股利"] > 0) & (e["公告值"] < e["去年股利"] * (1 - cut_tol))
    hit = {"est": below_est, "cut": cut, "both": below_est & cut}[kind]
    out = {}
    for sid, g in e[hit].groupby("代號"):
        f = np.zeros(len(dates), bool)
        for _, r in g.iterrows():
            f |= np.asarray((dates >= r["公告"]) & (dates < r["除息"]))
        out[sid] = f
    return out


_orig_to_kw = po.to_kw
def to_kw2(cfg):
    kw = _orig_to_kw({k: v for k, v in cfg.items() if k not in ("miss_exit", "miss_key")})
    if cfg.get("miss_exit"):
        kw.update(miss_exit=cfg["miss_exit"], miss_key=cfg["miss_key"])
    return kw
po.to_kw = to_kw2


def main(which="main"):
    variants = SETS[which]
    po.setup(); G = rs.G; dates = G["dates"]
    data, _ = pickle.loads(ps.PREPARED.read_bytes())
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    mem_all = ps.membership(cons, dates)
    est, events = build(data, dates)
    import warnings; warnings.simplefilter("ignore", FutureWarning)
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    ev = events[events["年度"] >= 2016]
    print(f"【全池年配股公告 vs 公告前推估（A0），2016 年起 {len(ev)} 筆】")
    print("  低於推估的比例：", {f"低於{t:.0%}": f"{100 * (ev['差異'] < -100 * t).mean():.0f}%" for t in TOLS},
          "　中位差異", round(ev["差異"].median(), 1), "%")
    print("  低於去年股利的比例：", {f"砍{t:.0%}以上": f"{100 * (ev['對去年'] < -100 * t).mean():.0f}%" for t in (0.0, 0.10, 0.20)})
    ev.round(2).to_csv(RESULTS / "miss_study_events.csv", index=False, encoding="utf-8-sig")

    rows, money = {}, []
    for name, spec in variants.items():
        Y = est[spec["est"]]
        for sid, d in G["sub"].items():
            d["yield"] = Y[sid]
        if spec["miss"]:
            fl = flags(events, dates, "A0" if spec["est"] == "A" else spec["est"], spec.get("kind", "est"),
                       spec["miss"][0], spec.get("cut_tol", 0.0))   # A 公告前的推估＝A0
            for sid, d in G["sub"].items():
                d["miss"] = fl.get(sid, np.zeros(len(dates), bool))
        Yall = pd.DataFrame({s: np.where(mem_all[s].values, Y[s], np.nan) for s in Y if s in mem_all}, index=dates)
        po._mk[("all", len(dates))] = (Yall.median(axis=1).values, Yall.std(axis=1).values, Yall.notna().sum(axis=1).values)
        po._applied.clear()
        cfg = {**dr.FINAL}
        if spec["miss"]:
            cfg.update(miss_exit=spec["miss"][1], miss_key="miss")
        po.CONFIGS[name] = cfg
        po.apply(cfg)
        m = po.evaluate([name], f"miss_{which}")
        rows[name] = m.loc[name]
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **po.to_kw(cfg))
        cl = tr[tr["出場"].notna()]
        ms = cl[cl["原因"] == "股利不如預期出場"]
        money.append(dict(版本=name, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                          最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                          不如預期出場=len(ms), 其平均報酬=round(ms["報酬%"].mean(), 1) if len(ms) else None,
                          平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
        tr.to_csv(RESULTS / f"miss_study_trades_{name}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name} 完成", flush=True)
    M = pd.DataFrame(rows).T
    M.round(2).to_csv(RESULTS / f"miss_study_{which}_summary.csv", encoding="utf-8-sig")
    pd.DataFrame(money).to_csv(RESULTS / f"miss_study_{which}_money.csv", index=False, encoding="utf-8-sig")
    print("\n【穩健度：前 7 年 20 情境、後 3 年延續／單獨】")
    print(M[po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    print("\n【500 萬 2017 起不追加】")
    print(pd.DataFrame(money).to_string(index=False))


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "main")
