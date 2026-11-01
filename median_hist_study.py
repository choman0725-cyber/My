"""自己中位數用真正的歷史（2026-11-01）：2017 起的快取殖利率從 2016-12-27 才開始，回測裡的「自己 3 年中位」
2017 年算不出來（全部當一般股）、2018～2019 只用 1～3 年資料；每日程式不受影響（今天已有完整 3 年）。
這裡改用 results/portfolio_prepared_2006.pkl 的 2006 起殖利率算中位數（成長股判定、成長股門檻、信心 F1 都用它），
其他一律照正式版。版本（配對都相對「正式版（現行快取）」；另附 5 年 vs 真 3 年的配對）：
  正式版（現行快取）／正式版（真 3 年中位）／成長股改真 5 年中位／一般股 ≥真 5 年中位×1.00、×1.25
用法：python median_hist_study.py（2006 快取沒有時先建，約 20 分鐘）　輸出：results/median_hist_eval.csv、median_hist_money.csv
     python median_hist_study.py gen：一般股 3 年 vs 5 年中位 × k（1.00～1.25）　輸出：results/median_gen_eval.csv、median_gen_money.csv"""
import pickle
import sys

import numpy as np
import pandas as pd

import daily_run as dr
import long_history as lh
import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_ext
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

VARIANTS = {"正式版（現行快取）": (False, {}), "正式版（真 3 年中位）": (True, {}),
            "成長股改真 5 年中位": (True, {"growth_rel": (1.25, 4.0, 1250)}),
            "一般股 ≥真5年中位×1.00": (True, {"gen_rel": 1.0, "gen_rel_win": 1250}),
            "一般股 ≥真5年中位×1.25": (True, {"gen_rel": 1.25, "gen_rel_win": 1250})}
# python median_hist_study.py gen：成長股固定 3 年，一般股 ≥ 自己中位×k，中位 3 年 vs 5 年（都用真歷史），配對相對真 3 年正式版
VARIANTS_GEN = {"正式版（真 3 年中位）": (True, {}),
                **{f"一般股 ≥真{y}年中位×{k:.2f}": (True, {"gen_rel": k, "gen_rel_win": w})
                   for y, w in ((3, 750), (5, 1250)) for k in (1.0, 1.05, 1.10, 1.15, 1.25)}}
_orig = rules_ext.own_median


def hist_median(G):
    data06, _ = pickle.loads(lh.PKL.read_bytes())
    cal = pd.read_csv(ps.ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    d06 = pd.DatetimeIndex(cal[cal >= lh.START - pd.Timedelta(days=5)]).sort_values()
    full = {sid: pd.Series(data06[sid]["yield"][:len(d06)], index=d06) for sid in G["sub"] if sid in data06}
    gap = max(float(np.nanmax(np.abs(full[s].reindex(G["dates"]).values - G["sub"][s]["yield"]))) for s in full)
    print(f"2006 與 2017 快取的殖利率在重疊日最大差 {gap:.2e}", flush=True)
    idmap = {id(G["sub"][s]["yield"]): s for s in full}

    def own_median(yield_arr, dates, window=750, min_obs=250):
        sid = idmap.get(id(yield_arr))
        if sid is None:
            return _orig(yield_arr, dates, window, min_obs)
        med = full[sid].rolling(window, min_periods=min(min_obs, window // 2)).median().shift(1).reindex(dates)
        return (pd.Series(yield_arr, index=dates) / med).values, med.values
    return own_median


def main():
    gen = "gen" in sys.argv
    variants, tag, outp = (VARIANTS_GEN, "medgen", "median_gen") if gen else (VARIANTS, "medhist", "median_hist")
    po.setup(); G = rs.G; dates = G["dates"]
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    patched = hist_median(G)
    results, money, tags = {}, {}, {}
    for i, (name, (hist, extra)) in enumerate(variants.items()):
        rules_ext.own_median = patched if hist else _orig
        po._applied["buy"] = None                # 換了中位數來源，設定相同也要重算買點（HANDOFF 11.2）
        cfg = {**dr.FINAL, **extra}
        po.apply(cfg); kw = po.to_kw(cfg)
        tags[name] = f"{tag}_{i}"
        po.CONFIGS[name] = cfg
        m = po.evaluate([name], tags[name]).loc[name]
        if i:
            for k_, val in paired_from_files(f"{tag}_0", tags[name]).items():
                m[k_] = val
        if i >= 2 and not gen:
            for k_, val in paired_from_files("medhist_1", tags[name]).items():
                m["對真3年" + k_] = val
        results[name] = m
        po._applied["buy"] = None
        po.apply(cfg)
        sc = np.concatenate([d["buy"][s17:] for d in G["sub"].values()])
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (tr["報酬%"] > 0).mean(), 0))
        m["買點事件"] = int(sc.sum())
        print(f"  {name} 完成：三段 {m['三段平均']:.2f}", flush=True)
    rules_ext.own_median = _orig
    out = pd.DataFrame(results).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對",
                        "後3年配對最差", "對真3年前7年配對", "對真3年後3年配對", "買點事件"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].round(2).to_csv(RESULTS / f"{outp}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"{outp}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob(f"param_opt_{tag}_*"):
        f.unlink()
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版現行快取；「對真3年」＝相對真 3 年中位版）"); print(out[show].round(2).to_string())
        print("\n500 萬不追加"); print(mon.to_string())


if __name__ == "__main__":
    main()
