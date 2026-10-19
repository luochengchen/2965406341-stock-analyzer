"""每日价格波动驱动的买卖策略。

输入是一份已经算好指标的日线 DataFrame（`fetcher.fetch_daily_kline` + `indicators.calc_all`），
输出给人看的结论：做什么（买入/加仓/持有/减仓/卖出/观望）、急不急、为什么、在哪些价位做。

两条设计原则：

1. **只看当天的价量决定动作**，长周期均线只当背景过滤。原因是同一根均线今天翻多明天翻空，
   那是指标在噪音里说话；真正能执行的是"今天放量突破 / 今天缩量回踩"这种可观测事件。
2. **有持仓和无持仓是两条不同的路**：无仓不可能"减仓"，有仓时止损优先级高于一切。
"""
from __future__ import annotations

import math

import pandas as pd

from indicators import find_support_resistance
from positions import PositionCalculator

# 动作优先级（数字越小越先判断），前端也按这个顺序上色
ACTIONS = ("卖出", "止损", "减仓", "加仓", "买入", "持有", "观望")


def _num(value, default: float = 0.0) -> float:
    """把 DataFrame 里可能为 NaN/None/空串的值转成 float。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _change_pct(df: pd.DataFrame, bars: int) -> float:
    """近 bars 个交易日的涨跌幅（%）。数据不足时返回 0。"""
    if len(df) <= bars:
        return 0.0
    now = _num(df["close"].iloc[-1])
    before = _num(df["close"].iloc[-1 - bars])
    if before <= 0:
        return 0.0
    return (now - before) / before * 100


def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def analyze_day(df: pd.DataFrame, entry: dict | None = None) -> dict:
    """对单只股票给出当天的买卖建议。

    Args:
        df: 含全部技术指标的日线数据（至少 60 行，末尾是最近一个交易日）。
        entry: portfolio 里的自选信息，含 has_position / shares / cost。

    Returns:
        {"action", "urgency", "reasons", "metrics", "levels", "position"}
    """
    entry = entry or {}
    latest = df.iloc[-1]
    close = _num(latest["close"])
    prev_close = _num(df["close"].iloc[-2]) if len(df) > 1 else close
    pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    chg5 = _change_pct(df, 5)
    chg20 = _change_pct(df, 20)

    ma5 = _num(latest.get("MA5"))
    ma10 = _num(latest.get("MA10"))
    ma20 = _num(latest.get("MA20"))
    ma60 = _num(latest.get("MA60"))
    ma120 = _num(latest.get("MA120"))
    atr_pct = _num(latest.get("ATR_PCT"))
    rsi = _num(latest.get("RSI14"), 50.0)
    j = _num(latest.get("J"), 50.0)

    high = _num(latest["high"])
    low = _num(latest["low"])
    volume = _num(latest["volume"])
    vol_ma5 = _num(latest.get("VOL_MA5"))
    vol_ratio = volume / vol_ma5 if vol_ma5 > 0 else 1.0

    amplitude = (high - low) / prev_close * 100 if prev_close > 0 else 0.0
    upper_shadow = (high - close) / (high - low) if high > low else 0.0

    if len(df) >= 22:
        high20 = _num(df["high"].iloc[-21:-1].max())
        low20 = _num(df["low"].iloc[-21:-1].min())
    else:
        high20, low20 = high, low

    supports, resistances = find_support_resistance(df)
    levels = PositionCalculator(df, supports, resistances).calculate_all()
    stop = _num(levels["stop_loss"]["price"])
    take = [_num(lv["price"]) for lv in levels["take_profit"]]
    add = [_num(lv["price"]) for lv in levels["add_position"]]
    target = take[0] if take else close * 1.1
    # 买点：优先用最近的加仓价位（回踩买），没有就在现价买
    buy_point = add[0] if add and 0 < add[0] < close else close

    has_pos = bool(entry.get("has_position"))
    shares = int(entry.get("shares") or 0)
    cost = _num(entry.get("cost"))
    profit_pct = (close - cost) / cost * 100 if has_pos and cost > 0 else 0.0
    profit_amount = (close - cost) * shares if has_pos and cost > 0 else 0.0

    # ---- 当天价量状态 ----
    bull = ma5 > ma10 > ma20 > 0
    bear = 0 < ma5 < ma10 < ma20
    above_ma60 = ma60 > 0 and close > ma60
    breakout = close > high20 > 0
    breakdown = 0 < low20 and close < low20
    heavy_drop = pct <= -4
    heavy_rise = pct >= 5
    volume_surge = vol_ratio >= 1.3
    volume_dry = vol_ratio <= 0.7
    near_ma20 = ma20 > 0 and abs(close - ma20) / ma20 <= 0.025
    near_stop = stop > 0 and close <= stop * 1.015

    reasons: list[str] = [f"今日{pct:+.2f}%（振幅{amplitude:.1f}%），量比{vol_ratio:.2f}"]

    if has_pos:
        action, urgency = _decide_holding(
            close=close, stop=stop, profit_pct=profit_pct, pct=pct, chg5=chg5,
            vol_ratio=vol_ratio, rsi=rsi, j=j, upper_shadow=upper_shadow,
            bull=bull, bear=bear, above_ma60=above_ma60, breakout=breakout,
            breakdown=breakdown, heavy_drop=heavy_drop, volume_surge=volume_surge,
            volume_dry=volume_dry, near_ma20=near_ma20, near_stop=near_stop,
            ma20=ma20, ma60=ma60, high20=high20, low20=low20,
            shares=shares, cost=cost, profit_amount=profit_amount, reasons=reasons,
        )
    else:
        action, urgency = _decide_entry(
            close=close, stop=stop, pct=pct, chg5=chg5, chg20=chg20, vol_ratio=vol_ratio,
            rsi=rsi, j=j, atr_pct=atr_pct, bull=bull, bear=bear, above_ma60=above_ma60,
            breakout=breakout, breakdown=breakdown, heavy_drop=heavy_drop,
            heavy_rise=heavy_rise, volume_surge=volume_surge, volume_dry=volume_dry,
            near_ma20=near_ma20, ma20=ma20, ma60=ma60, ma120=ma120,
            high20=high20, low20=low20, reasons=reasons,
        )

    return {
        "action": action,
        "urgency": urgency,
        "price": _r(close),
        "reasons": reasons[:4],
        "metrics": {
            "pct": _r(pct),
            "chg5": _r(chg5),
            "chg20": _r(chg20),
            "amplitude": _r(amplitude),
            "vol_ratio": _r(vol_ratio),
            "atr_pct": _r(atr_pct),
            "rsi": _r(rsi, 1),
            "high20": _r(high20),
            "low20": _r(low20),
            "ma20": _r(ma20),
            "ma60": _r(ma60),
        },
        "levels": {
            "buy": _r(buy_point),
            "stop": _r(stop),
            "target": _r(target),
            "add": [_r(x) for x in add[:2]],
            "take": [_r(x) for x in take[:2]],
        },
        "position": {
            "shares": shares,
            "cost": _r(cost, 3),
            "profit_pct": _r(profit_pct),
            "profit_amount": _r(profit_amount),
        } if has_pos else None,
    }


def _decide_holding(*, close, stop, profit_pct, pct, chg5, vol_ratio, rsi, j,
                    upper_shadow, bull, bear, above_ma60, breakout, breakdown,
                    heavy_drop, volume_surge, volume_dry, near_ma20, near_stop,
                    ma20, ma60, high20, low20, shares, cost, profit_amount,
                    reasons) -> tuple[str, str]:
    """有持仓：先保命，再谈加仓。"""
    if stop > 0 and close <= stop:
        reasons.insert(0, f"现价{close:.2f}已跌破止损位{stop:.2f}，先离场再讨论")
        return "止损", "高"

    if profit_pct < -10 and not above_ma60:
        reasons.append(f"浮亏{abs(profit_pct):.1f}%且在MA60下方，趋势已走坏")
        return "卖出", "高"

    if heavy_drop and volume_surge:
        reasons.append(f"单日{pct:.1f}%放量下跌（量比{vol_ratio:.1f}），大资金在出逃")
        return "减仓", "高"

    if breakdown and volume_surge:
        reasons.append(f"放量跌破20日低点{low20:.2f}，短线结构破了")
        return "减仓", "高"

    if profit_pct >= 15 and (rsi >= 75 or upper_shadow >= 0.5):
        hints = []
        if rsi >= 75:
            hints.append(f"RSI {rsi:.1f} 超买")
        if upper_shadow >= 0.5:
            hints.append("今日长上影冲高回落")
        reasons.append(f"浮盈{profit_pct:.1f}%，{'、'.join(hints)}，可先落袋一部分")
        return "减仓", "中"

    if profit_pct > 0 and bear:
        reasons.append("短线均线转空头，浮盈单先减一半保住利润")
        return "减仓", "中"

    if near_stop and pct < 0:
        reasons.append(f"现价距止损位{stop:.2f}只剩{(close - stop) / close * 100:.1f}%，跌破就走")
        return "减仓", "中"

    if breakout and volume_surge and bull:
        reasons.append(f"放量突破20日高点{high20:.2f}且均线多头，趋势加速可加")
        return "加仓", "中"

    if near_ma20 and above_ma60 and not bear and profit_pct > -5:
        reasons.append(f"回踩MA20（{ma20:.2f}）附近获得支撑，趋势未破")
        return "加仓", "低"

    if volume_dry and above_ma60 and pct > -1:
        reasons.append("缩量整理，没有抛压，原仓拿着")
        return "持有", "低"

    if above_ma60:
        reasons.append(f"站稳MA60（{ma60:.2f}），趋势完好，持有观察")
    else:
        reasons.append(f"在MA60（{ma60:.2f}）下方，反弹到均线附近再考虑减")
    return "持有", "低"


def _decide_entry(*, close, stop, pct, chg5, chg20, vol_ratio, rsi, j, atr_pct,
                  bull, bear, above_ma60, breakout, breakdown, heavy_drop,
                  heavy_rise, volume_surge, volume_dry, near_ma20, ma20, ma60,
                  ma120, high20, low20, reasons) -> tuple[str, str]:
    """无持仓：只找"现在能买"的位置，其余一律观望。"""
    if bear and not above_ma60:
        reasons.append(f"均线空头排列且价在MA60（{ma60:.2f}）下方，不参与")
        return "观望", "低"

    if heavy_drop:
        reasons.append(f"单日{pct:.1f}%大跌，不接飞刀，等缩量企稳再看")
        return "观望", "低"

    if breakdown:
        reasons.append(f"跌破20日低点{low20:.2f}，等重回区间内再谈")
        return "观望", "低"

    if rsi >= 78:
        reasons.append(f"RSI {rsi:.1f} 过热，追高性价比低，等回调")
        return "观望", "低"

    if breakout and volume_surge and bull and rsi < 75:
        reasons.append(f"放量突破20日高点{high20:.2f}，均线多头，短线资金进场")
        return "买入", "中"

    if near_ma20 and above_ma60 and ma20 > ma60:
        reasons.append(f"回踩MA20（{ma20:.2f}）支撑，中期趋势向上，可低吸")
        return "买入", "中"

    if volume_dry and above_ma60 and ma20 > ma60 and pct > -1.5:
        reasons.append(f"缩量回踩、抛压释放，站上MA60（{ma60:.2f}）可小仓试")
        return "买入", "低"

    if heavy_rise and not breakout:
        reasons.append(f"今日{pct:+.1f}%但在压力位下方，等突破或回踩再进")
        return "观望", "低"

    if above_ma60 and ma20 > ma60 and vol_ratio >= 0.9:
        reasons.append(f"MA20上穿MA60、价在MA60上方，趋势偏多但今天没有买点")
        return "观望", "低"

    reasons.append(f"MA20（{ma20:.2f}）与MA60（{ma60:.2f}）未形成多头，信号不明确")
    return "观望", "低"
