"""每日報表的「劇本」文字（2026-11-03 使用者：「無論買進或賣出觀察名單，都要給我未來的劇本要如何執行」）。
只是把引擎已經在用的規則換算成「價位／量／日期」印出來，不改任何規則。
  holding_script：每檔持股 → 什麼情況賣、什麼情況加碼／補足、何時不佔名額。
  watch_script：每檔觀察股 → 殖利率門檻價，六種技術買點各自還差什麼。"""
import numpy as np
import pandas as pd

from indicators import atr, bollinger, kd, sma


def _fmt(x, nd=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{nd}f}"


def holding_script(sid, name, q, d, p, dates, capital, final, steps=(-0.15, -0.30), adds=(0.30, 0.20), time_add_days=182, time_add_amount=0.20,
                   stale_days=365, stale_loss=-0.30):
    px = d["close_ff"][p]; avg = q["cost"] / q["shares"]; gain = px / avg - 1; y = d["yield"][p]
    hy = d["hy_rel"][p] if "hy_rel" in d else final["hold_yield"]
    tp = avg * (1 + final["target"])
    hyp = px * y / hy if (not np.isnan(y) and not np.isnan(hy) and hy > 0) else np.nan
    budget = q["budget"] * capital
    vol20 = d["df"]["volume"].rolling(20).mean().iloc[-1] if "df" in d else np.nan
    held = (dates[p] - dates[q["start"]]).days
    L = [f"◆ {sid} {name}（現價 {_fmt(px)}、均價 {_fmt(avg)}、損益 {gain:+.1%}、殖利率 {_fmt(y, 2)}%、續抱線 {_fmt(hy, 2)}%）"]
    # 賣出
    need = max(tp, hyp) if not np.isnan(hyp) else tp
    if gain >= final["target"] and not np.isnan(y) and not np.isnan(hy) and y >= hy:
        L.append(f"  賣出：獲利已 ≥12%，只等殖利率跌破 {_fmt(hy, 2)}%（股價站上約 {_fmt(hyp)} 就成立）→ 隔天開盤全部賣")
    else:
        why = f"停利價 {_fmt(tp)}" + (f"、續抱線價 {_fmt(hyp)}" if not np.isnan(hyp) else "")
        L.append(f"  賣出：收盤 ≥ 約 {_fmt(need)}（同時滿足 {why}）→ 隔天開盤全部賣；殖利率若因 EPS／股利改變，續抱線價會跟著動")
    L.append("  其他賣出：近四季 EPS 合計轉負 → 隔天賣；被移出成分股後出現爆量上影線／長黑且不賠 → 賣")
    # 加碼
    sig_txt = f"出現「爆量（> {_fmt(1.5 * vol20 / 1000, 0)} 張，20 日均量 1.5 倍）長下影線或長紅」"
    for i, (st, amt) in enumerate(zip(steps, adds)):
        if q["adds"] > i:
            L.append(f"  跌深加碼{'①②'[i]}：已做")
            continue
        lvl = q["first"] * (1 + st)
        hit = q.get("hit", 0) > i or q.get("low", px) <= lvl
        L.append(f"  跌深加碼{'①②'[i]}：收盤曾跌到首買價 {st:+.0%}（{_fmt(lvl)}）{'（已跌到）' if hit else ''}之後，{sig_txt}且收盤仍 < 首買價 {_fmt(q['first'])} → 隔天開盤加碼約 {budget * amt / 1e4:,.0f} 萬")
    nxt = dates[q["start"]] + pd.Timedelta(days=time_add_days * (q.get("time_adds", 0) + 1))
    L.append(f"  定期加碼：{nxt.date()} 起（持有滿 {time_add_days} 天×{q.get('time_adds', 0) + 1}）若仍虧損、{sig_txt}且收盤 < 均價 → 加碼約 {budget * time_add_amount / 1e4:,.0f} 萬")
    L.append("  補足：收盤 ≥ 均價時若再次出現完整買點（殖利率達門檻＋技術買訊）→ 補到當天可投資資產 ÷ 5 × 首買比例（補完現金須 ≥ 一筆首買）")
    stale_px = avg * (1 + stale_loss)
    stale_day = dates[q["start"]] + pd.Timedelta(days=stale_days)
    L.append(f"  名額：{stale_day.date()} 起（持有 > {stale_days} 天）或收盤 < {_fmt(stale_px)}（虧 >30%）→ 不佔名額，空位讓給新買點（部位照抱）"
             + ("；目前已不佔名額" if (held > stale_days or gain < stale_loss) else ""))
    return "\n".join(L)


