"""第 1、2 名版本的參數全面分析與最佳化。

底 A（第 1 名）：不設上限＋Y1 殖利率≥5% 續抱｜不分區
底 B（第 2 名）：不設上限＋Y3 續抱＋封頂 40%｜0050 區 2＋0056 區 3
（第 1 名的 B3×Rb 延後賣出版本，在這裡當作「延後賣出」參數的一個選項）

階段一（python param_opt.py stage1）：每個參數單獨掃描，其餘維持底的設定。
階段二（python param_opt.py stage2）：把階段一有改善的參數值交叉組合，再驗證。
評分：前 7 年 20 情境（5 起始日 × 4 追加）的 IRR 中位數 ＋ 最差 10% − 標準差（只用樣本內選），
後 3 年（延續、單獨）只做驗證不參與挑選。
"""
import itertools
import pickle
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

import oos_study as oos
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from yield_entry_study import entries

# ---------- 參數空間 ----------
ADD_SCHEMES = {
    "A -15/-30 加30/20": ((0.30, 0.20), (-0.15, -0.30)),
    "B -10/-20 加30/20": ((0.30, 0.20), (-0.10, -0.20)),
    "C -20/-40 加30/20": ((0.30, 0.20), (-0.20, -0.40)),
    "D -10/-20/-30 加25/15/10": ((0.25, 0.15, 0.10), (-0.10, -0.20, -0.30)),
    "E -15/-30 加25/25": ((0.25, 0.25), (-0.15, -0.30)),
    "N 不加碼": ((), ()),
}
ENTRIES = {"任一": "任一", "共振": "共振（目前版本）", "價量引線": "價量引線", "布林KD": "布林KD", "混合": "混合（布林KD位置＋價量引線時機）"}
SPLITS = {"不分區": None, "0050區2＋0056區3": (2, 3), "0050區3＋0056區2": (3, 2)}
DEFERS = {"不延後": {}, "B3×Rb": {"defer_breakout": "breakout_B3", "defer_reversal": "reversal_Rb"},
          "B1×Ra": {"defer_breakout": "breakout_B1", "defer_reversal": "reversal_Ra"}}

BASE_A = dict(min_yield=5.0, entry="任一", target=0.20, hold_yield=5.0, cap=None, floor=None, first=0.50,
              adds="A -15/-30 加30/20", time_add_days=182, time_add_amount=0.20, max_slots=5, split="不分區",
              stale=True, stale_days=365, stale_loss=-0.30, eps_exit=True, removal=True, defer="不延後")
BASE_B = {**BASE_A, "cap": 0.40, "split": "0050區2＋0056區3"}
BASES = {"底A 第1名Y1不分區": BASE_A, "底B 第2名Y3封頂2+3": BASE_B}

GRID = {
    "min_yield": [4.0, 4.5, 5.0, 5.5, 6.0],
    "entry": list(ENTRIES),
    "target": [0.10, 0.15, 0.20, 0.25, 0.30],
    "hold_yield": [None, 4.0, 4.5, 5.0, 5.5, 6.0],
    "cap": [None, 0.30, 0.40, 0.50, 0.60],
    "floor": [None, 0.05, 0.10],
    "first": [0.35, 0.50, 0.65, 0.80, 1.00],
    "adds": list(ADD_SCHEMES),
    "time_add_days": [None, 91, 182, 365],
    "time_add_amount": [0.10, 0.20, 0.30, 0.50],
    "max_slots": [3, 4, 5, 6, 7, 8],
    "split": list(SPLITS),
    "stale": [True, False],
    "stale_days": [180, 365, 730],
    "stale_loss": [-0.20, -0.30, -0.40],
    "eps_exit": [True, False],
    "removal": [True, False],
    "defer": list(DEFERS),
}
LABEL = {"min_yield": "買進殖利率門檻%", "entry": "技術買點", "target": "停利門檻", "hold_yield": "續抱殖利率%",
         "cap": "續抱封頂", "floor": "續抱保利回落", "first": "首買比例", "adds": "加碼階梯", "time_add_days": "定期加碼間隔(天)",
         "time_add_amount": "定期加碼額度", "max_slots": "最多檔數", "split": "分區", "stale": "套牢不佔名額",
         "stale_days": "套牢定義(天)", "stale_loss": "套牢定義(虧損)", "eps_exit": "EPS轉負出場", "removal": "剔除後伺機出場", "defer": "突破延後賣出"}

G = rs.G
CONFIGS = {}  # name -> cfg dict


def key(cfg):
    return tuple((k, str(cfg[k])) for k in BASE_A)


