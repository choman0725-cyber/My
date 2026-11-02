"""買點時間與持有時間分類（2026-11-02 使用者：「哪些股票買點通常比哪些早、哪些出場後常常可以接到哪些；
沒選進來的也回測；不同產業發動時間可能不同，太類似可能互相卡買賣點」）。
做法：0050／0056／0051／0052 歷年全部成分股（351 檔有資料）每檔單獨跑正式版規則，2007-01-02～最新、500 萬不追加、
只在當天是任一 ETF 成分股時買（沒有名額互卡，看的是每檔自己的買點）。產業：電子股用證交所產業別，非電子用 FinMind 產業別。
分析：
  1. 每檔：筆數、持有天數（短 <120／中 120–500／長 >500 天）、勝率、平均報酬、損益、每筆進出日期
  2. 產業：每年買進筆數（看各產業發動的年份）、持有中位天數
  3. 產業同步度：每天「產業內持有中股票的比例」兩兩相關（越高越會同時想買、互卡名額）
  4. 產業先後：每天新買進筆數（60 日平滑）的交叉相關，找相關最高的時間差 → 誰通常先發動
  5. 接棒：某檔出場後 60 個交易日內，其他股票出現新買進的比例，相對隨便挑一天的基準（倍數 >1 ＝常接得到）
  6. 股票分群：買點同步度（前後 40 個交易日內也有買點的比例）做平均連結分群，同群的股票常常同時被買
用法：python timing_study.py　輸出：results/timing_*.csv、results/timing_report.md"""
import numpy as np
import pandas as pd

import daily_run as dr
import param_opt as po
import portfolio_study as ps
from backtest import RESULTS
from portfolio_electronics import CAPITAL, POOL
from pool_expand_study import load, setup_pool

START, HANDOFF, SMOOTH, MAXLAG = "2007-01-02", 60, 60, 120
SHORT, LONG = 120, 500


def industries():
    a = pd.read_csv(ps.UNI / "industry_twse_all.csv", dtype=str).set_index("stock_id")
    f = pd.read_csv(ps.UNI / "industry_finmind.csv", dtype=str)
    f = f[f["stock_id"].isin(a.index[a["industry"] == "非電子"])].sort_values("date").groupby("stock_id")["industry_category"].last()
    ind = a["industry"].where(a["industry"] != "非電子", f.reindex(a.index))
    ind = ind.replace({"化學生技醫療": "生技醫療業", "創新板股票": "其他", "數位雲端": "其他", "居家生活": "其他", "電器電纜": "電機機械",
                       "玻璃陶瓷": "建材營造", "油電燃氣業": "其他", "資訊服務業": "其他電子業", "電子通路業": "其他電子業"})
    return a["name"], ind.str.replace("設備業", "").str.replace("業", "").str.replace("工", "")


def backtest(dates, data, sig, cons):
    G = setup_pool(pd.concat([cons["0050"], cons["0051"], cons["0052"]]), dates, data, sig)
    full_sub, full_mem, full_sig = dict(G["sub"]), dict(G["member"]), {e: dict(m) for e, m in G["sig"].items()}
    s = dates.get_indexer([pd.Timestamp(START)], method="bfill")[0]
    out = []
    for i, sid in enumerate(sorted(full_sub)):
        G["sub"] = {sid: full_sub[sid]}; G["member"] = {sid: full_mem[sid]}
        G["sig"] = {e: {sid: m[sid]} for e, m in full_sig.items() if sid in m}
        po._applied["buy"] = None; po.apply(dr.FINAL)
        tr, _ = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **po.to_kw(dr.FINAL))
        if len(tr):
            out.append(tr)
        if (i + 1) % 50 == 0:
            print(f"  回測 {i + 1}/{len(full_sub)}", flush=True)
    t = pd.concat(out, ignore_index=True)
    t["進場"] = pd.to_datetime(t["進場"]); t["出場"] = pd.to_datetime(t["出場"])
    t["持有天"] = (t["出場"].fillna(dates[-1]) - t["進場"]).dt.days
    t["損益萬"] = (t["回收"].where(t["出場"].notna(), t["市值"]) - t["投入"]) * CAPITAL / 1e4
    return t, {sid: full_mem[sid].iloc[s:].sum() for sid in full_sub}


def hold_class(d):
    return "短" if d < SHORT else ("長" if d > LONG else "中")


def held_matrix(t, dates):
    idx = dates[dates >= pd.Timestamp(START)]
    H = pd.DataFrame(False, index=idx, columns=sorted(t["代號"].unique()))
    for r in t.itertuples():
        H.loc[r.進場:(r.出場 if pd.notna(r.出場) else idx[-1]), r.代號] = True
    return H


