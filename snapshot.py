"""把一只股票的日线压成一行「当天快照指标」。

推荐（recommend.py）与大师分析（masters.py）都要用同一套指标，抽在这里避免两处口径漂移。
调用前 df 必须已经过 indicators.calc_all()。
"""
from __future__ import annotations


def num(value, default: float = 0.0) -> float:
    """转 float，脏数据（None/字符串/NaN/inf）一律回默认值。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _ratio(a: float, b: float, scale: float = 100.0) -> float:
    return (a / b - 1) * scale if b > 0 else 0.0


def snap(df, code: str, name: str) -> dict:
    l = df.iloc[-1]
    close = num(l["close"])
    prev = num(df["close"].iloc[-2]) if len(df) > 1 else close
    if close <= 0 or prev <= 0:
        return {}

    pct = (close - prev) / prev * 100
    chg5 = _ratio(close, num(df["close"].iloc[-6])) if len(df) > 6 else 0.0
    chg20 = _ratio(close, num(df["close"].iloc[-21])) if len(df) > 21 else 0.0
    chg60 = _ratio(close, num(df["close"].iloc[-61])) if len(df) > 61 else 0.0

    vol = num(l["volume"])
    vol_ma5 = num(l.get("VOL_MA5"))
    vol_ratio = vol / vol_ma5 if vol_ma5 > 0 else 1.0
    amount20 = num(df["amount"].tail(20).mean())
    amount60 = num(df["amount"].tail(60).mean())
    vol20 = num(df["volume"].tail(20).mean())
    vol60 = num(df["volume"].tail(60).mean())

    high = num(l["high"])
    low = num(l["low"])
    amplitude = (high - low) / prev * 100 if prev > 0 else 0.0

    high20 = num(df["high"].iloc[-21:-1].max()) if len(df) > 21 else high
    low20 = num(df["low"].iloc[-21:-1].min()) if len(df) > 21 else low
    high60 = num(df["high"].iloc[-61:-1].max()) if len(df) > 61 else high
    high250 = num(df["high"].tail(250).max())
    low250 = num(df["low"].tail(250).min())

    ma5, ma10, ma20 = num(l.get("MA5")), num(l.get("MA10")), num(l.get("MA20"))
    ma60, ma120, ma250 = num(l.get("MA60")), num(l.get("MA120")), num(l.get("MA250"))

    # 均线斜率：跟 N 个交易日前比，用来判断趋势是在走强还是走平
    ma250_prev = num(df["MA250"].iloc[-21]) if len(df) > 21 else ma250
    ma20_prev = num(df["MA20"].iloc[-11]) if len(df) > 11 else ma20

    return {
        "code": code,
        "name": name,
        "close": close,
        "pct": pct,
        "chg5": chg5,
        "chg20": chg20,
        "chg60": chg60,
        "vol_ratio": vol_ratio,
        "amount20": amount20,
        "amount60": amount60,
        "amplitude": amplitude,
        "atr_pct": num(l.get("ATR_PCT")),
        "rsi": num(l.get("RSI14"), 50.0),
        "j": num(l.get("J"), 50.0),
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "ma60": ma60, "ma120": ma120, "ma250": ma250,
        "ma20_up": ma20 > ma20_prev > 0,
        "ma250_up": ma250 > ma250_prev > 0,
        "high20": high20, "low20": low20, "high60": high60,
        "high250": high250, "low250": low250,
        "dd20": _ratio(close, high20),
        "dist_ma250": _ratio(close, ma250),
        "dist_high250": _ratio(close, high250),
        "dist_low250": _ratio(close, low250),
        "breakout20": close > high20 > 0,
        "breakout60": close > high60 > 0,
        "boll_up": num(l.get("BOLL_UP")),
        "boll_dn": num(l.get("BOLL_DN")),
        "macd_bar": num(l.get("MACD_BAR")),
        "vol20_60": vol20 / vol60 if vol60 > 0 else 1.0,
    }
