"""修正資料後的參數重新驗證：以目前正式版（daily_run.FINAL）為基準，逐一改一個參數，
跑 20 情境（前 7 年）＋後 3 年延續／單獨，附與正式版的逐情境配對，並加上 0050／0056 買進持有在同樣情境的基準。

用法：
  python reopt_study.py            # 第一階段：逐一掃描，寫 results/reopt_stage1.csv
  python reopt_study.py combo strict    # 第二階段：第一階段通過的改善逐項疊加（貪婪），寫 results/reopt_combo_strict.csv
  python reopt_study.py combo relaxed   # 放寬版：標準差改為絕對上限 2.5，配對要求更嚴（前 7 年好 ≥ 2×差、後 3 年好 ≥ 差）
嚴格標準（和過去一樣）：三段平均上升、最差 10% 不降、標準差不升（+0.2 內）、前 7 年配對好 ≥ 差。
"""
import sys

import numpy as np
import pandas as pd

import daily_run as dr
import oos_study as oos
import param_opt as po
import robust_study as rs
from backtest import RESULTS

BASE = dict(dr.FINAL)
SCAN = {
    "買進下限%": [("mkt", ("all", 0.0, None, f)) for f in (4.0, 4.5, 5.5, 6.0)] + [("mkt", None)],
    "停利": [("target", v) for v in (0.08, 0.10, 0.15, 0.20, 0.30)],
    "續抱殖利率%": [("hold_yield", v) for v in (None, 4.0, 4.5, 5.0, 5.5)],
    "連續N年賺錢": [("profit_years", v) for v in (None, 3, 10)],
    "最多檔數": [("max_slots", v) for v in (3, 4, 6, 7, 8)],
    "首買比例": [("first", v) for v in (0.35, 0.65, 0.80, 1.00)],
    "加碼階梯": [("adds", k) for k in po.ADD_SCHEMES if k != BASE["adds"]],
    "定期加碼間隔": [("time_add_days", v) for v in (None, 91, 365)],
    "套牢不佔名額": [("stale", False)],
    "套牢定義(天)": [("stale_days", v) for v in (180, 730)],
    "套牢定義(虧損)": [("stale_loss", v) for v in (-0.20, -0.40)],
    "EPS轉負出場": [("eps_exit", False)],
    "剔除後伺機出場": [("removal", False)],
    "技術買點": [("entry", k) for k in po.ENTRIES if k != BASE["entry"]],
}


def label(param, key, val):
    v = val if key != "mkt" else ("固定5%" if val is None else f"下限{val[3]}")
    return f"{param}={v}"


def etf_benchmark():
    """0050／0056 買進持有在同樣 20 情境＋後 3 年的 IRR 中位數。"""
    rows = {}
    for etf in ("0050", "0056"):
        rule = f"ETF買進持有 {etf}"
        is_irr = [rs.one((rule, "—", st, c, 0))[1] for st in rs.STARTS for c in rs.CONTRIBS]
        oos_irr = {m: [oos.one((m, rule, "—", st, c, 0))[1] for st in starts for c in oos.CONTRIBS]
                   for m, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS))}
        rows[rule] = {"前7年": np.median(is_irr), "前7年最差10": np.quantile(is_irr, .1), "前7年標準差": np.std(is_irr, ddof=1),
                      "延續": np.median(oos_irr["延續"]), "單獨": np.median(oos_irr["單獨"])}
        rows[rule]["三段平均"] = np.mean([rows[rule]["前7年"], rows[rule]["延續"], rows[rule]["單獨"]])
    return pd.DataFrame(rows).T


MODE = "strict"   # strict：原本的四條；relaxed：標準差改為絕對上限 2.5，但配對要求更嚴（前 7 年好 ≥ 2×差、後 3 年好 ≥ 差）


def passes(row, base):
    g, _, b = (int(x) for x in row["前7年配對"].split("/"))
    g3, _, b3 = (int(x) for x in row["後3年配對"].split("/"))
    if MODE == "strict":
        checks = {"三段平均升": row["三段平均"] > base["三段平均"] + 0.05,
                  "最差10不降": row["最差10最小"] >= base["最差10最小"] - 0.3,
                  "標準差不升": row["標準差平均"] <= base["標準差平均"] + 0.2,
                  "配對好≥差": g >= b}
    else:
        checks = {"三段平均升≥0.3": row["三段平均"] > base["三段平均"] + 0.3,
                  "最差10不降": row["最差10最小"] >= base["最差10最小"] - 0.3,
                  "標準差≤2.5": row["標準差平均"] <= 2.5,
                  "前7年配對好≥2×差": g >= 2 * b and g > b,
                  "後3年配對好≥差": g3 >= b3}
    return all(checks.values()), "、".join(k for k, v in checks.items() if not v)


