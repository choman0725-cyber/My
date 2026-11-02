"""換股：名額滿時，新買點的「預期肉」比持股「剩餘肉」多 margin 以上就隔天切換（2026-11-02 使用者）。
使用者原案：持股已賺 ≥10%、新股預期 − 持股剩餘 ≥10 個百分點。另跑鄰近門檻看是否只是剛好。
剩餘／預期肉的定義見 portfolio_study.run 的 switch 說明（停利 12% 與殖利率跌破續抱門檻都成立的價位）。
用法：python switch_study.py　輸出：results/switch_eval.csv、results/switch_money.csv
     python switch_study.py v2：第二版（使用者 2026-11-02）：持股賺 ≥12% 才比；肉一律用 5% 殖利率價位算（不設停利下限）；
       用金額比：新股預期獲利（當天額度 × 首買比例〔信心 ≥3 為 80%〕× 預期%）比持股剩餘獲利（賣出金額 × 剩餘%）多 ≥ 賣出金額的 10% 就換
       輸出：results/switch_v2_*.csv"""
import sys

import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

VARIANTS = {"正式版": dr.FINAL,
            "換股 賺≥10%·差≥10點（原案）": {**dr.FINAL, "switch": {"min_gain": 0.10, "margin": 0.10}},
            "換股 賺≥10%·差≥5點": {**dr.FINAL, "switch": {"min_gain": 0.10, "margin": 0.05}},
            "換股 賺≥10%·差≥20點": {**dr.FINAL, "switch": {"min_gain": 0.10, "margin": 0.20}},
            "換股 賺≥0%·差≥10點": {**dr.FINAL, "switch": {"min_gain": 0.0, "margin": 0.10}},
            "換股 賺≥20%·差≥10點": {**dr.FINAL, "switch": {"min_gain": 0.20, "margin": 0.10}}}

OUT = "switch"
if "v2" in sys.argv:
    _V2 = {"min_gain": 0.12, "hy": 5.0, "floor": False, "money": True, "margin": 0.10}
    VARIANTS = {"正式版": dr.FINAL,
                "v2 賺≥12%·5%殖利率·金額多10%（使用者）": {**dr.FINAL, "switch": _V2},
                "v2 同上·只比百分比（不看金額）": {**dr.FINAL, "switch": {**_V2, "money": False}},
                "v2 金額多5%": {**dr.FINAL, "switch": {**_V2, "margin": 0.05}},
                "v2 金額多20%": {**dr.FINAL, "switch": {**_V2, "margin": 0.20}}}
    OUT = "switch_v2"


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(VARIANTS.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"sw_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("sw_0", f"sw_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            sw = tr[tr["原因"].astype(str).str.startswith("換股")]
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 換股次數=len(sw),
                                     換股時已賺平均=round(sw["報酬%"].mean(), 1) if len(sw) else None)
            if i == 1 and sn == "2017-01-03":
                tr.to_csv(RESULTS / f"{OUT}_trades_orig.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / f"{OUT}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"{OUT}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_sw_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
