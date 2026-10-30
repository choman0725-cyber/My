"""只買電子股的組合回測：初始資金 500 萬，顯示期末資產、各檔交易與目前持股。

電子股依證交所「電子工業」分類（半導體、電腦及週邊、光電、通信網路、電子零組件、電子通路、
資訊服務、其他電子），從 0050 / 0056 歷年成分股中挑出（ELECTRONICS 清單）。
其餘規則同 portfolio_study.py（A 版單檔邏輯、最多 5 檔、被踢出後不新進場）。
用法：python portfolio_electronics.py
"""
import pickle

import numpy as np
import pandas as pd

import portfolio_study as ps
from backtest import RESULTS, ROOT

CAPITAL = 5_000_000
ELECTRONICS = {
    # 半導體
    "2303", "2311", "2325", "2330", "2337", "2344", "2379", "2408", "2441", "2449", "2454", "2458", "3034",
    "3443", "3474", "3532", "3661", "3711", "4919", "5264", "6239", "6271", "6415", "6770", "7769", "8150",
    # 電腦及週邊、光電
    "2301", "2324", "2352", "2353", "2357", "2362", "2376", "2377", "2382", "2395", "3005", "3231", "3706",
    "4938", "6669", "2356", "2409", "3008", "3481", "6116", "6176", "2451",
    # 通信網路、電子零組件、電子通路、其他電子
    "2345", "2412", "3045", "4904", "6285", "2439", "2308", "2327", "2368", "2383", "2385", "2392", "2474",
    "2492", "3017", "3023", "3037", "3044", "3189", "3653", "3665", "4958", "8046", "2347", "3036", "3702",
    "2317", "2354", "2360", "2404", "2059",
}
VARIANTS = {
    "原版（最多5檔、首買總資產10%）": {},
    "解讀二·冷卻7日（實際投入≈80%）": {"one_per_day": True, "cooldown": 7, "target_util": 0.8,
                                     "util_mode": "invested", "first": 0.8},
}


def main():
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()
    cache = RESULTS / "portfolio_prepared.pkl"
    data, _ = pickle.loads(cache.read_bytes()) if cache.exists() else ps.prepare(sorted(cons["stock_id"].unique()), dates)

    raw_last = {sid: pd.read_csv(ps.UNI / "prices" / f"{sid}.csv")["close"].iloc[-1] for sid in ELECTRONICS
                if (ps.UNI / "prices" / f"{sid}.csv").exists()}
    rows, details = {}, {}
    for uname, etfs in {"0050＋0056": ("0050", "0056"), "只看0050": ("0050",), "只看0056": ("0056",)}.items():
        member = ps.membership(cons[cons["etf"].isin(etfs) & cons["stock_id"].isin(ELECTRONICS)], dates)
        sub = {k: v for k, v in data.items() if k in member}
        for vname, kw in VARIANTS.items():
            tr, eq = ps.run(sub, member, dates, **kw)
            tr["名稱"] = tr["代號"].map(names)
            for col in ("投入", "回收", "市值"):
                tr[col] = tr[col] * CAPITAL
            closed = tr[tr["出場"].notna()]
            key = f"{uname}｜{vname}"
            rows[key] = {"電子股池": len(sub), "期末資產(萬)": eq.iloc[-1] * CAPITAL / 1e4,
                         **{k: v for k, v in ps.stats(eq).items()}, "筆數": len(tr), "已結案": len(closed),
                         "勝率%": 100 * (closed["報酬%"] > 0).mean(), "持有中": int(tr["出場"].isna().sum()),
                         "資金使用率%": eq.attrs["資金使用率%"]}
            details[key] = tr
            tr.to_csv(RESULTS / f"portfolio_electronics_{uname}_{vname.split('（')[0].replace('·', '_')}.csv",
                      index=False, encoding="utf-8-sig")
    for etf in ("0050", "0056"):
        px = ps.load_prices(etf)[0]["close"].reindex(eq.index).ffill().dropna()
        rows[f"{etf} 買進持有"] = {"期末資產(萬)": px.iloc[-1] / px.iloc[0] * CAPITAL / 1e4, **ps.stats(px)}
    table = pd.DataFrame(rows).T
    table.to_csv(RESULTS / "portfolio_electronics_summary.csv", encoding="utf-8-sig")

    with pd.option_context("display.width", 250, "display.max_rows", 300, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        for key, tr in details.items():
            hold = tr[tr["出場"].isna()].copy()
            hold["約股數"] = [int(m / raw_last[s]) for m, s in zip(hold["市值"], hold["代號"])]
            print(f"【{key}】目前持股")
            print(hold[["代號", "名稱", "進場", "加碼", "約股數", "投入", "市值", "報酬%", "最深套牢%", "持有日"]]
                  .round(1).to_string(index=False))
            g = tr.groupby(["代號", "名稱"]).agg(次數=("報酬%", "size"), 平均報酬=("報酬%", "mean"),
                                                 損益=("回收", "sum"), 投入=("投入", "sum"))
            print("  交易過的股票：", "、".join(f"{n}({c})" for (_, n), c in g["次數"].items()), "\n")


if __name__ == "__main__":
    main()
