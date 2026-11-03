"""門檻擾動測試（2026-11-03 使用者同意，測試方法補強第 2 項）：正式版的每個引擎門檻隨機 ±一格，看結果會不會垮。
不是找更好的參數，是回答「現在這套是不是剛好配在一組幸運數字上」。技術指標內部門檻（k=0.8、±3%、15% 等）要重算訊號快取，本檔不動。

兩種擾動：
  一次一項（tornado）：每個門檻各往上、往下一格，其餘照正式版 → 哪一項最敏感
  全部同時（joint）：每個門檻在 ±一格內均勻亂抽，抽 N 組（預設 50）→ 整體分布 vs 正式版
指標：5 個起始日（2017-01-03 … 2019-01-02，不追加）跑到回測截止日的 IRR 中位數與最小值，加 500 萬 2016-12-28 起的期末萬。
用法：python perturb_study.py [N]　輸出：results/perturb_tornado.csv、perturb_joint.csv、perturb_summary.md"""
import sys
from copy import deepcopy

import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 50
SEED = 20261103

# 名稱 → (正式值, 一格, 套用函數)。套用函數改 cfg 或 ps 模組常數。
def _mkt_floor(cfg, v): cfg["min_yield"] = v; cfg["mkt"] = ("all", 0.0, None, v)
def _growth_k(cfg, v): cfg["growth_rel"] = (v, cfg["growth_rel"][1], cfg["growth_rel"][2])
def _growth_med(cfg, v): cfg["growth_rel"] = (cfg["growth_rel"][0], v, cfg["growth_rel"][2])
def _conf_frac(cfg, v): cfg["conf_first"] = (cfg["conf_first"][0], v)
def _topup_health(cfg, v): cfg["topup"] = {**cfg["topup"], "health_min": v}
def _scheme(cfg, adds=None, steps=None):
    """apply() 會用 ADD_SCHEMES[cfg["adds"]] 覆寫 ps.ADDS／ADD_STEPS，所以擾動要登記成新方案名再指給 cfg。"""
    a, st = po.ADD_SCHEMES[cfg["adds"]]
    a = adds or a; st = steps or st
    name = f"擾動 {a} {st}"
    po.ADD_SCHEMES[name] = (a, st); cfg["adds"] = name
def _adds0(cfg, v): _scheme(cfg, adds=(v, po.ADD_SCHEMES[cfg["adds"]][0][1]))
def _adds1(cfg, v): _scheme(cfg, adds=(po.ADD_SCHEMES[cfg["adds"]][0][0], v))
def _step0(cfg, v): _scheme(cfg, steps=(v, po.ADD_SCHEMES[cfg["adds"]][1][1]))
def _step1(cfg, v): _scheme(cfg, steps=(po.ADD_SCHEMES[cfg["adds"]][1][0], v))
def _stale_loss(cfg, v): cfg["stale_loss"] = v
def _stale_days(cfg, v): cfg["stale_days"] = int(v)
def _set(key): return lambda cfg, v: cfg.__setitem__(key, v)

PARAMS = {
    "買進門檻下限 5%": (5.0, 0.5, _mkt_floor),
    "續抱殖利率 4.75%": (4.75, 0.5, _set("hold_yield")),
    "停利 12%": (0.12, 0.03, _set("target")),
    "成長股倍數 1.25": (1.25, 0.15, _growth_k),
    "成長股定義中位 <4%": (4.0, 0.5, _growth_med),
    "信心≥3 首買 80%": (0.8, 0.1, _conf_frac),
    "首買 50%": (0.5, 0.1, _set("first")),
    "定期加碼 20%": (0.2, 0.05, _set("time_add_amount")),
    "跌深加碼① 30%": (0.30, 0.05, _adds0),
    "跌深加碼② 20%": (0.20, 0.05, _adds1),
    "跌深觸發① −15%": (-0.15, 0.03, _step0),
    "跌深觸發② −30%": (-0.30, 0.05, _step1),
    "套牢定義 −30%": (-0.30, 0.05, _stale_loss),
    "久抱定義 365 天": (365, 60, _stale_days),
    "補足健康度 0.8": (0.8, 0.1, _topup_health),
}


def md(df):
    """簡單 markdown 表（不依賴 tabulate）。"""
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(f"{v:,}" if isinstance(v, (int, np.integer)) else (f"{v:g}" if isinstance(v, (float, np.floating)) else str(v)) for v in r) + " |")
    return "\n".join(out)


def reset_consts():
    """門檻都走 cfg → apply()，每次 deepcopy(rr.BASE) 就是重設；保留函數名給呼叫處。"""