def to_kw(cfg):
    kw = {"first": cfg["first"], "time_add_amount": cfg["time_add_amount"]}
    if cfg["stale"]:
        kw["stale_free_slot"] = True
    if cfg["eps_exit"]:
        kw["exit_eps_loss"] = True
    if cfg["time_add_days"] and cfg["adds"] != "N 不加碼":
        kw["time_add_days"] = cfg["time_add_days"]
    if cfg["removal"]:
        kw.update(removal_exit="tech_profit", free_slot_removed=True)
    if cfg["hold_yield"] is not None:
        kw["hold_yield"] = cfg["hold_yield"]
        if cfg["cap"] is not None:
            kw["hold_yield_cap"] = cfg["cap"]
        if cfg["floor"] is not None:
            kw["hold_yield_floor"] = cfg["floor"]
    kw.update(DEFERS[cfg["defer"]])
    return kw


_applied = {}


def apply(cfg):
    """在工作行程內套用模組常數與買點陣列。"""
    ps.MAX_SLOTS, ps.TARGET = cfg["max_slots"], cfg["target"]
    ps.ADDS, ps.ADD_STEPS = ADD_SCHEMES[cfg["adds"]]
    ps.STALE_DAYS, ps.STALE_LOSS = cfg["stale_days"], cfg["stale_loss"]
    k = (cfg["min_yield"], cfg["entry"])
    if _applied.get("buy") != k:
        sig = G["sig"][ENTRIES[cfg["entry"]]]
        for sid, d in G["sub"].items():
            y = d["yield"]
            d["buy"] = sig[sid] & (np.nan_to_num(y, nan=-1) >= cfg["min_yield"])
        _applied["buy"] = k


def one_is(t):
    apply(CONFIGS[t[0]]); return rs.one(t)


def one_oos(t):
    apply(CONFIGS[t[1]]); return oos.one(t)


def setup():
    rs.setup()
    rs.SPLITS.clear(); rs.SPLITS.update(SPLITS)
    cache = RESULTS / "param_opt_sigs.pkl"
    if cache.exists():
        G["sig"] = pickle.loads(cache.read_bytes())
    else:
        sig = {k: {} for k in ENTRIES.values()}
        for sid in G["sub"]:
            df, _ = ps.load_prices(sid)
            e, _ = entries(df)
            for k in sig:
                sig[k][sid] = e[k].reindex(G["dates"]).fillna(False).astype(bool).values
        G["sig"] = sig
        cache.write_bytes(pickle.dumps(sig))
    # 檢查：預設參數算出的 buy 應與原始 prepared 一致
    for sid, d in G["sub"].items():
        y = d["yield"]
        assert ((G["sig"]["任一"][sid] & (np.nan_to_num(y, nan=-1) >= 5.0)) == d["buy"]).all(), sid


def evaluate(names, tag):
    """跑樣本內 20 情境 ＋ 後 3 年延續/單獨，回傳彙整表。"""
    for n in names:
        rs.RULES[n] = to_kw(CONFIGS[n])
    tasks = [(n, CONFIGS[n]["split"], st, c, 0) for n in names for st in rs.STARTS for c in rs.CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one_is, tasks, chunksize=4)
    df = pd.DataFrame([dict(版本=t[0], IRR=i, 回撤=m, 最長持有=h, 超過2年=p) for t, i, m, h, p in res])
    df.to_csv(RESULTS / f"param_opt_{tag}_is_runs.csv", index=False, encoding="utf-8-sig")
    g = df.groupby("版本").agg(前7年=("IRR", "median"), 前7年最差10=("IRR", lambda x: x.quantile(.1)), 前7年標準差=("IRR", "std"),
                           前7年回撤=("回撤", "median"), 最長持有=("最長持有", "max"), 超過2年比例=("超過2年", "mean"))
    tasks = []
    for mode, starts in (("延續", oos.STARTS_FULL), ("單獨", oos.STARTS_OOS)):
        tasks += [(mode, n, CONFIGS[n]["split"], st, c, 0) for n in names for st in starts for c in oos.CONTRIBS]
    with Pool(4) as pool:
        res = pool.map(one_oos, tasks, chunksize=4)
    do = pd.DataFrame([dict(驗證=t[0], 版本=t[1], IRR=i, 回撤=m) for t, i, m, h in res])
    go = do.groupby(["驗證", "版本"]).agg(中位=("IRR", "median"), 最差10=("IRR", lambda x: x.quantile(.1)), 標準差=("IRR", "std"))
    m = g.copy()
    for mode in ("延續", "單獨"):
        m[mode] = go.loc[mode]["中位"]; m[f"{mode}最差10"] = go.loc[mode]["最差10"]; m[f"{mode}標準差"] = go.loc[mode]["標準差"]
    m["樣本內分數"] = m["前7年"] + m["前7年最差10"] - m["前7年標準差"]
    m["三段平均"] = m[["前7年", "延續", "單獨"]].mean(axis=1)
    m["最差10最小"] = m[["前7年最差10", "延續最差10", "單獨最差10"]].min(axis=1)
    m["標準差平均"] = m[["前7年標準差", "延續標準差", "單獨標準差"]].mean(axis=1)
    return m


SHOW = ["前7年", "前7年最差10", "前7年標準差", "樣本內分數", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "最長持有"]


