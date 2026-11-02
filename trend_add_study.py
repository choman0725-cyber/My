"""多頭排列加碼（2026-11-02 使用者）：手上賺錢的部位，在股票進入「多頭排列」時加碼。
多頭排列用 indicators.ma_align_forecast：今天月線 > 季線，且假設未來每天收盤變動 r、1 天後與 2 天後重算的
MA5′ > MA20′ > MA60′ 都成立（r=−3%＝禁得起兩天回檔的預算版；r=0＝純預測：跳漲後日線落後但必追上、橫盤後自然形成）；
只取首次成立那天。加碼：進場額度 20%、部位總成本 ≤ 額度 ×1.5、每檔最多 2 次、殖利率 ≥ 4.75%（還沒逼近賣點）、
補完後現金 ≥ 一筆首買。對照：確認版（今天已 MA5 > MA20 > MA60 首次成立，不預測）。
判準（2026-11-02 晚放寬）：σ 上升 ≤0.15 且前 7 年配對 ≥14/20 好。
用法：python trend_add_study.py　輸出：results/trend_add_eval.csv、trend_add_money.csv、trend_add_counts.csv
     python trend_add_study.py h1：（2026-11-02 使用者）預算只算 1 天，r 掃 −3%／−4%／−5%　輸出：results/trend_add_h1_*.csv"""
import sys

import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from indicators import ma_align_forecast
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

SIGNALS = {
    "trend_r3": lambda df: ma_align_forecast(df, r=-0.03, horizons=(1, 2)),
    "trend_r1": lambda df: ma_align_forecast(df, r=-0.01, horizons=(1, 2)),
    "trend_r0": lambda df: ma_align_forecast(df, r=0.0, horizons=(1, 2)),
    "trend_now": lambda df: ma_align_forecast(df, horizons=(0,)),
}
ADD = {"amount": 0.2, "cap": 1.5, "max": 2, "min_yield": 4.75}
VARIANTS = {"正式版": rr.BASE,
            "多頭加碼 預算−3%×2天": {**rr.BASE, "trend_add": {**ADD, "key": "trend_r3"}},
            "多頭加碼 預算−1%×2天": {**rr.BASE, "trend_add": {**ADD, "key": "trend_r1"}},
            "多頭加碼 預測持平×2天": {**rr.BASE, "trend_add": {**ADD, "key": "trend_r0"}},
            "多頭加碼 確認版（今天已排列）": {**rr.BASE, "trend_add": {**ADD, "key": "trend_now"}}}
OUT = "trend_add"
if "h1" in sys.argv:
    SIGNALS = {f"trend_h1_r{k}": (lambda k_: (lambda df: ma_align_forecast(df, r=-k_ / 100, horizons=(1,))))(k) for k in (3, 4, 5)}
    VARIANTS = {"正式版": rr.BASE, **{f"多頭加碼 預算−{k}%×1天": {**rr.BASE, "trend_add": {**ADD, "key": f"trend_h1_r{k}"}} for k in (3, 4, 5)}}
    OUT = "trend_add_h1"


def attach_signals(G):
    dates = G["dates"]
    rows = []
    for sid, d in G["sub"].items():
        df, _ = ps.load_prices(sid)
        row = {"代號": sid}
        for k, f in SIGNALS.items():
            d[k] = f(df).reindex(dates).fillna(False).astype(bool).values
            row[k] = int(d[k].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    counts = attach_signals(G)
    counts.to_csv(RESULTS / f"{OUT}_counts.csv", index=False, encoding="utf-8-sig")
    print("全池訊號天數（首次成立日，2017 起到回測截止日）：", counts.drop(columns="代號").sum().to_dict(), flush=True)
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(VARIANTS.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"{OUT}_{i}").loc[name]
        if i:
            for k_, v in paired_from_files(f"{OUT}_0", f"{OUT}_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            led = []
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, ledger=led, **kw)
            ld = pd.DataFrame(led)
            n_ta = int(ld["說明"].astype(str).str.contains("多頭排列加碼").sum()) if len(ld) and "說明" in ld else None
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 多頭加碼次=n_ta)
            tr.to_csv(RESULTS / f"{OUT}_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
            if len(ld):
                ld.to_csv(RESULTS / f"{OUT}_ledger_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / f"{OUT}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"{OUT}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob(f"param_opt_{OUT}_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
