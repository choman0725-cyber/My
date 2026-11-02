"""壓低 20 情境標準差（2026-11-01 使用者：P0 與 E1 能不能到 2.0 以下、最好 1.8）。
在 U1 上加「補足的煞車」：補一半、每檔只補一次、現金底線兩筆首買、單次上限 5% 總資產、組合；另列 E＋D（無補足）當底。
兩個股票池：P0 現行（分類法 90 檔）、E1 ＋0052 電子。全部用 2006 起全成分股快取，三組標準差分開列。
輸出 results/std_tune_eval.csv"""
import pandas as pd

import rules_research as rr
import param_opt as po
import robust_study as rs
from backtest import RESULTS
from stock_fit import paired_from_files
from pool_expand_study import load, pools_elec, setup_pool

U1 = rr.BASE["topup"]
VARIANTS = {
    "E＋D 無補足": None,
    "U1 正式版": U1,
    "U1·補一半缺口": {**U1, "frac": 0.5},
    "U1·每檔只補一次": {**U1, "max_per_pos": 1},
    "U1·現金底線兩筆首買": {**U1, "cash_floor_mult": 2},
    "U1·單次上限 5% 總資產": {**U1, "max_amt": 0.05},
    "U1·補一半＋每檔一次": {**U1, "frac": 0.5, "max_per_pos": 1},
    "U1·補一半＋底線兩筆": {**U1, "frac": 0.5, "cash_floor_mult": 2},
}


def main():
    cons, dates, data, sig = load()
    P = pools_elec(cons)
    res = {}
    i = 0
    for pool_name, key in (("P0", "E0 0050/0056 電子工業（分類法）"), ("E1", "E1 E0＋0052 電子")):
        setup_pool(P[key], dates, data, sig)
        base_tag = None
        for vname, tu in VARIANTS.items():
            cfg = {k: v for k, v in rr.BASE.items() if k != "topup"}
            if tu is not None:
                cfg["topup"] = tu
            name = f"{pool_name} {vname}"
            po.CONFIGS[name] = cfg
            po._applied.clear(); po.apply(cfg)
            tag = f"st_{i}"; i += 1
            m = po.evaluate([name], tag).loc[name]
            if vname == "U1 正式版":
                base_tag = tag
            elif base_tag:
                for k_, v in paired_from_files(base_tag, tag).items():
                    m[k_] = v
            res[name] = m
            print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "前7年標準差", "延續", "延續標準差", "單獨", "單獨標準差", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / "std_tune_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 100, "display.max_columns", 40, "display.unicode.east_asian_width", True):
        print("\n（配對相對同池的 U1 正式版）"); print(out[show].round(2).to_string())


if __name__ == "__main__":
    main()
