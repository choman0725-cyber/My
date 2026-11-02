"""47 檔股票池逐檔拿掉跑 20 情境（2026-11-02 使用者：「把目前 47 檔個別跑 20 情境」）。
正式版 E＋D＋U1、5 檔不變；每次只拿掉一檔（46 檔），看這檔對結果的貢獻：
  拿掉後變差 → 這檔有貢獻；拿掉後變好 → 這檔拖累（配對相對 47 檔）。
另附基準 47 檔兩條 500 萬路徑裡這檔自己的筆數與損益。從沒買過的股票拿掉結果不變。
用法：python pool_loo_study.py　輸出：results/pool_loo_eval.csv"""
import time

import pandas as pd

import rules_research as rr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL, POOL
from pool_tech_study import restrict
from stock_fit import paired_from_files

rs.POOL = POOL                # pool_tech_study 匯入時把池子改回電子 90 檔，這裡改回正式版 47 檔

NAMES = pd.read_csv(ps.UNI / "industry_twse_elec.csv", dtype=str).set_index("stock_id")[["name", "industry"]]


def paths(G, dates, kw, s17):
    out = {}
    for sn, s in (("12-28", 1), ("01-03", s17)):
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
        out[sn] = (round(eq.iloc[-1] * CAPITAL / 1e4), tr)
    return out


def own_pnl(tr, sid):
    t = tr[tr["代號"] == sid]
    if t.empty:
        return 0, 0
    pnl = t["回收"].where(t["出場"].notna(), t["市值"]) - t["投入"]
    return len(t), round(pnl.sum() * CAPITAL / 1e4)


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    full = {k: G[k] for k in ("sub", "member", "sig", "zone")}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    kw = po.to_kw(rr.BASE)
    po.CONFIGS["base"] = rr.BASE
    po.apply(rr.BASE)
    base = po.evaluate(["base"], "loo_base").loc["base"]
    bp = paths(G, dates, kw, s17)
    print(f"基準 47 檔：三段 {base['三段平均']:.2f} σ {base['標準差平均']:.2f} 500萬 {bp['12-28'][0]}／{bp['01-03'][0]}", flush=True)
    rows = [dict(代號="—", 名稱="47 檔全部（基準）", 產業="", 三段平均=base["三段平均"], 標準差=base["標準差平均"],
                 最差10=base["最差10最小"], 萬1228=bp["12-28"][0], 萬0103=bp["01-03"][0])]
    for i, sid in enumerate(sorted(POOL)):
        t0 = time.time()
        own = [own_pnl(bp[k][1], sid) for k in ("12-28", "01-03")]
        restrict(G, full, set(POOL) - {sid})
        po.apply(rr.BASE)
        name = f"去{sid}"; po.CONFIGS[name] = rr.BASE
        m = po.evaluate([name], f"loo_{sid}").loc[name]
        p = paired_from_files("loo_base", f"loo_{sid}")
        mp = paths(G, dates, kw, s17)
        rows.append(dict(代號=sid, 名稱=NAMES.loc[sid, "name"], 產業=NAMES.loc[sid, "industry"].replace("設備業", "").replace("業", ""),
                         三段平均=m["三段平均"], 標準差=m["標準差平均"], 最差10=m["最差10最小"],
                         前7年配對=p["前7年配對"], 後3年配對=p["後3年配對"], 萬1228=mp["12-28"][0], 萬0103=mp["01-03"][0],
                         本檔筆數1228=own[0][0], 本檔損益萬1228=own[0][1], 本檔筆數0103=own[1][0], 本檔損益萬0103=own[1][1]))
        for f in RESULTS.glob(f"param_opt_loo_{sid}_*"):
            f.unlink()
        print(f"  [{i + 1}/{len(POOL)}] 去 {sid} {NAMES.loc[sid, 'name']}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} "
              f"配對 {p['前7年配對']}｜{p['後3年配對']} 500萬 {mp['12-28'][0]}／{mp['01-03'][0]}（{time.time() - t0:.0f}s）", flush=True)
    out = pd.DataFrame(rows)
    out["拿掉後三段差"] = (out["三段平均"] - base["三段平均"]).round(2)
    out["拿掉後σ差"] = (out["標準差"] - base["標準差平均"]).round(2)
    out.to_csv(RESULTS / "pool_loo_eval.csv", index=False, encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_loo_base_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print(out.sort_values("拿掉後三段差").to_string(index=False))


if __name__ == "__main__":
    main()