SHOW = ["前7年", "前7年最差10", "前7年標準差", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "超過2年比例",
        "前7年配對", "前7年配對中位差", "後3年配對", "後3年配對最差"]


def stage1():
    po.setup()
    po.CONFIGS["正式版"] = BASE
    names, meta = ["正式版"], {"正式版": ("—", None, None)}
    for param, items in SCAN.items():
        for key, val in items:
            n = label(param, key, val)
            po.CONFIGS[n] = {**BASE, key: val}
            if key == "mkt" and val is None:
                po.CONFIGS[n]["min_yield"] = 5.0
            names.append(n); meta[n] = (param, key, val)
    print(f"第一階段：{len(names)} 個設定 × 52 次回測", flush=True)
    m = po.evaluate(names, "reopt_stage1")
    base = m.loc["正式版"]
    m["參數"] = [meta[n][0] for n in m.index]
    m["通過"], m["未過項目"] = zip(*[passes(m.loc[n], base) if n != "正式版" else (False, "基準") for n in m.index])
    etf = etf_benchmark()
    out = pd.concat([m, etf])
    out.round(3).to_csv(RESULTS / "reopt_stage1.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 340, "display.max_rows", 200, "display.unicode.east_asian_width", True):
        print(out[["參數"] + SHOW + ["通過", "未過項目"]].round(2).to_string())
    print("\n通過的改善：", list(m[m["通過"]].sort_values("三段平均", ascending=False).index))


def combo():
    s1 = pd.read_csv(RESULTS / "reopt_stage1.csv", index_col=0)
    s1 = s1[s1["參數"].notna() & (s1.index != "正式版")]
    base = s1.loc[s1.index[0]].copy()   # 佔位，下面用正式版列
    full = pd.read_csv(RESULTS / "reopt_stage1.csv", index_col=0)
    base = full.loc["正式版"]
    s1["通過"] = [passes(s1.loc[n], base)[0] for n in s1.index]
    ok = s1[s1["通過"] == True].sort_values("三段平均", ascending=False)
    print(f"模式 {MODE}：第一階段通過 {len(ok)} 項：{list(ok.index)}", flush=True)
    po.setup()
    cur, cur_name = dict(BASE), "正式版"
    po.CONFIGS[cur_name] = cur
    history = []
    for n in ok.index:
        param = s1.loc[n, "參數"]
        key, val = next((k, v) for p, items in SCAN.items() for k, v in items if label(p, k, v) == n)
        if key in {h[1] for h in history}:
            continue      # 同一參數只疊一次
        cand = {**cur, key: val}
        if key == "mkt" and val is None:
            cand["min_yield"] = 5.0
        cand_name = f"{cur_name}＋{n}"
        po.CONFIGS[cand_name] = cand
        m = po.evaluate([cur_name, cand_name], f"reopt_combo_{len(history)}")
        ok_, why = passes(m.loc[cand_name], m.loc[cur_name])
        history.append((n, key, val, ok_, why, m.loc[cand_name]["三段平均"], m.loc[cand_name]["最差10最小"], m.loc[cand_name]["標準差平均"], m.loc[cand_name]["前7年配對"]))
        print(f"{'採用' if ok_ else '不採用'}：{cand_name}  三段 {m.loc[cand_name]['三段平均']:.2f}  最差10 {m.loc[cand_name]['最差10最小']:.2f}  σ {m.loc[cand_name]['標準差平均']:.2f}  配對 {m.loc[cand_name]['前7年配對']}  {why}", flush=True)
        if ok_:
            cur, cur_name = cand, cand_name
    h = pd.DataFrame(history, columns=["改動", "參數鍵", "值", "採用", "未過項目", "三段平均", "最差10最小", "標準差平均", "前7年配對"])
    h.round(3).to_csv(RESULTS / f"reopt_combo_{MODE}.csv", index=False, encoding="utf-8-sig")
    print("\n最終設定：", {k: v for k, v in cur.items() if BASE.get(k) != v} or "與正式版相同")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "combo":
        MODE = sys.argv[2] if len(sys.argv) > 2 else "strict"
        combo()
    else:
        stage1()