def score(cfg, label):
    G = rs.G; dates = G["dates"]
    po.CONFIGS[label] = cfg; po.apply(cfg); kw = po.to_kw(cfg)
    irrs = []
    for st in rs.STARTS:
        s = dates.get_indexer([pd.Timestamp(st)], method="bfill")[0]
        _, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw)
        irrs.append(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]))
    tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=1, **kw)
    return dict(IRR中位=round(float(np.median(irrs)), 2), IRR最小=round(float(min(irrs)), 2), IRR最大=round(float(max(irrs)), 2),
                期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), 回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr))


def main():
    po.setup()
    base = score(deepcopy(rr.BASE), "正式版")
    print("正式版：", base, flush=True)
    # 一次一項
    rows = []
    for name, (v0, step, fn) in PARAMS.items():
        for sgn, tag in ((-1, "−一格"), (1, "＋一格")):
            reset_consts(); cfg = deepcopy(rr.BASE); v = v0 + sgn * step
            fn(cfg, v)
            m = score(cfg, f"{name}{tag}")
            rows.append(dict(門檻=name, 方向=tag, 值=round(v, 3), **m, ΔIRR中位=round(m["IRR中位"] - base["IRR中位"], 2), Δ期末萬=m["期末萬"] - base["期末萬"]))
            print(f"  {name}{tag}={v:g}：IRR中位 {m['IRR中位']:.2f}（{m['IRR中位'] - base['IRR中位']:+.2f}）期末 {m['期末萬']}", flush=True)
    reset_consts()
    tor = pd.DataFrame(rows)
    tor.to_csv(RESULTS / "perturb_tornado.csv", index=False, encoding="utf-8-sig")
    # 全部同時
    rng = np.random.default_rng(SEED)
    jrows = []
    for i in range(N):
        reset_consts(); cfg = deepcopy(rr.BASE); draw = {}
        for name, (v0, step, fn) in PARAMS.items():
            v = v0 + rng.uniform(-step, step)
            fn(cfg, v); draw[name] = round(v, 3)
        m = score(cfg, f"joint{i}")
        jrows.append({"抽樣": i, **m, **draw})
        print(f"  joint {i + 1}/{N}：IRR中位 {m['IRR中位']:.2f} 期末 {m['期末萬']}", flush=True)
    reset_consts()
    jo = pd.DataFrame(jrows)
    jo.to_csv(RESULTS / "perturb_joint.csv", index=False, encoding="utf-8-sig")
    for f in RESULTS.glob("param_opt_joint*"):
        f.unlink()

    q = jo["IRR中位"].quantile([.1, .5, .9]); qe = jo["期末萬"].quantile([.1, .5, .9]); qm = jo["IRR最小"].quantile([.1, .5, .9])
    worst = tor.sort_values("ΔIRR中位").head(5)
    lines = ["# 門檻擾動測試（perturb_study.py）", "",
             f"基準＝正式版（六種買點）：IRR 中位 {base['IRR中位']:.2f}%、IRR 最小 {base['IRR最小']:.2f}%、500 萬 12-28 期末 {base['期末萬']:,} 萬、回撤 {base['回撤']}%、{base['筆數']} 筆", "",
             f"## 全部同時亂抽 {N} 組（每個門檻 ±一格內均勻）", "",
             "| 指標 | 10% | 中位 | 90% | 正式版 |", "|---|---|---|---|---|",
             f"| 5 起始日 IRR 中位 | {q[.1]:.2f} | {q[.5]:.2f} | {q[.9]:.2f} | {base['IRR中位']:.2f} |",
             f"| 5 起始日 IRR 最小 | {qm[.1]:.2f} | {qm[.5]:.2f} | {qm[.9]:.2f} | {base['IRR最小']:.2f} |",
             f"| 500 萬 期末萬 | {qe[.1]:,.0f} | {qe[.5]:,.0f} | {qe[.9]:,.0f} | {base['期末萬']:,} |", "",
             f"正式版 IRR 中位在 {N} 組亂抽裡的百分位：{(jo['IRR中位'] < base['IRR中位']).mean():.0%}（50% 附近＝正式版只是平台上的一點；接近 100%＝正式版是孤峰、配適嫌疑）", "",
             "## 一次一項：影響最大的五個", "", md(worst[["門檻", "方向", "值", "IRR中位", "ΔIRR中位", "期末萬", "Δ期末萬"]]), "",
             "## 一次一項全表", "", md(tor[["門檻", "方向", "值", "IRR中位", "IRR最小", "ΔIRR中位", "期末萬", "Δ期末萬", "回撤", "筆數"]])]
    (RESULTS / "perturb_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()
