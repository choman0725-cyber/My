"""三件事，都以新正式版 E＋D 為基準：
A. 加碼改成「目前持有市值的 X%」並找等價比例：現行額度 30%／20% 在加碼當下約等於市值的 45～70%／25～35%，
   測 (第一次, 第二次)＝(0.5,0.3)、(0.6,0.3)、(0.7,0.35)、(0.4,0.25)、(0.5,0.25)，定期加碼另測市值 25%。
B. 續抱加信心：獲利 ≥12% 且殖利率已跌破續抱門檻時，若當天信心 ≥ hi（3／4）就先不賣（引擎 hold_keep 掛鉤）。
C. 續抱加碼：續抱中、信心 ≥3、出現加碼訊號 → 加碼部位市值 25%／50%，每個部位一次（引擎 win_add）。
每個版本跑 20 情境＋後 3 年＋配對＋500 萬。用法：python hold_add_confidence_study.py
輸出：results/hold_add_confidence_eval.csv、_money.csv"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

for a, b in ((0.5, 0.3), (0.6, 0.3), (0.7, 0.35), (0.4, 0.25), (0.5, 0.25)):
    po.ADD_SCHEMES[f"M 市值 {int(a * 100)}/{int(b * 100)}"] = ((a, b), (-0.15, -0.30))

V = {"正式版 E＋D": {}}
for a, b in ((0.5, 0.3), (0.6, 0.3), (0.7, 0.35), (0.4, 0.25), (0.5, 0.25)):
    V[f"A 加碼＝市值 {int(a * 100)}%/{int(b * 100)}%"] = {"cfg": {"adds": f"M 市值 {int(a * 100)}/{int(b * 100)}", "deep_add_base": "position"}}
V["A 加碼＝市值 50%/30%＋定期市值 25%"] = {"cfg": {"adds": "M 市值 50/30", "deep_add_base": "position", "time_add_base": "position", "time_add_amount": 0.25}}
V["A 加碼＝市值 60%/30%＋定期市值 25%"] = {"cfg": {"adds": "M 市值 60/30", "deep_add_base": "position", "time_add_base": "position", "time_add_amount": 0.25}}
V["B 續抱：信心≥3 不賣"] = {"hold_keep": 3}
V["B 續抱：信心≥4 不賣"] = {"hold_keep": 4}
V["C 續抱加碼：信心≥3 加市值 25%"] = {"win_ok": 3, "kw": {"win_add": 0.25}}
V["C 續抱加碼：信心≥3 加市值 50%"] = {"win_ok": 3, "kw": {"win_add": 0.5}}
V["B＋C：信心≥3 不賣＋加市值 25%"] = {"hold_keep": 3, "win_ok": 3, "kw": {"win_add": 0.25}}


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    results, money = {}, {}
    _to_kw = po.to_kw
    try:
        for i, (name, v) in enumerate(V.items()):
            cfg = {**dr.FINAL, **v.get("cfg", {})}
            po.apply(cfg)
            for sid, d in G["sub"].items():
                sc = d["conf_score"]
                d.pop("hold_keep", None); d.pop("win_add_ok", None)
                if "hold_keep" in v:
                    d["hold_keep"] = sc >= v["hold_keep"]
                if "win_ok" in v:
                    d["win_add_ok"] = sc >= v["win_ok"]
            extra = v.get("kw", {})
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = cfg
            m = po.evaluate([name], f"hac_{i}").loc[name]
            if i:
                for k_, val in paired_from_files("hac_0", f"hac_{i}").items():
                    m[k_] = val
            results[name] = m
            kw = po.to_kw(cfg)
            for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
                tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
                money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                         回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 加碼次數=int(tr["加碼"].sum()),
                                         勝率=round(100 * (tr[tr["出場"].notna()]["報酬%"] > 0).mean(), 0), 資金使用率=round(eq.attrs.get("資金使用率%", np.nan), 0))
            print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
        for d in G["sub"].values():
            d.pop("hold_keep", None); d.pop("win_add_ok", None)
        po.apply(dr.FINAL)
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / "hold_add_confidence_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "hold_add_confidence_money.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版 E＋D）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
