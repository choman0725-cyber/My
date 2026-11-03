"""周轉研究（2026-11-03 使用者：「把交易次數多一倍以上（62→≥124 筆），加換股、撿股、補虧邏輯，獲利與 σ 不能差太多」）。
正式版 10 年 62 筆的瓶頸：42% 的交易日有空位（2017、2018 幾乎滿倉；2019 整年有空位），持有中位 285 天，出場 52 筆是停利。
所以多交易只有兩條路：空位時多買點（撿股），或讓部位早點讓位（換股／呆部位出清／補虧）。每版只改一項，基準＝正式版（六種買點）。

A 撿股（新技術買點 OR 進「任一」；殖利率門檻、5 年賺錢、名額都照舊）
  A1 W 底突破頸線（另一 session bottom_study S12：近 20 日曾距一年高點跌 ≥25%，60 日低點在 15～50 日前、回測低點高 3%、收盤突破反彈高）
  A2 帶量突破 20 日高（S8：同跌深區、收盤 > 前 20 日最高、量 ≥ 1.5×20 日均量）
  A3 法人連 3 日買超（外資＋投信合計淨買 >0 連續 3 日；data/extra，2012 起）
  A4 融資 20 日降 ≥10%（融資餘額比 20 日前少一成，籌碼洗清；data/extra）
  A5 跌深任一天（S0：近 20 日曾距一年高點跌 ≥25%，不要技術確認；最寬鬆的對照）
B 讓位
  B1 換股·殖利率跌破續抱就讓：名額滿時，持股（賺 ≥0、非成長股）剩餘肉比新買點預期肉少就隔天換（switch min_gain 0、margin 0）
  B2 呆部位出清 365 天：持有 >1 年、扣成本賺 0～12%、殖利率 < 續抱門檻 → 賣（引擎 stale_exit）
  B3 呆部位出清 180 天
C 補虧（HANDOFF 11.1 已否決過定期結算，使用者 11-03 點名再測一次）
  C1 每半年補虧結算（settle (6,"offset")：賣有賺的，再用當期已實現獲利認列虧損部位）
  C2 每年補虧結算（settle (12,"offset")）
D 衛星名額（核心 5 檔照舊，另開第 6 個名額只給撿股訊號；額度仍是總資產 ÷ 5）
  D1 核心 5＋撿股 1（W 底）　D2 核心 5＋撿股 1（帶量突破）
E 結構性（單路徑初篩後留下的：名額、門檻下限、與 B1 的組合；這些在 HANDOFF 11.1 是定案，使用者 11-03 為了翻倍筆數點名再測）
  E3 門檻下限 4.5%　E10 7 檔＋門檻 4.5%　E11 停利 8%＋B1 換股　E13 A2 帶量突破＋B1 換股
G 衛星名額放寬殖利率（引擎 zone_buy：衛星區自己的買進條件＝W 底｜帶量突破 且 殖利率 ≥3% 且 5 年賺錢；持滿 126 日強制出、停利照舊）
  G1 衛星 2 檔　G2 衛星 3 檔
用法：python turnover_study.py [A|B|C|D|E|G ...]（不給＝全部）　輸出：results/turnover_eval.csv、turnover_money.csv、turnover_summary.md"""
import sys

import numpy as np
import pandas as pd

import param_opt as po
import portfolio_study as ps
import robust_study as rs
import rules_research as rr
from backtest import RESULTS, ROOT
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

EXTRA = ROOT / "data" / "extra"
TARGET_TRADES = 124


# ---------- 訊號 ----------
def zone(df):
    dd250 = df["low"] / df["high"].rolling(250, min_periods=60).max() - 1
    return (dd250.rolling(20).min() <= -0.25).fillna(False)


def s8_breakout(df):
    vratio = df["volume"] / df["volume"].rolling(20).mean().shift(1)
    return (zone(df) & (df["close"] > df["high"].shift(1).rolling(20).max()) & (vratio >= 1.5)).fillna(False)


def s12_wbottom(df):
    c, lo, hi = df["close"], df["low"], df["high"]
    low60_pos = lo.rolling(60).apply(np.argmin, raw=True)
    pos = np.arange(len(df))
    lowpos = pos - 59 + low60_pos.fillna(0).astype(int).values
    age = pos - lowpos
    lov, hiv = lo.values, hi.values
    since_low_min = np.array([lov[max(lp + 5, 0):p - 2].min() if 0 <= lp and p - lp >= 15 and p - 2 > lp + 5 else np.nan for p, lp in zip(pos, lowpos)])
    bounce_high = np.array([hiv[lp + 1:p].max() if 0 <= lp and p - lp >= 15 else np.nan for p, lp in zip(pos, lowpos)])
    bh = pd.Series(bounce_high, index=df.index)
    sig = (zone(df) & (age >= 15) & (age <= 50) & (pd.Series(since_low_min, index=df.index) >= lo.rolling(60).min() * 1.03)
           & (c > bh) & (c.shift(1) <= bh.shift(1)))
    return sig.fillna(False)