def stage1():
    rows = []  # (base, param, value, name)
    for bname, base in BASES.items():
        for param, values in GRID.items():
            for v in values:
                cfg = {**base, param: v}
                if param == "split" and cfg["max_slots"] != 5:
                    continue
                name = f"{bname}｜{LABEL[param]}={v}"
                if key(cfg) in {key(CONFIGS[n]) for n in CONFIGS if n.startswith(bname)}:
                    # 與同底的既有設定相同（例如底本身的值），共用結果
                    same = next(n for n in CONFIGS if n.startswith(bname) and key(CONFIGS[n]) == key(cfg))
                    rows.append((bname, param, v, same)); continue
                CONFIGS[name] = cfg
                rows.append((bname, param, v, name))
    names = sorted({r[3] for r in rows})
    print(f"階段一：{len(names)} 個設定 × 52 次回測", flush=True)
    m = evaluate(names, "stage1")
    out = pd.DataFrame([dict(底=b, 參數=LABEL[p], 值=str(v), 是底值=(BASES[b][p] == v), **m.loc[n].to_dict()) for b, p, v, n in rows])
    out.round(2).to_csv(RESULTS / "param_opt_stage1.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 500, "display.unicode.east_asian_width", True):
        for b in BASES:
            print(f"\n===== {b} =====")
            print(out[out["底"] == b][["參數", "值", "是底值"] + SHOW].round(1).to_string(index=False))


def stage2():
    s1 = pd.read_csv(RESULTS / "param_opt_stage1.csv")
    cands = []
    for bname, base in BASES.items():
        sub = s1[s1["底"] == bname]
        base_score = sub[sub["是底值"]]["樣本內分數"].iloc[0]
        # 每個參數挑樣本內分數最高的值；只保留比底值好 >= 0.5 分的參數
        improv, second = {}, {}
        for param in GRID:
            rows = sub[(sub["參數"] == LABEL[param]) & ~sub["是底值"]].sort_values("樣本內分數", ascending=False)
            rows = rows[rows["樣本內分數"] - base_score >= 0.5]
            if rows.empty:
                continue
            best = rows.iloc[0]
            improv[param] = (parse(param, best["值"]), best["樣本內分數"] - base_score)
            if len(rows) > 1:
                second[param] = parse(param, rows.iloc[1]["值"])
        print(f"{bname}：底分數 {base_score:.2f}，有改善的參數：", {LABEL[k]: v for k, v in improv.items()}, flush=True)
        params = sorted(improv, key=lambda k: -improv[k][1])
        # 依改善幅度逐步累加、改善最大的前 4 個參數「底值 / 最佳值」全交叉、
        # 以及前 4 個參數改用次佳值的版本（避免只挑到樣本內最尖的那個值）
        combos = []
        for i in range(1, len(params) + 1):
            combos.append({p: improv[p][0] for p in params[:i]})
        top = params[:4]
        for mask in itertools.product([0, 1], repeat=len(top)):
            combos.append({p: improv[p][0] for p, m_ in zip(top, mask) if m_})
        for p in top:
            if p in second:
                combos.append({**{q: improv[q][0] for q in top}, p: second[p]})
                combos.append({**{q: improv[q][0] for q in top if q != "defer"}, p: second[p]})
        # 不含延後賣出（B3×Rb 在後 3 年沒有優勢）的全套用版本
        combos.append({p: improv[p][0] for p in params if p != "defer"})
        seen = set()
        for c in combos:
            cfg = {**base, **c}
            if cfg["max_slots"] != 5 and cfg["split"] != "不分區":
                cfg["split"] = "不分區"
            k = key(cfg)
            if k in seen:
                continue
            seen.add(k)
            desc = "＋".join(f"{LABEL[p]}={v}" for p, v in c.items()) or "底"
            name = f"{bname}｜{desc}"
            CONFIGS[name] = cfg
            cands.append((bname, desc, name))
    names = [n for _, _, n in cands]
    print(f"階段二：{len(names)} 個組合", flush=True)
    m = evaluate(names, "stage2")
    out = pd.DataFrame([dict(底=b, 組合=d, **m.loc[n].to_dict()) for b, d, n in cands])
    out = out.sort_values(["底", "樣本內分數"], ascending=[True, False])
    out.round(2).to_csv(RESULTS / "param_opt_stage2.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 500, "display.max_colwidth", 120, "display.unicode.east_asian_width", True):
        for b in BASES:
            print(f"\n===== {b} =====")
            print(out[out["底"] == b][["組合"] + SHOW].round(1).to_string(index=False))


def parse(param, s):
    if s in ("None", "nan"):
        return None
    if param in ("stale", "eps_exit", "removal"):
        return s == "True"
    if param in ("entry", "adds", "split", "defer"):
        return s
    v = float(s)
    return int(v) if param in ("max_slots", "time_add_days", "stale_days") else v


if __name__ == "__main__":
    setup()
    {"stage1": stage1, "stage2": stage2}[sys.argv[1] if len(sys.argv) > 1 else "stage1"]()
