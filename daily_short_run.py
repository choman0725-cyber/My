"""放空規則每日執行程式：殖利率 <1.5% ＋ 大盤空頭排列 ＋ 技術放空點，獲利 5% 回補，最多 5 檔（規則見 SHORT_RULES.md）。

做法：用規則從 2017-01 把歷史重跑到最新資料日，得到目前應有的空單，再依最新收盤判斷明天開盤要做的事。
用法：
  python daily_short_run.py                       # 500 萬
  python daily_short_run.py --capital 3000000
  python daily_short_run.py --asof 2025-03-31     # 假裝今天是這一天
資料更新：data/universe/prices/*.csv、eps_all.csv、dividend_all.csv 更新後，先刪掉 results/short_prepared.pkl 再執行。
"""
import argparse

import numpy as np
import pandas as pd

import short_yield_study as sy
from short_study import MARGIN_CALL, UPTICK_DROP

YIELD_TH, REGIME, TARGET = 1.5, "R4 空頭排列MA5<20<60", 0.05
RULE_TEXT = """放空規則（最多 5 檔、每檔名目＝總資產 ÷ 5、放空與回補都隔天開盤）
  範圍：當天屬於 0050 或 0056 成分股（全部股票）
  放空：預估殖利率 < 1.5%（算不出的不空）且 加權指數空頭排列（MA5<MA20<MA60）
        且技術放空點任一：超買共振＋KD死叉＋年線下／爆量長上影線或爆量長黑／觸布林上軌＋K>70死叉／高檔區＋出貨訊號
        同日多檔依殖利率低到高挑
  回補：收盤較放空價跌 >= 5% 隔天開盤回補；除權息前 5 個交易日強制回補；維持率 130% 斷頭
  不停損、不加碼、不設持有期限、大盤轉多不回補"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=5_000_000)
    ap.add_argument("--asof", default=None)
    a = ap.parse_args()

    data, dates, regimes, tai = sy.prepare()
    if a.asof:
        cut = pd.Timestamp(a.asof)
        dates = dates[dates <= cut]
        for d in data.values():
            keep = d["df"].index <= cut
            for k in ("df", "yield", "sig", "member", "force", "block", "raw_close"):
                d[k] = d[k][keep]
        tai = tai[tai.index <= cut]
    data = {sid: d for sid, d in data.items() if len(d["df"]) > 250}
    last = dates[-1]
    regime = regimes[REGIME].reindex(dates).ffill().fillna(False).astype(bool)
    ma5, ma20, ma60 = (sy.sma(tai, n).reindex(dates).iloc[-1] for n in (5, 20, 60))

    T, eq = sy.run_portfolio(data, dates, regimes, YIELD_TH, REGIME, False, capital=a.capital, target=TARGET)
    value = eq.iloc[-1] * a.capital
    closed = T[T["原因"] != "期末"]
    opened = T[T["原因"] == "期末"]

    print(RULE_TEXT)
    print(f"\n資料最後日期：{last.date()}　投入 {a.capital / 1e4:,.0f} 萬　目前總資產 {value / 1e4:,.0f} 萬"
          f"（累計已實現 {closed['損益元'].sum() / 1e4:+,.0f} 萬，{len(closed)} 筆，勝率 {100 * (closed['報酬率'] > 0).mean():.0f}%）")
    print(f"加權指數 {tai.reindex(dates).iloc[-1]:,.0f}：MA5 {ma5:,.0f}／MA20 {ma20:,.0f}／MA60 {ma60:,.0f} → "
          f"{'空頭排列成立，可以新放空' if regime.iloc[-1] else '非空頭排列，今天不新放空'}")

    print("\n【目前空單】")
    acts = []
    if opened.empty:
        print("（無）")
    for _, r in opened.iterrows():
        d = data[r["代號"]]
        p = d["df"].index.get_loc(last) if last in d["df"].index else len(d["df"]) - 1
        close = d["df"]["close"].iloc[p]
        raw = d["raw_close"].iloc[p]
        gain = 1 - close / r["放空價"]  # 放空獲利（還原價）
        status = []
        if gain >= TARGET:
            status.append("達 5%，明天回補")
            acts.append(f"回補 {r['代號']} {r['名稱']}：全部（獲利 {100 * gain:.1f}%）")
        if close / r["放空價"] - 1 >= MARGIN_CALL:
            status.append("斷頭")
        if d["force"].iloc[p]:
            status.append("除息前最後回補日，明天回補")
            acts.append(f"回補 {r['代號']} {r['名稱']}：全部（除權息前強制回補）")
        held = (last - r["進場"]).days
        print(f"  {r['代號']} {r['名稱']}：{r['進場'].date()} 放空，持有 {held} 天，"
              f"目前獲利 {100 * gain:+.1f}%（回補價位：原始收盤 ≤ 約 {raw * (1 - TARGET) / (1 - gain):.1f}）"
              + (f"　狀態：{'；'.join(status)}" if status else ""))

    print(f"\n【明天（{last.date()} 之後第一個交易日）開盤要做的事】")
    held_ids = set(opened["代號"])
    if regime.iloc[-1]:
        cands = []
        for sid, d in data.items():
            if sid in held_ids or last not in d["df"].index:
                continue
            p = d["df"].index.get_loc(last)
            y = d["yield"].iloc[p]
            if not d["member"].iloc[p] or np.isnan(y) or y >= YIELD_TH or not d["sig"].iloc[p]:
                continue
            if d["block"].iloc[p]:
                continue
            chg = d["df"]["close"].pct_change().iloc[p]
            cands.append((y, sid, d["name"], d["raw_close"].iloc[p], chg))
        slots = 5 - len(held_ids)
        for y, sid, name, raw, chg in sorted(cands)[:max(slots, 0)]:
            note = "（昨日跌幅 >3.5%，開盤低於昨收就放棄）" if chg <= UPTICK_DROP else ""
            acts.append(f"放空 {sid} {name}：名目約 {value / 5 / 1e4:,.1f} 萬（預估殖利率 {y:.2f}%，收盤 {raw:.1f}，回補目標約 {raw * (1 - TARGET):.1f}）{note}")
        if len(cands) > max(slots, 0):
            acts.append(f"（另有 {len(cands) - max(slots, 0)} 檔符合但沒有空位）")
    print("\n".join(acts) if acts else "沒有動作")

    print("\n【觀察名單：成分股中殖利率 < 1.5%、未放空（等空頭排列＋技術放空點）】")
    rows = []
    for sid, d in data.items():
        if sid in held_ids or last not in d["df"].index:
            continue
        p = d["df"].index.get_loc(last)
        y = d["yield"].iloc[p]
        if not d["member"].iloc[p] or np.isnan(y) or y >= YIELD_TH:
            continue
        rows.append(dict(代號=sid, 名稱=d["name"], 收盤=round(d["raw_close"].iloc[p], 1), 預估殖利率=round(y, 2),
                         今日放空訊號="是" if d["sig"].iloc[p] else "", 停券中="是" if d["block"].iloc[p] else ""))
    w = pd.DataFrame(rows).sort_values("預估殖利率") if rows else pd.DataFrame()
    with pd.option_context("display.width", 200, "display.unicode.east_asian_width", True):
        print(w.to_string(index=False) if len(w) else "（無）")


if __name__ == "__main__":
    main()