def watch_script(sid, name, df, y, gate, growth, own_med, thr):
    """df＝原始日線（到最新一天）；y＝預估殖利率；gate＝這檔的買進門檻；thr＝市場門檻。"""
    df = df.dropna(subset=["close"])
    c, lo, hi, v = df["close"], df["low"], df["high"], df["volume"]
    px = c.iloc[-1]
    dps = y / 100 * px if not np.isnan(y) else np.nan
    gate_px = dps / (gate / 100) if not np.isnan(dps) and gate > 0 else np.nan
    L = [f"◆ {sid} {name}（現價 {_fmt(px)}、殖利率 {_fmt(y, 2)}%、門檻 {_fmt(gate, 2)}%{'＝自己中位 ' + _fmt(own_med, 2) + '%×1.25' if growth else '＝max(市場中位, 5%)'}）"]
    L.append(f"  殖利率：收盤 ≤ 約 {_fmt(gate_px)} 都達門檻（現在{'達標' if y >= gate else '未達'}，差 {y - gate:+.2f} 點）；達門檻那天同時出現下面任一技術買訊 → 隔天開盤買")
    # 布林 KD
    lower, mid, upper = bollinger(df); k, dd = kd(df)
    touched = bool((lo.iloc[-3:] <= lower.iloc[-3:]).any())
    L.append(f"  ①布林KD：下軌 {_fmt(lower.iloc[-1])}（近 3 日{'已碰' if touched else '未碰，低點要 ≤ 下軌'}）；K {k.iloc[-1]:.0f}／D {dd.iloc[-1]:.0f}，"
             f"需 K 由下往上穿過 D 且 K < 30{'（今天已成立）' if touched and k.iloc[-1] > dd.iloc[-1] and k.iloc[-2] <= dd.iloc[-2] and k.iloc[-1] < 30 else ''}")
    # 落底
    h60 = c.iloc[-60:].max(); dd60 = px / h60 - 1
    pl = lo.iloc[-23:-3].min()
    lows3 = lo.iloc[-3:].tolist()
    deep_ok = dd60 <= -0.15
    L.append(f"  ②落底：距 60 日高 {_fmt(h60)} 為 {dd60:+.1%}{'（已跌深 ≥15%）' if deep_ok else f'（需收盤 ≤ {_fmt(h60 * 0.85)}）'}；前低 {_fmt(pl)}，"
             f"連續三根低點都 ≥ {_fmt(pl * 0.97)} 且至少一根 ≤ {_fmt(pl * 1.03)}（近三日低點 {'／'.join(_fmt(x) for x in lows3)}）")
    # 下影線站穩
    a = atr(df).iloc[-1]; v5 = v.iloc[-6:-1].mean(); v20 = v.iloc[-21:-1].mean()
    L.append(f"  ③下影線站穩：某天 K 棒全長 ≥ {_fmt(0.8 * a)} 元、下影線 ≥ 全長一半、量 ≥ {_fmt(0.8 * v5 / 1000, 0)} 張（5 日均量 0.8 倍），之後兩天收盤都 ≥ 那天收盤 → 第三天為買訊")
    # 價量引線
    L.append(f"  ④價量引線：爆量 > {_fmt(1.5 * v20 / 1000, 0)} 張（20 日均量 1.5 倍）且當天長下影線（同③定義）或收長紅（漲 >2%）")
    L.append(f"  ⑤共振／⑥混合：多個超賣指標同日轉折（KD、RSI、威廉、CCI 等），或收盤在月線 {_fmt(sma(c, 20).iloc[-1])} 之下時出現④ → 由程式判定，不易用單一價位描述")
    return "\n".join(L)