def inst_buy3(sid, dates):
    f = EXTRA / "TaiwanStockInstitutionalInvestorsBuySell" / f"{sid}.csv"
    if not f.exists():
        return pd.Series(False, index=dates)
    d = pd.read_csv(f, parse_dates=["date"])
    d = d[d["name"].isin(["Foreign_Investor", "Investment_Trust"])]
    net = (d["buy"] - d["sell"]).groupby(d["date"]).sum().sort_index()
    pos3 = (net > 0).astype(int).rolling(3).sum() == 3
    return pos3.reindex(dates).fillna(False).astype(bool)


def margin_down(sid, dates, k=0.10, win=20):
    f = EXTRA / "TaiwanStockMarginPurchaseShortSale" / f"{sid}.csv"
    if not f.exists():
        return pd.Series(False, index=dates)
    d = pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()
    bal = pd.to_numeric(d["MarginPurchaseTodayBalance"], errors="coerce")
    sig = (bal / bal.shift(win) - 1 <= -k) & (bal.shift(win) > 0)
    return sig.reindex(dates).fillna(False).astype(bool)


PRICE_SIGS = {"W底突破": s12_wbottom, "帶量突破20日高": s8_breakout, "跌深任一天": zone}
EXTRA_SIGS = {"法人連3日買超": inst_buy3, "融資20日降10%": margin_down}


def build_signals(G):
    dates = G["dates"]
    raw = {k: {} for k in list(PRICE_SIGS) + list(EXTRA_SIGS)}
    rows = []
    base = G["sig"]["任一"]
    for sid in G["sub"]:
        df, _ = ps.load_prices(sid)
        for k, f in PRICE_SIGS.items():
            raw[k][sid] = f(df).reindex(dates).fillna(False).astype(bool).values
        for k, f in EXTRA_SIGS.items():
            raw[k][sid] = f(sid, dates).values
        rows.append({"代號": sid, "任一": int(base[sid].sum()), **{k: int(raw[k][sid].sum()) for k in raw},
                     **{f"{k}·新增": int((raw[k][sid] & ~base[sid]).sum()) for k in raw}})
    return raw, pd.DataFrame(rows)


def variants(G, raw):
    """回傳 {版本名: cfg}；需要的 entry／split 先登記進 G["sig"]、po.ENTRIES、rs.SPLITS。"""
    def add_entry(name, parts):
        G["sig"][name] = {sid: np.logical_or.reduce([G["sig"]["任一"][sid]] + [raw[p][sid] for p in parts]) for sid in G["sub"]}
        po.ENTRIES[name] = name
        return name
    V = {"正式版": rr.BASE}
    A = {"A1 ＋W底突破頸線": ["W底突破"], "A2 ＋帶量突破20日高": ["帶量突破20日高"], "A3 ＋法人連3日買超": ["法人連3日買超"],
         "A4 ＋融資20日降10%": ["融資20日降10%"], "A5 ＋跌深任一天（對照）": ["跌深任一天"]}
    for name, parts in A.items():
        V[name] = {**rr.BASE, "entry": add_entry(name, parts)}
    V["B1 換股·殖利率跌破續抱就讓"] = {**rr.BASE, "switch": {"min_gain": 0.0, "hy": None, "floor": False, "money": False, "margin": 0.0, "no_growth": True}}
    V["B2 呆部位出清 365 天"] = {**rr.BASE, "stale_exit": (365, 0.12)}
    V["B3 呆部位出清 180 天"] = {**rr.BASE, "stale_exit": (180, 0.12)}
    V["C1 每半年補虧結算"] = {**rr.BASE, "settle": (6, "offset")}
    V["C2 每年補虧結算"] = {**rr.BASE, "settle": (12, "offset")}
    member = {sid: G["member"][sid].values for sid in G["sub"]}
    for tag, part in (("D1 核心5＋撿股1（W底）", "W底突破"), ("D2 核心5＋撿股1（帶量突破）", "帶量突破20日高")):
        split = f"split:{tag}"
        rs.SPLITS[split] = {"核心": (5, member), "撿股": (1, {sid: raw[part][sid] & member[sid] for sid in G["sub"]})}
        V[tag] = {**rr.BASE, "entry": add_entry(f"entry:{tag}", [part]), "split": split}
    def thr(v): return {**rr.BASE, "mkt": ("all", 0.0, None, v), "min_yield": v}
    B1 = V["B1 換股·殖利率跌破續抱就讓"]["switch"]
    V["E3 門檻下限 4.5%"] = thr(4.5)
    V["E10 7 檔＋門檻 4.5%"] = {**thr(4.5), "max_slots": 7}
    V["E11 停利 8%＋B1 換股"] = {**rr.BASE, "target": 0.08, "switch": B1}
    V["E13 A2 帶量突破＋B1 換股"] = {**rr.BASE, "entry": V["A2 ＋帶量突破20日高"]["entry"], "switch": B1}
    prof = {sid: ps.profit_years_flag(G["sub"][sid].get("annual_eps"), G["dates"], 5) for sid in G["sub"]}
    both = {sid: raw["W底突破"][sid] | raw["帶量突破20日高"][sid] for sid in G["sub"]}
    sat = {sid: both[sid] & member[sid] & prof[sid] & (np.nan_to_num(G["sub"][sid]["yield"], nan=-1) >= 3.0) for sid in G["sub"]}
    for k in (2, 3):
        nm = f"G{k - 1} 衛星 {k} 檔·殖利率≥3%·持滿126日"
        rs.SPLITS[nm] = {"核心": (5, member), "撿股": (k, sat)}
        V[nm] = {**rr.BASE, "split": nm, "max_hold_days": 126, "zone_hold": "撿股", "zone_buy": {"撿股"}}
    return V