def cluster(ent_day, cols, thr=0.5, win=40):
    """買點同步度：A 的買點裡，B 在前後 win 個交易日內也有買點的比例，與反向取平均（J）。
    平均連結分群：兩群之間平均 J ≥ thr 就合併。持有期多半很長（中位 300 天），用持有重疊會全部黏在一起，所以改看買點。"""
    n = len(cols); J = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = ent_day[cols[i]], ent_day[cols[j]]
            f = lambda x, y: np.mean([np.abs(y - v).min() <= win for v in x])
            J[i, j] = J[j, i] = (f(a, b) + f(b, a)) / 2
    groups = [[i] for i in range(len(cols))]
    while True:
        best, bi, bj = thr, -1, -1
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                v = J[np.ix_(groups[a], groups[b])].mean()
                if v > best:
                    best, bi, bj = v, a, b
        if bi < 0:
            break
        groups[bi] += groups.pop(bj)
    return [[cols[i] for i in g] for g in sorted(groups, key=len, reverse=True)], pd.DataFrame(J, index=cols, columns=cols)


def main():
    cons, dates, data, sig = load()
    names, ind = industries()
    t, mem_days = backtest(dates, data, sig, cons)
    t["名稱"] = t["代號"].map(names); t["產業"] = t["代號"].map(ind); t["持有類"] = t["持有天"].map(hold_class)
    t["47檔"] = t["代號"].isin(POOL)
    t.to_csv(RESULTS / "timing_trades.csv", index=False, encoding="utf-8-sig")

    # 1. 每檔
    g = t.groupby("代號")
    st = pd.DataFrame({"名稱": g["名稱"].first(), "產業": g["產業"].first(), "47檔": g["47檔"].first(), "筆數": g.size(),
                       "持有中位天": g["持有天"].median(), "持有類": g["持有天"].median().map(hold_class),
                       "短/中/長": g["持有類"].apply(lambda x: f"{(x == '短').sum()}/{(x == '中').sum()}/{(x == '長').sum()}"),
                       "勝率%": g["報酬%"].apply(lambda x: round(100 * (x > 0).mean())), "平均報酬%": g["報酬%"].mean().round(1),
                       "損益萬": g["損益萬"].sum().round(), "最深套牢%": g["最深套牢%"].min().round(1),
                       "買進月份": g["進場"].apply(lambda x: "、".join(x.dt.strftime("%Y-%m")))})
    never = sorted(s for s in mem_days if s not in st.index and mem_days[s] > 0)

    # 2. 產業 × 年 買進筆數
    yr = t.assign(年=t["進場"].dt.year).pivot_table(index="產業", columns="年", values="代號", aggfunc="count", fill_value=0)
    ind_sum = t.groupby("產業").agg(檔數=("代號", "nunique"), 筆數=("代號", "size"), 持有中位天=("持有天", "median"),
                                   勝率=("報酬%", lambda x: round(100 * (x > 0).mean())), 平均報酬=("報酬%", "mean"), 損益萬=("損益萬", "sum"))
    ind_sum["成分股檔數"] = pd.Series({k: sum(1 for s in mem_days if ind.get(s) == k and mem_days[s] > 0) for k in ind_sum.index})

    # 3. 產業同步度（持有比例相關）
    H = held_matrix(t, dates)
    share = pd.DataFrame({k: H[[c for c in H.columns if ind.get(c) == k]].mean(axis=1) for k in ind_sum.index})
    big = ind_sum.index[ind_sum["筆數"] >= 15]
    sync = share[big].corr().round(2)

    # 4. 產業先後（新買進強度交叉相關）
    ent = pd.DataFrame(0.0, index=H.index, columns=big)
    for r in t[t["產業"].isin(big)].itertuples():
        ent.loc[r.進場, r.產業] += 1
    ent = ent.rolling(SMOOTH, min_periods=1).mean()
    ent = ent / ent.std()
    lead = pd.DataFrame(index=big, columns=big, dtype=float); lead_c = lead.copy()
    for a in big:
        for b in big:
            if a == b:
                continue
            cs = {L: ent[a].corr(ent[b].shift(-L)) for L in range(-MAXLAG, MAXLAG + 1, 5)}   # L>0：b 比 a 晚 L 天
            L = max(cs, key=lambda k: cs[k]); lead.loc[a, b] = L; lead_c.loc[a, b] = round(cs[L], 2)
    lead_avg = lead.mean(axis=1).sort_values(ascending=False)          # 平均起來其他產業比它晚幾天＝它多早發動

    # 5. 接棒
    pos = {d: i for i, d in enumerate(H.index)}
    ent_day = {s: np.array(sorted(pos[d] for d in x)) for s, x in t.groupby("代號")["進場"]}
    N = len(H.index)
    base = {s: np.isin(np.arange(N), (e[:, None] - np.arange(1, HANDOFF + 1)).ravel()).mean() for s, e in ent_day.items()}
    rows = []
    for r in t[t["出場"].notna()].itertuples():
        x = pos[r.出場]
        for s, e in ent_day.items():
            if s != r.代號 and ((e > x) & (e <= x + HANDOFF)).any():
                rows.append((r.代號, s))
    ho = pd.DataFrame(rows, columns=["出場股", "接棒股"])
    n_exit = t[t["出場"].notna()].groupby("代號").size()
    pair = ho.value_counts().rename("次數").reset_index()
    pair["出場次數"] = pair["出場股"].map(n_exit); pair["接得到%"] = (100 * pair["次數"] / pair["出場次數"]).round()
    pair["基準%"] = (100 * pair["接棒股"].map(base)).round(1); pair["倍數"] = (pair["接得到%"] / pair["基準%"]).round(1)
    pair[["出場名", "接棒名", "出場產業", "接棒產業"]] = np.c_[pair["出場股"].map(names), pair["接棒股"].map(names), pair["出場股"].map(ind), pair["接棒股"].map(ind)]
    pair.to_csv(RESULTS / "timing_handoff_pairs.csv", index=False, encoding="utf-8-sig")
    # 產業層級：X 出場後 60 天內 Y 產業有新買進的比例 ÷ 隨便一天 Y 產業 60 天內有新買進的比例
    ind_ent = {k: np.array(sorted(set(np.concatenate([ent_day[s] for s in ent_day if ind.get(s) == k])))) for k in big}
    ind_base = {k: np.isin(np.arange(N), (e[:, None] - np.arange(1, HANDOFF + 1)).ravel()).mean() for k, e in ind_ent.items()}
    ex = t[t["出場"].notna() & t["產業"].isin(big)]
    ih = pd.DataFrame(index=big, columns=big, dtype=float)
    for a in big:
        xs = np.array([pos[d] for d in ex.loc[ex["產業"] == a, "出場"]])
        for b in big:
            e = ind_ent[b]
            hit = np.mean([((e > x) & (e <= x + HANDOFF)).any() for x in xs]) if len(xs) else np.nan
            ih.loc[a, b] = round(hit / ind_base[b], 2)

    # 6. 分群
    n_tr = t.groupby("代號").size()
    cols = sorted(c for c in ent_day if n_tr[c] >= 3)
    groups, J = cluster(ent_day, cols)
    # 個股先後：A、B 都有 ≥3 筆，A 的每個買點找 B 前後 120 個交易日內最近的買點，正＝B 比 A 晚
    lr = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            gaps = [int((ent_day[b] - v)[np.abs(ent_day[b] - v).argmin()]) for v in ent_day[a] if np.abs(ent_day[b] - v).min() <= MAXLAG]
            if len(gaps) >= 3:
                g_ = np.array(gaps); same = max((g_ > 5).mean(), (g_ < -5).mean())
                lr.append(dict(A=a, A名=names.get(a), A產業=ind.get(a), B=b, B名=names.get(b), B產業=ind.get(b), 共同波段=len(g_),
                               B晚幾天中位=float(np.median(g_)), 同方向比例=round(same, 2)))
    lr = pd.DataFrame(lr); lr.to_csv(RESULTS / "timing_lead_pairs.csv", index=False, encoding="utf-8-sig")

    st["群"] = pd.Series({c: i + 1 for i, g_ in enumerate(groups) for c in g_})
    st.to_csv(RESULTS / "timing_stocks.csv", encoding="utf-8-sig"); yr.to_csv(RESULTS / "timing_industry_year.csv", encoding="utf-8-sig")
    ind_sum.to_csv(RESULTS / "timing_industry.csv", encoding="utf-8-sig"); sync.to_csv(RESULTS / "timing_sync.csv", encoding="utf-8-sig")
    lead.to_csv(RESULTS / "timing_lead_days.csv", encoding="utf-8-sig"); ih.to_csv(RESULTS / "timing_handoff_industry.csv", encoding="utf-8-sig")
    J.round(3).to_csv(RESULTS / "timing_jaccard.csv", encoding="utf-8-sig")
    pd.DataFrame([dict(群=i + 1, 檔數=len(g_), 股票="、".join(f"{s}{names.get(s, '')}" for s in g_),
                       產業="、".join(f"{k}{v}" for k, v in pd.Series([ind.get(s) for s in g_]).value_counts().items()))
                  for i, g_ in enumerate(groups)]).to_csv(RESULTS / "timing_groups.csv", index=False, encoding="utf-8-sig")
    pd.Series(never).map(lambda s: f"{s} {names.get(s, '')} {ind.get(s, '')}").to_csv(RESULTS / "timing_never.csv", index=False, encoding="utf-8-sig")
    print("完成", len(t), "筆", st.shape[0], "檔有交易", len(never), "檔沒買點")
    with pd.option_context("display.width", 300, "display.max_rows", 200, "display.unicode.east_asian_width", True, "display.max_columns", 40):
        print(ind_sum.round(1).sort_values("損益萬", ascending=False).to_string()); print(yr.to_string()); print(sync.to_string())
        print(lead_avg.to_string()); print(ih.to_string())
        for i, g_ in enumerate(groups[:15]):
            print(i + 1, len(g_), "、".join(f"{names.get(s, '')}" for s in g_))


if __name__ == "__main__":
    main()
