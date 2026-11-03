"""每日報表的「劇本」文字（2026-11-03 使用者：「無論買進或賣出觀察名單，都要給我未來的劇本要如何執行」；
同日更正：「點位接近或未來三天才有可能發生的才告知，否則單純給目標價就好」）。
只是把引擎已經在用的規則換算成「價位／量／日期」印出來，不改任何規則。
  holding_script：每檔持股 → 賣出目標價一定給；加碼／補足／不佔名額只在「價位距現價 5% 內、或日期在 5 天內」才展開條件，否則只給觸發價。
  watch_script：每檔觀察股 → 殖利率門檻上限價一定給；六種技術買點只列「近 3 天內可能成立」的（已碰下軌、已跌深、剛出現長下影線），其餘不列。"""
import numpy as np
import pandas as pd

from indicators import atr, bollinger, kd, sma, wick_conditions

NEAR_PX, NEAR_DAYS = 0.05, 5     # 「接近」：價位距現價 5% 內；日期在 5 個日曆天內


def _fmt(x, nd=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{nd}f}"


def _near(px, level):
    return not np.isnan(level) and abs(px / level - 1) <= NEAR_PX


def holding_script(sid, name, q, d, p, dates, capital, final, steps=(-0.15, -0.30), adds=(0.30, 0.20), time_add_days=182, time_add_amount=0.20,
                   stale_days=365, stale_loss=-0.30):
    px = d["close_ff"][p]; avg = q["cost"] / q["shares"]; gain = px / avg - 1; y = d["yield"][p]
    hy = d["hy_rel"][p] if "hy_rel" in d else final["hold_yield"]
    tp = avg * (1 + final["target"])
    hyp = px * y / hy if (not np.isnan(y) and not np.isnan(hy) and hy > 0) else np.nan
    need = max(tp, hyp) if not np.isnan(hyp) else tp
    budget = q["budget"] * capital
    vol20 = d["df"]["volume"].rolling(20).mean().iloc[-1] if "df" in d else np.nan
    held = (dates[p] - dates[q["start"]]).days
    today = dates[p]
    sig_txt = f"爆量（> {_fmt(1.5 * vol20 / 1000, 0)} 張）長下影線或長紅"
    L = [f"◆ {sid} {name}（{_fmt(px)}，損益 {gain:+.1%}）"]
    # 賣出：目標價一定給
    if gain >= final["target"] and not np.isnan(y) and not np.isnan(hy) and y >= hy:
        L.append(f"  賣出：獲利已 ≥12%，等股價站上約 {_fmt(hyp)}（殖利率跌破 {_fmt(hy, 2)}%）→ 隔天開盤全賣")
    elif _near(px, need):
        L.append(f"  賣出：**接近** 收盤 ≥ 約 {_fmt(need)}（停利價 {_fmt(tp)}、續抱線價 {_fmt(hyp)}）→ 隔天開盤全賣")
    else:
        L.append(f"  賣出目標價：約 {_fmt(need)}（+{need / px - 1:.0%}）")
    # 加碼：接近才展開
    lv = [q["first"] * (1 + st) for st in steps]
    shown = False
    for i, (st, amt) in enumerate(zip(steps, adds)):
        if q["adds"] > i:
            continue
        hit = q.get("hit", 0) > i or q.get("low", px) <= lv[i]
        if hit or _near(px, lv[i]):
            L.append(f"  跌深加碼{'①②'[i]}：**{'已跌到' if hit else '接近'}** {_fmt(lv[i])}（首買 {st:+.0%}），{'接下來' if hit else '跌到後'}出現{sig_txt}且收盤 < {_fmt(q['first'])} → 隔天開盤加碼約 {budget * amt / 1e4:,.0f} 萬")
            shown = True
            break
    if not shown and q["adds"] < len(steps):
        L.append(f"  跌深加碼觸發價：{'／'.join(_fmt(x) for x in lv[q['adds']:])}（出現{sig_txt}才加）")
    nxt = dates[q["start"]] + pd.Timedelta(days=time_add_days * (q.get("time_adds", 0) + 1))
    if (nxt - today).days <= NEAR_DAYS and gain < 0:
        L.append(f"  定期加碼：**{nxt.date()} 起**仍虧損、出現{sig_txt}且收盤 < 均價 {_fmt(avg)} → 加碼約 {budget * time_add_amount / 1e4:,.0f} 萬")
    if gain >= 0 and not np.isnan(y) and "yield_ok" in d and d["yield_ok"][p]:
        L.append("  補足：目前賺錢且殖利率達門檻，再出現技術買訊 → 補到可投資資產 ÷ 5 × 首買比例")
    stale_px = avg * (1 + stale_loss)
    stale_day = dates[q["start"]] + pd.Timedelta(days=stale_days)
    if held > stale_days or gain < stale_loss:
        L.append("  名額：已不佔名額（空位讓給新買點，部位照抱）")
    elif (stale_day - today).days <= NEAR_DAYS or _near(px, stale_px):
        L.append(f"  名額：**接近** {stale_day.date()} 或收盤 < {_fmt(stale_px)} 起不佔名額")
    return "\n".join(L)


