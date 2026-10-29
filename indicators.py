"""技術指標與多空訊號。

每個策略函式回傳 (buy, sell) 兩個布林 Series：當天收盤出現買進／賣出訊號。
"""
import numpy as np
import pandas as pd


# ---------- 基礎指標 ----------

def sma(s, n):
    return s.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def cross_down(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


def atr(df, n=14):
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def kd(df, n=9):
    low_n, high_n = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    return k, d


def rsi(s, n=14):
    diff = s.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def macd(s, fast=12, slow=26, signal=9):
    dif = ema(s, fast) - ema(s, slow)
    return dif, ema(dif, signal)


def dmi(df, n=14):
    up, down = df["high"].diff(), -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    a = atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / a
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return plus_di, minus_di, dx.ewm(alpha=1 / n, adjust=False).mean()


def obv(df):
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


# ---------- 策略：A 趨勢類 ----------

def a1_ma_cross(df):
    fast, slow = sma(df["close"], 20), sma(df["close"], 60)
    return cross_up(fast, slow), cross_down(fast, slow)


def a2_price_ma(df):
    ma = sma(df["close"], 60)
    return cross_up(df["close"], ma), cross_down(df["close"], ma)


def a3_macd(df):
    dif, dea = macd(df["close"])
    return cross_up(dif, dea), cross_down(dif, dea)


def a4_dmi(df):
    plus_di, minus_di, adx = dmi(df)
    trending = adx > 25
    return trending & (plus_di > minus_di), cross_down(plus_di, minus_di)


def a5_ma_alignment(df):
    c = df["close"]
    bull = (sma(c, 5) > sma(c, 20)) & (sma(c, 20) > sma(c, 60))
    return bull & ~bull.shift(1, fill_value=False), sma(c, 5) < sma(c, 20)


# ---------- 策略：B 震盪類 ----------

def b1_kd(df):
    k, d = kd(df)
    return cross_up(k, d) & (k < 20), cross_down(k, d) & (k > 80)


def b2_rsi(df):
    r = rsi(df["close"])
    return cross_up(r, pd.Series(30, index=df.index)), cross_down(r, pd.Series(70, index=df.index))


def b3_williams(df, n=14):
    high_n, low_n = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    wr = (high_n - df["close"]) / (high_n - low_n) * -100
    return cross_up(wr, pd.Series(-80, index=df.index)), cross_down(wr, pd.Series(-20, index=df.index))


def b4_cci(df, n=20):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mad = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma(tp, n)) / (0.015 * mad)
    return cross_up(cci, pd.Series(-100, index=df.index)), cross_down(cci, pd.Series(100, index=df.index))


def b5_bias(df, n=20, th=7):
    bias = (df["close"] / sma(df["close"], n) - 1) * 100
    return cross_up(bias, pd.Series(-th, index=df.index)), cross_down(bias, pd.Series(th, index=df.index))


# ---------- 策略：C 波動／通道類 ----------

def c1_bollinger(df, n=20, k=2):
    mid = sma(df["close"], n)
    sd = df["close"].rolling(n).std()
    return cross_up(df["close"], mid - k * sd), cross_down(df["close"], mid + k * sd)


def c2_donchian(df):
    return df["close"] > df["high"].rolling(20).max().shift(1), df["close"] < df["low"].rolling(10).min().shift(1)


def c3_keltner(df):
    mid = ema(df["close"], 20)
    return cross_up(df["close"], mid + 1.5 * atr(df)), cross_down(df["close"], mid)


# ---------- 策略：D 量能類 ----------

def d1_volume_breakout(df):
    vol_ma = sma(df["volume"], 20)
    ma20 = sma(df["close"], 20)
    buy = (df["volume"] > 1.5 * vol_ma) & (df["close"] > df["open"]) & (df["close"].pct_change() > 0.02)
    return buy, cross_down(df["close"], ma20)


def d2_obv(df):
    o = obv(df)
    o_ma = sma(o, 20)
    return cross_up(o, o_ma), cross_down(o, o_ma)


def d3_price_volume(df):
    vol_ma = sma(df["volume"], 20)
    new_high = df["close"] >= df["close"].rolling(20).max()
    buy = new_high & (df["volume"] > 1.2 * vol_ma)            # 價量齊揚
    divergence = new_high & (df["volume"] < 0.8 * vol_ma)     # 價創高量縮
    return buy, divergence | cross_down(df["close"], sma(df["close"], 20))


# ---------- 策略：E 型態類 ----------

def e1_new_high(df):
    return df["close"] >= df["close"].rolling(60).max(), df["close"] <= df["close"].rolling(20).min()


def e2_gap(df):
    gap_up = df["low"] > df["high"].shift(1)
    gap_down = df["high"] < df["low"].shift(1)
    return gap_up, gap_down | cross_down(df["close"], sma(df["close"], 20))


