"""兩個「落底」技術買點（2026-11-02 使用者提案），加進正式版的「技術買點任一」裡測：
  A 跌深落底：個股距 60 日最高收盤已跌 ≥15%，之後連續三根日 K 的低點都沒有跌破「前低」（三根之前的 20 日最低點）×(1−3%)
    → 第三根當天視為落底、是買點（隔天開盤買）。嚴格版另要求三根裡至少一根低點回到前低 ×(1+3%) 以內（真的有測過前低）。
  B 下影線站穩：出現長下影線（影線 ≥ K 棒全長一半、全長 ≥ 0.8 ATR，同現有定義）但不必爆量，只要沒有量縮（量 ≥ 20 日均量 ×k），
    且之後兩天收盤都不低於那天收盤 → 第三天視為落底、是買點。k 測 1.0 與 0.8。
殖利率門檻、5 年賺錢、名額、加碼、賣出全部照正式版；只是「技術買點任一」多了一種。
一次只改一項：A、B 各自加；最後一欄 A＋B 一起加只當參考。
用法：python bottom_entry_study.py　輸出：results/bottom_entry_eval.csv、bottom_entry_money.csv、bottom_entry_counts.csv"""
import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from indicators import atr, bottom_hold, shadows, sma
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files


def bottom_a(df, dd=0.15, tol=0.03, lookback=60, low_win=20, strict=False):
    """A 跌深落底（定義搬到 indicators.bottom_hold；嚴格版 2026-11-02 已採用進「任一」，本檔的「正式版」欄位從此已含它）。"""
    return bottom_hold(df, dd, tol, lookback, low_win, strict)


def bottom_b(df, vol_k=1.0, wick_ratio=0.5):
    """B 下影線站穩。t0 長下影線、量 ≥ vol_k × 20 日均量；t0+1、t0+2 收盤 ≥ t0 收盤；訊號日 t0+2。"""
    upper, lower, rng = shadows(df)
    big_bar = rng >= 0.8 * atr(df)
    long_lower = (lower >= wick_ratio * rng) & big_bar
    no_shrink = df["volume"] >= vol_k * sma(df["volume"], 20)
    t0 = long_lower & no_shrink
    c = df["close"]
    stood = (c.shift(1) >= c.shift(2)) & (c >= c.shift(2))          # t0 = 兩天前
    return (t0.shift(2).fillna(False).astype(bool) & stood).fillna(False)


NEW = {
    "落底A": lambda df: bottom_a(df),
    "落底A嚴格": lambda df: bottom_a(df, strict=True),
    "下影線站穩1.0": lambda df: bottom_b(df, 1.0),
    "下影線站穩0.8": lambda df: bottom_b(df, 0.8),
}
COMBOS = {  # 版本名 → 要和「任一」OR 起來的新訊號
    "＋落底A": ["落底A"], "＋落底A嚴格": ["落底A嚴格"],
    "＋下影線站穩(量≥1.0均量)": ["下影線站穩1.0"], "＋下影線站穩(量≥0.8均量)": ["下影線站穩0.8"],
    "＋落底A＋下影線站穩1.0（參考）": ["落底A", "下影線站穩1.0"],
}


def build_signals(G):
    """每檔算新訊號，對齊研究日曆；回傳 {訊號名: {sid: bool 陣列}} 與觸發統計。"""
    dates = G["dates"]
    raw = {k: {} for k in NEW}
    rows = []
    base = G["sig"]["任一"]
    for sid in G["sub"]:
        df, _ = ps.load_prices(sid)
        for k, f in NEW.items():
            raw[k][sid] = f(df).reindex(dates).fillna(False).astype(bool).values
        rows.append({"代號": sid, "任一": int(base[sid].sum()),
                     **{k: int(raw[k][sid].sum()) for k in NEW},
                     **{f"{k}·新增": int((raw[k][sid] & ~base[sid]).sum()) for k in NEW}})
    return raw, pd.DataFrame(rows)


def main():
    po.setup(); G = rs.G; dates = G["dates"]
    raw, counts = build_signals(G)
    counts.to_csv(RESULTS / "bottom_entry_counts.csv", index=False, encoding="utf-8-sig")
    tot = counts.drop(columns="代號").sum()
    print("全池訊號天數（2017 起到回測截止日）：", tot.to_dict(), flush=True)
    for name, parts in COMBOS.items():
        G["sig"][name] = {sid: np.logical_or.reduce([G["sig"]["任一"][sid]] + [raw[p][sid] for p in parts]) for sid in G["sub"]}
        po.ENTRIES[name] = name
    variants = {"正式版": rr.BASE, **{n: {**rr.BASE, "entry": n} for n in COMBOS}}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    res, money = {}, {}
    for i, (name, cfg) in enumerate(variants.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"be_{i}").loc[name]
        if i:
            for k_, v in paired_from_files("be_0", f"be_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr),
                                     勝率=round(100 * (tr["報酬%"].dropna() > 0).mean(), 0) if "報酬%" in tr else None)
            tr.to_csv(RESULTS / f"bottom_entry_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對", "後3年配對最差"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / "bottom_entry_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / "bottom_entry_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_be_*"):
        f.unlink()
    with pd.option_context("display.width", 300, "display.unicode.east_asian_width", True):
        print(out[show].to_string()); print(mon.to_string())


if __name__ == "__main__":
    main()