def watch_script(sid, name, df, y, gate, growth, own_med, thr):
    df = df.dropna(subset=["close"])
    c, lo, hi, v = df["close"], df["low"], df["high"], df["volume"]
    px = c.iloc[-1]
    dps = y / 100 * px if not np.isnan(y) else np.nan
    gate_px = dps / (gate / 100) if not np.isnan(dps) and gate > 0 else np.nan
    L = [f"◆ {sid} {name}（{_fmt(px)}，殖利率 {_fmt(y, 2)}% vs 門檻 {_fmt(gate, 2)}%，門檻上限價 {_fmt(gate_px)}）"]
    near = []
    lower, mid, upper = bollinger(df); k, dd = kd(df)
    touched = bool((lo.iloc[-3:] <= lower.iloc[-3:]).any())
    if touched or _near(px, lower.iloc[-1]):
        near.append(f"  布林KD：{'已碰' if touched else '接近'}下軌 {_fmt(lower.iloc[-1])}；K {k.iloc[-1]:.0f}／D {dd.iloc[-1]:.0f}，等 K 翻上 D（K<30）→ 隔天開盤買")
    h60 = c.iloc[-60:].max(); dd60 = px / h60 - 1; pl = lo.iloc[-23:-3].min(); lows3 = lo.iloc[-3:].tolist()
    if dd60 <= -0.15:
        ok3 = all(x >= pl * 0.97 for x in lows3); tested = any(x <= pl * 1.03 for x in lows3)
        near.append(f"  落底：已跌深 {dd60:+.1%}；前低 {_fmt(pl)}，三日低點要 ≥ {_fmt(pl * 0.97)} 且一根 ≤ {_fmt(pl * 1.03)}（近三日 {'／'.join(_fmt(x) for x in lows3)}，"
                    f"{'守住' if ok3 else '已破'}{'、已測' if tested else '、未測'}）")
    elif _near(px, h60 * 0.85):
        near.append(f"  落底：接近跌深線 {_fmt(h60 * 0.85)}（60 日高 −15%），之後三根守住前低 {_fmt(pl)} ±3% 才算")
    wc = wick_conditions(df)
    v5 = v.iloc[-6:-1].mean()
    for back in (1, 2):      # 前一、二天有長下影線且量 ≥ 0.8×5 日均量 → 站穩進行中
        i = -back - 1 if back else -1
        if len(df) > 3 and bool(wc["long_lower"].iloc[-back]) and v.iloc[-back] >= 0.8 * v.iloc[-back - 5:-back].mean():
            ref = c.iloc[-back]
            near.append(f"  下影線站穩：{df.index[-back].date()} 出現長下影線（收 {_fmt(ref)}），之後兩天收盤都 ≥ {_fmt(ref)} 就成立（已過 {back - 1} 天）")
            break
    if near:
        L += near
    else:
        L.append(f"  目前沒有接近中的技術買訊；跌深線 {_fmt(h60 * 0.85)}、布林下軌 {_fmt(lower.iloc[-1])}，爆量／長下影線型訊號無法預判")
    return "\n".join(L)