STRATEGIES = {
    "A1 均線交叉 MA20/60": a1_ma_cross,
    "A2 價格站上/跌破 MA60": a2_price_ma,
    "A3 MACD 交叉": a3_macd,
    "A4 ADX/DMI": a4_dmi,
    "A5 均線多頭排列": a5_ma_alignment,
    "B1 KD 低檔金叉/高檔死叉": b1_kd,
    "B2 RSI 30/70": b2_rsi,
    "B3 威廉 %R": b3_williams,
    "B4 CCI ±100": b4_cci,
    "B5 乖離率 ±7%": b5_bias,
    "C1 布林通道": c1_bollinger,
    "C2 唐奇安 20/10": c2_donchian,
    "C3 ATR 通道 (Keltner)": c3_keltner,
    "D1 帶量長紅": d1_volume_breakout,
    "D2 OBV 穿越均線": d2_obv,
    "D3 價量齊揚/背離": d3_price_volume,
    "E1 60 日新高/20 日新低": e1_new_high,
    "E2 跳空缺口": e2_gap,
}


# ---------- 策略：F 上下引線 × 價量 ----------

def shadows(df):
    """回傳 (上影線, 下影線, 全長)。"""
    body_top = df[["open", "close"]].max(axis=1)
    body_bottom = df[["open", "close"]].min(axis=1)
    return df["high"] - body_top, body_bottom - df["low"], df["high"] - df["low"]


def wick_conditions(df, wick_ratio=0.5, vol_mult=1.5):
    """長下影線、長上影線、爆量、低檔、高檔等基本條件。

    長影線：影線占當日 K 棒全長 >= wick_ratio，且全長 >= 0.8 倍 ATR（排除小 K 棒）。
    爆量：成交量 > vol_mult 倍 20 日均量。
    低檔：收盤 < MA20；高檔：收盤 > MA20。
    """
    upper, lower, rng = shadows(df)
    big_bar = rng >= 0.8 * atr(df)
    ma20 = sma(df["close"], 20)
    return {
        "long_lower": (lower >= wick_ratio * rng) & big_bar,
        "long_upper": (upper >= wick_ratio * rng) & big_bar,
        "vol_up": df["volume"] > vol_mult * sma(df["volume"], 20),
        "low_zone": df["close"] < ma20,
        "high_zone": df["close"] > ma20,
    }


def f1_wick(df):
    c = wick_conditions(df)
    return c["long_lower"], c["long_upper"]


def f2_wick_volume(df):
    c = wick_conditions(df)
    return c["long_lower"] & c["vol_up"], c["long_upper"] & c["vol_up"]


def f3_wick_volume_zone(df):
    c = wick_conditions(df)
    return (c["long_lower"] & c["vol_up"] & c["low_zone"],
            c["long_upper"] & c["vol_up"] & c["high_zone"])


def f4_wick_zone(df):
    c = wick_conditions(df)
    return c["long_lower"] & c["low_zone"], c["long_upper"] & c["high_zone"]


WICK_STRATEGIES = {
    "F1 下影線買／上影線賣": f1_wick,
    "F2 ＋爆量": f2_wick_volume,
    "F3 ＋爆量＋位置（低檔下影／高檔上影）": f3_wick_volume_zone,
    "F4 ＋位置（不看量）": f4_wick_zone,
}


# ---------- 策略：G MACD × KD 組合 ----------
# 原則：MACD 判斷趨勢方向，KD 抓進場時機。

def g1_macd_kd(df):
    """MACD 多方（DIF > DEA）時 KD 金叉買；KD 死叉賣。"""
    dif, dea = macd(df["close"])
    k, d = kd(df)
    return cross_up(k, d) & (dif > dea), cross_down(k, d)


def g2_macd_kd_macd_exit(df):
    """MACD 多方時 KD 金叉買；MACD 死叉賣（抱得比較久）。"""
    dif, dea = macd(df["close"])
    k, d = kd(df)
    return cross_up(k, d) & (dif > dea), cross_down(dif, dea)


def g3_zero_line_pullback(df):
    """DIF 在零軸之上（中期多頭）、KD 在 50 以下金叉（拉回買點）；MACD 死叉賣。"""
    dif, dea = macd(df["close"])
    k, d = kd(df)
    return cross_up(k, d) & (k < 50) & (dif > 0), cross_down(dif, dea)


def g4_double_confirm(df):
    """雙重確認：DIF > DEA 且 K > D 同時成立的第一天買；任一條件消失就賣。"""
    dif, dea = macd(df["close"])
    k, d = kd(df)
    both = (dif > dea) & (k > d)
    return both & ~both.shift(1, fill_value=False), ~both


MACD_KD_STRATEGIES = {
    "A3 MACD 交叉（單獨）": a3_macd,
    "B1 KD 低檔金叉/高檔死叉（單獨）": b1_kd,
    "G1 MACD 多方＋KD 金叉買／KD 死叉賣": g1_macd_kd,
    "G2 MACD 多方＋KD 金叉買／MACD 死叉賣": g2_macd_kd_macd_exit,
    "G3 DIF>0＋KD<50 金叉買／MACD 死叉賣": g3_zero_line_pullback,
    "G4 雙重確認買／任一轉弱賣": g4_double_confirm,
}
