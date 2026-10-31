"""重建後檢查（python -I verify/post_fix_checks.py [比較基準 commit，預設 23be3e9]）。
1. OHLCV 沒有被動到（只有 adj_close 改變）。
2. 每檔 adj_close 新/舊比值的變化點都對得上一個事件（股數變動表或除權息結果）。
3. 還原日報酬超過漲跌幅的天數（修正前 256 天）。
4. 除權息結果每一筆：還原日報酬 ≈ 收盤 ÷ 參考價 − 1（參考價用修正後規則）。
5. share_events 各類筆數、「權息」仍無股數比例的筆數。
"""
import glob, io, os, subprocess, sys
import pandas as pd
sys.path.insert(0, os.getcwd())
import update_universe_finmind as u

BASE = sys.argv[1] if len(sys.argv) > 1 else "23be3e9"
U = "data/universe/"
def old_csv(p):
    out = subprocess.run(["git", "show", f"{BASE}:{p}"], capture_output=True, text=True).stdout
    return pd.read_csv(io.StringIO(out), dtype={"stock_id": str}) if out else None

se = pd.read_csv(U + "share_events_all.csv", dtype={"stock_id": str}); se["d"] = pd.to_datetime(se.date)
res = pd.read_csv(U + "dividend_result_all.csv", dtype={"stock_id": str}); res["d"] = pd.to_datetime(res.date)
ohlcv_bad, unexplained, changed, jumps, refcheck = [], [], 0, [], []
for f in sorted(glob.glob(U + "prices/*.csv")):
    sid = os.path.basename(f)[:-4]
    n = pd.read_csv(f); o = old_csv(f)
    if o is None:
        continue
    j = o.merge(n, on="date", suffixes=("_o", "_n"), how="outer", indicator=True)
    if (j._merge != "both").any() or any((j[c + "_o"] != j[c + "_n"]).any() for c in ("open", "high", "low", "close", "volume")):
        ohlcv_bad.append(sid)
    r = (j.adj_close_n / j.adj_close_o)
    step = (r / r.shift(1) - 1).abs() > 2e-4          # 比值變化點＝新舊事件不同的日子
    pts = pd.to_datetime(j.loc[step, "date"])
    if len(pts):
        changed += 1
    ev = list(se[se.stock_id == sid].d) + list(res[res.stock_id == sid].d)
    for p in pts:
        if not any(abs((p - e).days) <= 5 for e in ev):
            unexplained.append((sid, f"{p:%Y-%m-%d}", round(float(r[j.date == f'{p:%Y-%m-%d}'].iloc[0]), 5)))
    ret = n.adj_close.pct_change()
    lim = pd.Series(0.10, index=n.index); lim[n.date < "2015-06-01"] = 0.07
    for i in n.index[ret.abs() > lim + 0.001]:
        jumps.append((sid, n.date[i], round(float(ret[i]), 4)))
    # 4. 除權息日還原報酬 vs 收盤 ÷ 參考價
    for d, k, rights in u.result_events(res[res.stock_id == sid]):
        idx = n.index[n.date == f"{d:%Y-%m-%d}"]
        if not len(idx) or idx[0] == 0:
            continue
        i = idx[0]
        want = n.close[i] / (n.close[i - 1] * k) - 1
        got = n.adj_close[i] / n.adj_close[i - 1] - 1
        if abs(want - got) > 0.002:
            refcheck.append((sid, f"{d:%Y-%m-%d}", round(want, 4), round(got, 4)))

print(f"1. OHLCV 有變動的檔案：{ohlcv_bad or '無'}")
print(f"2. adj_close 有改變的檔案 {changed} 檔；變化點對不上任何事件（±5 天）：{len(unexplained)}", unexplained[:20])
jd = pd.DataFrame(jumps, columns=["stock_id", "date", "ret"])
print(f"3. 還原日報酬超過漲跌幅：{len(jd)} 天、{jd.stock_id.nunique()} 檔（修正前 256 天、28 檔）")
print(jd.groupby("stock_id").date.agg(["count", "min", "max"]).sort_values("count", ascending=False).to_string())
jd.to_csv(U + "_verify_cache/post_fix_jumps.csv", index=False)
print(f"4. 除權息日還原報酬與參考價不符（>0.2%）：{len(refcheck)}", refcheck[:20])
print("5. share_events 各類筆數：", se.kind.value_counts().to_dict())
o = old_csv(U + "share_events_all.csv")
print(f"   share_events：{len(o)} → {len(se)} 筆")
w = open(U + "update_warnings.txt", encoding="utf-8").read().strip().splitlines() if os.path.exists(U + "update_warnings.txt") else []
print(f"6. update_warnings.txt：{len(w)} 筆"); [print("   ", x) for x in w]
