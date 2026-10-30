"""只買電子股的組合回測：初始資金 500 萬，顯示期末資產、各檔交易與目前持股。

電子股依證交所「電子工業」分類（半導體、電腦及週邊、光電、通信網路、電子零組件、電子通路、
資訊服務、其他電子），從 0050 / 0056 歷年成分股中挑出（ELECTRONICS 清單）；
電信業者（中華電、台灣大、遠傳）與川湖不列入。
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
    # 通信網路（不含電信業者中華電、台灣大、遠傳）、電子零組件、電子通路、其他電子（不含川湖）
    "2345", "6285", "2439", "2308", "2327", "2368", "2383", "2385", "2392", "2474",
    "2492", "3017", "3023", "3037", "3044", "3189", "3653", "3665", "4958", "8046", "2347", "3036", "3702",
    "2317", "2354", "2360", "2404",
}
RECOMMENDED = {
    "①解讀二": {"one_per_day": True, "cooldown": 7, "target_util": 0.8, "util_mode": "invested", "first": 0.8},
    "②原版＋套牢不佔名額": {"stale_free_slot": True},
}
SPLITS = {"0050區2檔＋0056區3檔": (2, 3), "0050區3檔＋0056區2檔": (3, 2)}
_R5 = {"removal_exit": "tech_profit", "free_slot_removed": True}
EXITS = {
    "·R5＋移出不佔名額": _R5,
    "·H0滿2年強制賣": {**_R5, "max_hold_days": 730},
    "·H1逐步降停利＋滿2年賣": {**_R5, "target_schedule": [(0, 0.20), (365, 0.10), (548, 0.0)], "max_hold_days": 730},
    "·H2滿1年回本賣＋滿2年賣": {**_R5, "target_schedule": [(0, 0.20), (365, 0.0)], "max_hold_days": 730},
    "·H3逐步降停利＋技術賣訊＋滿2年賣": {**_R5, "target_schedule": [(0, 0.20), (365, 0.10), (548, 0.0)],
                                     "late_tech_days": 548, "max_hold_days": 730},
}
VARIANTS = {f"{r}｜{sp}{e}": ({**rk, **ek}, split) for r, rk in RECOMMENDED.items() for sp, split in SPLITS.items()
            for e, ek in EXITS.items()}


def main():
    cons = pd.read_csv(ps.UNI / "constituents.csv", dtype={"stock_id": str, "etf": str})
    names = dict(pd.read_csv(ps.UNI / "prices_manifest.csv", dtype=str)[["stock_id", "name"]].values)
    cal = pd.read_csv(ROOT / "data" / "TAIEX.csv", parse_dates=["date"])["date"]
    dates = pd.DatetimeIndex(cal[cal >= ps.START - pd.Timedelta(days=5)]).sort_values()
    cache = RESULTS / "portfolio_prepared.pkl"
    data, _ = pickle.loads(cache.read_bytes()) if cache.exists() else ps.prepare(sorted(cons["stock_id"].unique()), dates)
    ps.attach_fundamentals(data, dates)

    raw_last = {sid: pd.read_csv(ps.UNI / "prices" / f"{sid}.csv")["close"].iloc[-1] for sid in ELECTRONICS
                if (ps.UNI / "prices" / f"{sid}.csv").exists()}
    rows, details = {}, {}
    zone_members = {etf: {k: v.values for k, v in ps.membership(
        cons[(cons["etf"] == etf) & cons["stock_id"].isin(ELECTRONICS)], dates).items()} for etf in ("0050", "0056")}
    member = ps.membership(cons[cons["stock_id"].isin(ELECTRONICS)], dates)
    sub = {k: v for k, v in data.items() if k in member}
    for vname, (kw, split) in VARIANTS.items():
        extra = {"slot_split": {"0050": (split[0], zone_members["0050"]), "0056": (split[1], zone_members["0056"])}} \
            if split else {}
        tr, eq = ps.run(sub, member, dates, capital=CAPITAL, **kw, **extra)
        tr["名稱"] = tr["代號"].map(names)
        for col in ("投入", "回收", "市值"):
            tr[col] = tr[col] * CAPITAL
        closed = tr[tr["出場"].notna()]
        key = f"0050＋0056｜{vname}"
        rows[key] = {"補虧次數": int(tr["原因"].astype(str).str.startswith("以盈補虧").sum()),
                     "移出出場": int((tr["原因"] == "移出名單出場").sum()), "期末資產(萬)": eq.iloc[-1] * CAPITAL / 1e4, **ps.stats(eq), "筆數": len(tr), "已結案": len(closed),
                     "勝率%": 100 * (closed["報酬%"] > 0).mean(), "持有中": int(tr["出場"].isna().sum()),
                     "持有中虧損(萬)": (tr.loc[tr["出場"].isna(), "市值"] - tr.loc[tr["出場"].isna(), "投入"]).clip(upper=0).sum() / 1e4,
                     "資金使用率%": eq.attrs["資金使用率%"],
                     "持有>1年": int((((tr["出場"].fillna(dates[-1])) - tr["進場"]).dt.days > 365).sum()),
                     "持有>2年": int((((tr["出場"].fillna(dates[-1])) - tr["進場"]).dt.days > 730).sum()),
                     "最長持有(年)": (((tr["出場"].fillna(dates[-1])) - tr["進場"]).dt.days.max()) / 365,
                     "強制出場": int((tr["原因"] == "持有滿期強制出場").sum()),
                     "強制出場虧損(萬)": ((tr["回收"] - tr["投入"])[tr["原因"] == "持有滿期強制出場"]).sum() / 1e4,
                     "平均持有天": (((tr["出場"].fillna(dates[-1])) - tr["進場"]).dt.days).mean()}
        details[key] = tr
        tr.to_csv(RESULTS / f"portfolio_electronics_{vname}.csv", index=False, encoding="utf-8-sig")
    for etf in ("0050", "0056"):
        px = ps.load_prices(etf)[0]["close"].reindex(eq.index).ffill().dropna()
        rows[f"{etf} 買進持有"] = {"期末資產(萬)": px.iloc[-1] / px.iloc[0] * CAPITAL / 1e4, **ps.stats(px)}
    table = pd.DataFrame(rows).T
    table.to_csv(RESULTS / "portfolio_electronics_summary.csv", encoding="utf-8-sig")

    with pd.option_context("display.width", 250, "display.max_rows", 300, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string(), "\n")
        for key, tr in details.items():
            if "·" in key.split("｜")[-1]:
                continue
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
