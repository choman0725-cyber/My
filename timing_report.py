"""timing_study.py 的結果整理成 results/timing_report.md（先跑 timing_study.py）。"""
import numpy as np
import pandas as pd

from backtest import RESULTS

BIG = ["半導體", "電腦及週邊", "電子零組件", "光電", "其他電子", "通信網路", "金融保險", "航運", "建材營造", "生技醫療", "電機機械"]


def table(df, fmt=None):
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join("" if pd.isna(v) else (fmt(v) if fmt and isinstance(v, float) else str(v)) for v in r.values) + " |")
    return "\n".join(out)


def main():
    st = pd.read_csv(RESULTS / "timing_stocks.csv", dtype={"代號": str}).set_index("代號")
    t = pd.read_csv(RESULTS / "timing_trades.csv", dtype={"代號": str}, parse_dates=["進場", "出場"])
    ind = pd.read_csv(RESULTS / "timing_industry.csv", index_col=0)
    yr = pd.read_csv(RESULTS / "timing_industry_year.csv", index_col=0)
    J = pd.read_csv(RESULTS / "timing_jaccard.csv", index_col=0); J.index = J.index.astype(str); J.columns = J.columns.astype(str)
    lead = pd.read_csv(RESULTS / "timing_lead_days.csv", index_col=0)
    pair = pd.read_csv(RESULTS / "timing_handoff_pairs.csv", dtype={"出場股": str, "接棒股": str})
    never = pd.read_csv(RESULTS / "timing_never.csv").iloc[:, 0]

    c = J.index; si = st.loc[c, "產業"].values
    sync = pd.DataFrame({b: {a: J.values[np.ix_(si == a, si == b)].mean() for a in BIG if (si == a).any()} for b in BIG if (si == b).any()}).round(2)
    good = pair[(pair["次數"] >= 3) & (pair["倍數"] >= 3)].sort_values("倍數", ascending=False)
    succ = good.groupby("出場股").apply(lambda g: "、".join(f"{r.接棒名}({int(r.次數)}/{int(r.出場次數)})" for r in g.head(3).itertuples()))

    md = ["# 買點時間與持有時間分類（timing_study.py）", "",
          "0050／0056／0051／0052 歷年全部成分股每檔單獨跑正式版規則（2007-01-02～最新、500 萬不追加、只在當天是任一 ETF 成分股時買）。"
          "沒有名額互卡，看的是每檔自己會在什麼時候出現買點、抱多久。持有：短 <120 天、中 120–500、長 >500。", ""]

    md += ["## 1. 產業：獲利、持有時間、發動年份", ""]
    top_years = yr.apply(lambda r: "、".join(f"{y}({int(v)})" for y, v in r.sort_values(ascending=False).head(4).items() if v > 0), axis=1)
    d = ind.assign(平均報酬=ind["平均報酬"].round(1), 損益萬=ind["損益萬"].round(), 持有類=ind["持有中位天"].map(lambda x: "短" if x < 120 else ("長" if x > 500 else "中")),
                   買進最多的年份=top_years).sort_values("損益萬", ascending=False)
    md += [table(d.reset_index()[["產業", "成分股檔數", "檔數", "筆數", "持有中位天", "持有類", "勝率", "平均報酬", "損益萬", "買進最多的年份"]]), ""]
    md += ["### 各產業每年買進筆數", "", table(yr.loc[[i for i in BIG if i in yr.index]].reset_index()), ""]

    md += ["## 2. 買點同步度（會不會互卡）", "",
           "A 的買點前後 40 個交易日內 B 也有買點的比例（雙向平均）。對角線＝同產業內兩兩平均。數字越大越常同時出現買點、越會搶名額。", "",
           table(sync.reset_index().rename(columns={"index": "產業"}), lambda v: f"{v:.2f}"), ""]

    md += ["## 3. 產業先後（誰先發動）", "",
           "每天新買進筆數 60 日平滑後做交叉相關，取相關最高的時間差（交易日）。正數＝欄的產業比列的產業晚幾天出現買點。", "",
           table(lead.loc[[i for i in BIG if i in lead.index], [i for i in BIG if i in lead.columns]].reset_index().rename(columns={"產業": "產業"}), lambda v: f"{v:+.0f}"), ""]

    md += ["## 4. 現行 47 檔逐檔", "",
           "常接棒＝這檔賣出後 60 個交易日內、出現新買點的機率比隨便一天高 3 倍以上、且至少 3 次的股票（次數/出場次數）。", ""]
    p47 = st[st["47檔"]].sort_values("損益萬", ascending=False)
    p47 = p47.assign(常接棒=p47.index.map(lambda s: succ.get(s, "")), 代號名稱=p47.index + " " + p47["名稱"])
    md += [table(p47[["代號名稱", "產業", "筆數", "持有中位天", "持有類", "短/中/長", "勝率%", "平均報酬%", "損益萬", "最深套牢%", "買進月份", "常接棒"]], lambda v: f"{v:.0f}"), ""]

    md += ["## 5. 沒選進來的股票（不在 47 檔）損益前 40", ""]
    o = st[~st["47檔"]].sort_values("損益萬", ascending=False).head(40)
    o = o.assign(常接棒=o.index.map(lambda s: succ.get(s, "")), 代號名稱=o.index + " " + o["名稱"])
    md += [table(o[["代號名稱", "產業", "筆數", "持有中位天", "持有類", "勝率%", "平均報酬%", "損益萬", "最深套牢%", "買進月份", "常接棒"]], lambda v: f"{v:.0f}"), ""]
    lose = st[st["損益萬"] < 0].sort_values("損益萬")
    md += [f"虧損的股票（{len(lose)} 檔）：" + "、".join(f"{n}({int(v)})" for n, v in zip(lose["名稱"], lose["損益萬"])), "",
           f"從沒出現買點（{len(never)} 檔，依產業）：" + "、".join(f"{k} {v}" for k, v in never.str.split().str[-1].value_counts().items()), ""]
    (RESULTS / "timing_report.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
