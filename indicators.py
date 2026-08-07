"""Technical indicator calculations."""
from __future__ import annotations
import pandas as pd
import numpy as np


def calc_ma(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
    """Calculate moving averages (short + long term)."""
    if periods is None:
        periods = [5, 10, 20, 60, 120, 250]
    for p in periods:
        if len(df) >= p:
            df[f"MA{p}"] = df["close"].rolling(window=p).mean()
    return df


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Calculate MACD indicator."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD_BAR"] = 2 * (df["DIF"] - df["DEA"])
    return df


def calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """Calculate KDJ indicator."""
    low_n = df["low"].rolling(window=n).min()
    high_n = df["high"].rolling(window=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d

    df["K"] = k
    df["D"] = d
    df["J"] = j
    return df


def calc_rsi(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
    """Calculate RSI indicator."""
    if periods is None:
        periods = [6, 14]
    delta = df["close"].diff()
    for p in periods:
        gain = delta.where(delta > 0, 0).rolling(window=p).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=p).mean()
        rs = gain / loss.replace(0, np.nan)
        df[f"RSI{p}"] = 100 - (100 / (1 + rs))
    return df


def calc_bollinger(df: pd.DataFrame, period: int = 20, std: int = 2) -> pd.DataFrame:
    """Calculate Bollinger Bands."""
    df["BOLL_MID"] = df["close"].rolling(window=period).mean()
    std_dev = df["close"].rolling(window=period).std()
    df["BOLL_UP"] = df["BOLL_MID"] + std * std_dev
    df["BOLL_DN"] = df["BOLL_MID"] - std * std_dev
    df["BOLL_WIDTH"] = (df["BOLL_UP"] - df["BOLL_DN"]) / df["BOLL_MID"] * 100
    return df


def calc_volume_ma(df: pd.DataFrame, period: int = 5) -> pd.DataFrame:
    """Calculate volume moving average and volume ratio."""
    df["VOL_MA5"] = df["volume"].rolling(window=period).mean()
    df["VOL_RATIO"] = df["volume"] / df["VOL_MA5"]
    return df


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate Average True Range (ATR) for volatility-based stops."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = true_range.rolling(window=period).mean()
    df["ATR_PCT"] = df["ATR"] / close * 100  # ATR as % of price
    return df


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate ADX / +DI / -DI trend strength indicators."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low = high.shift(1), low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    # True range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_adx = tr.rolling(window=period).mean()

    plus_di = 100 * plus_dm.rolling(window=period).mean() / atr_adx
    minus_di = 100 * minus_dm.rolling(window=period).mean() / atr_adx

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window=period).mean()

    df["ADX"] = adx
    df["PLUS_DI"] = plus_di
    df["MINUS_DI"] = minus_di
    return df


def find_support_resistance(df: pd.DataFrame, lookback: int = 60) -> tuple[list[float], list[float]]:
    """Find recent support (below price) and resistance (above price) levels."""
    recent = df.tail(lookback)
    close = df["close"].iloc[-1]

    # Support: recent significant lows BELOW current price
    supports = []
    lows = recent["low"].values
    for i in range(2, len(lows) - 2):
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            if lows[i] < close:
                supports.append(lows[i])

    # Resistance: recent significant highs ABOVE current price
    resistances = []
    highs = recent["high"].values
    for i in range(2, len(highs) - 2):
        if highs[i] >= highs[i - 1] and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            if highs[i] > close:
                resistances.append(highs[i])

    # Add key MAs as support (if below price) or resistance (if above price)
    for ma_col in ["MA20", "MA60"]:
        ma_val = df[ma_col].iloc[-1]
        if pd.notna(ma_val):
            if ma_val < close:
                supports.append(ma_val)
            elif ma_val > close:
                resistances.append(ma_val)

    # Deduplicate and sort: supports nearest to price first, resistances nearest first
    supports = sorted(set(round(s, 2) for s in supports), reverse=True)[:3]
    resistances = sorted(set(round(r, 2) for r in resistances))[:3]

    return supports, resistances


def calc_all(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all technical indicators for both short and long term."""
    df = calc_ma(df, periods=[5, 10, 20, 60, 120, 250])
    df = calc_macd(df)
    df = calc_kdj(df)
    df = calc_rsi(df)
    df = calc_bollinger(df)
    df = calc_volume_ma(df)
    df = calc_atr(df)
    df = calc_adx(df)
    return df
