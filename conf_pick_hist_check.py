"""conf_pick_study 的①（信心高者先買）用真歷史中位數重驗：20 情境＋後 3 年＋配對＋37 個起跑日 500 萬（2026-11-01）。用法：python conf_pick_hist_check.py"""
import numpy as np
import pandas as pd
import param_opt as po, robust_study as rs, daily_run as dr, portfolio_study as ps, rules_ext, median_hist_study as mh
from stock_fit import paired_from_files
from backtest import RESULTS
po.setup(); G = rs.G; d = G["dates"]
rules_ext.own_median = mh.hist_median(G)
rows = {}
for i, (name, ex) in enumerate((("正式（真3年）", {}), ("信心優先（真3年）", {"cand_order": "conf"}))):
    po._applied["buy"] = None
    cfg = {**dr.FINAL, **ex}; po.CONFIGS[name] = cfg
    m = po.evaluate([name], f"pickh_{i}").loc[name]
    if i:
        for k_, v_ in paired_from_files("pickh_0", "pickh_1").items(): m[k_] = v_
    po._applied["buy"] = None; po.apply(cfg); kw = po.to_kw(cfg)
    v = [ps.run(G["sub"], G["member"], d, capital=5e6, start_n=s, **kw)[1].iloc[-1] * 500 for s in range(1, 38)]
    m["37起跑中位"] = round(np.median(v)); m["37起跑p10"] = round(np.percentile(v, 10)); rows[name] = m; rows[name + "_v"] = v
a, b = np.array(rows["正式（真3年）_v"]), np.array(rows["信心優先（真3年）_v"]); df = b - a
for f in RESULTS.glob("param_opt_pickh_*"): f.unlink()
out = pd.DataFrame({k: v for k, v in rows.items() if not k.endswith("_v")}).T
cols = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差", "37起跑中位", "37起跑p10"] if c in out]
pd.set_option("display.width", 300); print(out[cols].to_string())
print("37 起跑日 好/平/差", (df > 1).sum(), (abs(df) <= 1).sum(), (df < -1).sum(), "中位差", round(np.median(df)), "2016-12-28", round(a[0]), round(b[0]), "2017-01-03", round(a[3]), round(b[3]))
