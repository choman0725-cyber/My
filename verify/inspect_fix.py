"""--local --dry-run 之後檢查單檔：新 adj 事件、share events。用法：python verify/inspect_fix.py 2412 ..."""
import sys, os
sys.path.insert(0, os.getcwd())
import pandas as pd
import update_universe_finmind as u
U = u.UNI
res_hist = pd.read_csv(U / "dividend_result_all.csv", dtype={"stock_id": str})
div_hist = pd.read_csv(U / "dividend_all.csv", dtype={"stock_id": str})
manual = pd.read_csv(u.MANUAL, dtype={"stock_id": str})
md = pd.read_csv(u.ROOT / "data" / "TAIEX.csv", usecols=["date"], parse_dates=["date"])["date"]
fm = u.FinMind()
sp = fm.get("TaiwanStockSplitPrice", "", u.SPLIT_START, "2026-10-31", cached_only=True)
for sid in sys.argv[1:]:
    old = pd.read_csv(U / f"prices/{sid}.csv"); new = old.drop(columns="adj_close").assign(date=pd.to_datetime(old["date"]))
    res = res_hist[res_hist.stock_id == sid]; div = div_hist[div_hist.stock_id == sid] if sid not in u.ETFS else None
    red = fm.get("TaiwanStockCapitalReductionReferencePrice", sid, "2006-01-01", "2026-10-31", cached_only=True)
    lvl = u.share_levels(fm.get("TaiwanStockShareholding", sid, "2006-01-01", "2026-10-31", cached_only=True))
    split = sp[sp.stock_id == sid] if not sp.empty else sp
    pol = u.policy_events(div, res, new)
    known = [d for d, _ in u._events(red, "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice") + u._events(split, "before_price", "after_price")]
    unl = u.unlisted_reductions(lvl, new, known + [d for d, *_ in pol], manual, sid, md)
    log = []
    se = u.share_events(sid, div, res, red, split, [(d, kind, r) for d, k, kind, r in pol if r is not None] + [(d, f"減資（已發行股數；{n}）", r) for d, k, r, n in unl], lvl, log)
    ev = u.adjust_events(res, red, split, [(d, k) for d, k, *_ in pol] + [(d, k) for d, k, *_ in unl])
    built = u.build_prices(new, ev)
    print(f"== {sid} 已發行股數 {len(lvl)} 天；政策補事件 {[(f'{d:%Y-%m-%d}', round(k, 4), kind) for d, k, kind, _ in pol]}")
    for d, k, r, n in unl: print(f"   減資 {d:%Y-%m-%d} 價格係數 {k:.4f} 股數比例 {r:.4f} {n}")
    old_se = pd.read_csv(U / "share_events_all.csv", dtype={"stock_id": str}); old_se = old_se[old_se.stock_id == sid]
    print("   舊 share_events:", old_se[["date", "kind", "share_ratio"]].values.tolist())
    print("   新 share_events:", [(d, k, r) for _, d, k, r in se])
    for w in log: print("   ", w)
    j = old.merge(built, on="date", suffixes=("_old", "_new")); rr = j.adj_close_new / j.adj_close_old
    print(f"   adj 新/舊 首日 {rr.iloc[0]:.4f}，變動處：", j.loc[(rr.round(4) != rr.round(4).shift()), "date"].tolist()[:12])