def main():
    groups = [a for a in sys.argv[1:] if a in "ABCDEG"] or list("ABCDEG")
    po.setup(); G = rs.G; dates = G["dates"]
    raw, counts = build_signals(G)
    counts.to_csv(RESULTS / "turnover_counts.csv", index=False, encoding="utf-8-sig")
    print("全池訊號檔日數（2017 起到截止日）：", counts.drop(columns="代號").sum().to_dict(), flush=True)
    V = {k: v for k, v in variants(G, raw).items() if k == "正式版" or k[0] in groups}
    s17 = dates.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    tag = "_all" if len(groups) == 6 else "_" + "".join(groups)      # 評估暫存檔用 to_<組別>_i，不同組同時跑不會互相刪檔
    res, money = {}, {}
    for i, (name, cfg) in enumerate(V.items()):
        po.CONFIGS[name] = cfg; po.apply(cfg)
        m = po.evaluate([name], f"to{tag}_{i}").loc[name]
        if i:
            for k_, v in paired_from_files(f"to{tag}_0", f"to{tag}_{i}").items():
                m[k_] = v
        res[name] = m
        po.apply(cfg); kw = po.to_kw(cfg)
        sp = rs.SPLITS.get(cfg.get("split", "不分區"))
        extra = {"slot_split": sp} if isinstance(sp, dict) else {}
        for sn, s in (("2016-12-28", 1), ("2017-01-03", s17)):
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, start_n=s, **kw, **extra)
            money[(name, sn)] = dict(期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[s]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                                     回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr),
                                     勝率=round(100 * (tr["報酬%"].dropna() > 0).mean(), 0) if "報酬%" in tr else None,
                                     持有中位日=int(tr["持有日"].median()) if "持有日" in tr else None)
            tr.to_csv(RESULTS / f"turnover{tag}_trades_{i}_{sn}.csv", index=False, encoding="utf-8-sig")
        print(f"  {name}：三段 {m['三段平均']:.2f} σ {m['標準差平均']:.2f} 最差10 {m['最差10最小']:.2f} 筆數 {money[(name, '2016-12-28')]['筆數']}", flush=True)
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "前7年配對最差", "後3年配對"] if c in out.columns]
    mon = pd.DataFrame(money).T
    out[show].to_csv(RESULTS / f"turnover{tag}_eval.csv", encoding="utf-8-sig"); mon.to_csv(RESULTS / f"turnover{tag}_money.csv", encoding="utf-8-sig")
    for f in RESULTS.glob(f"param_opt_to{tag}_*"):
        f.unlink()
    b = res["正式版"]
    lines = ["# 周轉研究（turnover_study.py）", "", f"目標：500 萬 12-28 路徑筆數 ≥ {TARGET_TRADES}（正式版 {money[('正式版', '2016-12-28')]['筆數']}），三段平均與 σ 不能差太多。紅線：σ ≤+0.15 且前 7 年配對 ≥14/20。", "",
             "| 版本 | 筆數 | 三段平均 | Δ | 最差 10% | σ | Δσ | 前 7 年配對 | 後 3 年配對 | 500 萬 12-28 | 01-03 | 回撤 | 持有中位日 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in V:
        m = res[name]; a, c = money[(name, "2016-12-28")], money[(name, "2017-01-03")]
        lines.append(f"| {name} | {a['筆數']} | {m['三段平均']:.2f} | {m['三段平均'] - b['三段平均']:+.2f} | {m['最差10最小']:.2f} | {m['標準差平均']:.2f} | {m['標準差平均'] - b['標準差平均']:+.2f} | "
                     f"{m.get('前7年配對', '—')} | {m.get('後3年配對', '—')} | {a['期末萬']:,}（{a['IRR']}） | {c['期末萬']:,}（{c['IRR']}） | {a['回撤']} | {a['持有中位日']} |")
    (RESULTS / "turnover_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
