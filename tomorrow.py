"""明日买卖建议：把「今天的价量 + 关键价位」翻译成明天开盘前后能执行的条件句。

和 `strategy.analyze_day()` 的区别：

- `analyze_day` 回答「**今天**该做什么」，用的是今天已经发生的事实。
- 本模块回答「**明天**该怎么应对」，输出的是条件句（「回踩 X 附近买、跌破 Y 止损」），
  因为明天的价格还没发生，只能给区间和触发条件。

所有价位都从已有的技术位推导，不引入新指标，保证和止损/加仓/止盈口径一致。
"""
from __future__ import annotations

import math

import pandas as pd


def _num(value, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def _px(value: float, close: float) -> float:
    """价位精度：低价品种（ETF 常在 0.3~3 元）用三位小数，否则四舍五入到分。"""
    if not close or close >= 2:
        return _r(value, 2)
    return _r(value, 3)


def plan(df: pd.DataFrame, entry: dict | None = None, advice: dict | None = None) -> dict:
    """生成明日操作预案。

    Args:
        df: 已算好指标的日线（末尾是今天）。
        entry: portfolio 条目（has_position / shares / cost）。
        advice: 今天 `strategy.analyze_day()` 的结果，用来保持动作一致。

    Returns:
        {"bias", "score", "confidence", "action", "levels", "plan", "reasons"}
    """
    entry = entry or {}
    advice = advice or {}
    latest = df.iloc[-1]

    close = _num(latest["close"])
    prev_close = _num(df["close"].iloc[-2]) if len(df) > 1 else close
    pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    ma5 = _num(latest.get("MA5"))
    ma10 = _num(latest.get("MA10"))
    ma20 = _num(latest.get("MA20"))
    ma60 = _num(latest.get("MA60"))
    boll_up = _num(latest.get("BOLL_UP"))
    boll_dn = _num(latest.get("BOLL_DN"))
    rsi = _num(latest.get("RSI14"), 50.0)
    atr_pct = _num(latest.get("ATR_PCT"), 2.0)
    vol_ma5 = _num(latest.get("VOL_MA5"))
    vol_ratio = _num(latest.get("volume")) / vol_ma5 if vol_ma5 > 0 else 1.0

    high = _num(latest["high"])
    low = _num(latest["low"])
    amplitude = (high - low) / prev_close * 100 if prev_close > 0 else 0.0
    close_pos = (close - low) / (high - low) if high > low else 0.5

    if len(df) >= 21:
        high20 = _num(df["high"].iloc[-20:].max())
        low20 = _num(df["low"].iloc[-20:].min())
    else:
        high20, low20 = high, low

    has_pos = bool(entry.get("has_position"))
    shares = int(entry.get("shares") or 0)
    cost = _num(entry.get("cost"))
    levels = advice.get("levels") or {}
    stop = _num(levels.get("stop"))
    target = _num(levels.get("target")) or close * 1.1
    add = _num((levels.get("add") or [0])[0])
    take = [_num(x) for x in (levels.get("take") or [])]

    # ---- 打分：-5 偏空 … +5 偏多 ----
    score = 0
    reasons: list[str] = []
    if ma5 > ma10 > ma20 > 0:
        score += 2
        reasons.append("均线多头排列（MA5>MA10>MA20）")
    elif 0 < ma5 < ma10 < ma20:
        score -= 2
        reasons.append("均线空头排列（MA5<MA10<MA20）")
    if ma20 > 0:
        score += 1 if close > ma20 else -1
        reasons.append(f"{'站上' if close > ma20 else '跌破'}MA20（{ma20:.2f}）")
    if close_pos >= 0.7:
        score += 1
        reasons.append(f"收盘在日内高位（{close_pos * 100:.0f}% 位置）")
    elif close_pos <= 0.3:
        score -= 1
        reasons.append(f"收盘在日内低位（{close_pos * 100:.0f}% 位置），明早容易低开")
    if 1.2 <= vol_ratio <= 2.6:
        score += 1
        reasons.append(f"量比 {vol_ratio:.2f}，放量但不失控")
    elif vol_ratio >= 3.5:
        score -= 1
        reasons.append(f"量比 {vol_ratio:.2f}，放天量，次日冲高回落概率高")
    if rsi >= 78:
        score -= 1
        reasons.append(f"RSI {rsi:.1f} 偏热")
    elif rsi <= 32:
        score += 1
        reasons.append(f"RSI {rsi:.1f} 偏冷，有超跌反弹空间")
    if close > high20 * 0.999 and high20 > 0:
        score += 1
        reasons.append(f"收盘逼近/突破 20 日高点 {high20:.2f}")
    if 0 < low20 and close < low20:
        score -= 2
        reasons.append(f"跌破 20 日低点 {low20:.2f}")

    score = max(-5, min(5, score))
    if score >= 3:
        bias = "偏多"
    elif score <= -3:
        bias = "偏空"
    else:
        bias = "震荡"
    confidence = min(85, 45 + abs(score) * 8)

    # ---- 明日支撑 / 阻力 ----
    supports = [x for x in (ma5, ma10, ma20, ma60, low20, boll_dn) if 0 < x < close]
    resistances = [x for x in (ma20, ma60, high20, boll_up, target) if x > close]
    support = max(supports) if supports else close * (1 - atr_pct / 100)
    resistance = min(resistances) if resistances else close * (1 + atr_pct / 100)

    # 回踩买区：支撑上方 1% 到下方 0.5%，别买在破位下跌里
    buy_low = _px(min(support * 0.995, close * 0.985), close)
    buy_high = _px(support * 1.01, close)
    # 低价品种（ETF）用三位小数，否则 0.33/0.34 全撞在一起
    p = lambda v: f"{v:.{3 if close < 2 else 2}f}"  # noqa: E731

    plan_lines: list[str] = []
    if bias == "偏多":
        if has_pos:
            plan_lines.append(f"持有为主：明天冲高到 {p(resistance)} 附近不追，"
                              f"回落不破 {p(support)} 就继续拿")
            plan_lines.append(f"若跌破 {p(support)} 且收在下方，减掉一半；跌破 {p(stop)} 全部离场")
        else:
            plan_lines.append(f"回踩 {p(buy_low)}~{p(buy_high)} 分批买（先半仓），跌破 {p(stop)} 止损")
            plan_lines.append(f"若直接放量突破 {p(resistance)}，追一档，目标 {p(target)}")
    elif bias == "偏空":
        if has_pos:
            plan_lines.append(f"反弹到 {p(resistance)} 附近先减仓（不要等回本）；跌破 {p(stop)} 清仓")
            plan_lines.append(f"明天若低开超过 1%，不要补仓摊成本，等站回 {p(support)} 再说")
        else:
            plan_lines.append(f"不接飞刀：等站回 {p(ma20)}（MA20）再看，或跌到 {p(boll_dn)} 附近出现缩量长下影")
    else:
        if has_pos:
            plan_lines.append(f"区间对待：{p(support)}~{p(resistance)}，靠近上沿减一点、靠近下沿加一点")
            plan_lines.append(f"止损位 {p(stop)} 不变，跌破就走")
        else:
            plan_lines.append(f"观察为主：突破 {p(resistance)} 或回踩 {p(buy_low)} 出现缩量再进")

    if amplitude >= 6:
        plan_lines.append(f"今天振幅 {amplitude:.1f}%，明天波动会放大，仓位别一次打满")

    # 明日动作：和今天的结论保持一致，避免「今天说减、明天说买」
    today_action = advice.get("action", "")
    if today_action in ("止损", "卖出"):
        action = "减仓" if has_pos else "观望"
    elif bias == "偏空" and has_pos:
        action = "减仓"
    elif bias == "偏多" and has_pos:
        action = "持有"
    elif bias == "偏多":
        action = "买入"
    else:
        action = "观望"

    return {
        "bias": bias,
        "score": score,
        "confidence": confidence,
        "action": action,
        "levels": {
            "support": _px(support, close),
            "resistance": _px(resistance, close),
            "buy_low": buy_low,
            "buy_high": buy_high,
            "add": _px(add, close) if add else 0.0,
            "stop": _px(stop, close) if stop else 0.0,
            "target": _px(target, close),
            "take": [_px(x, close) for x in take[:2]],
            "high20": _px(high20, close),
            "low20": _px(low20, close),
        },
        "plan": plan_lines,
        "reasons": reasons[:4],
        "pct_today": _r(pct, 2),
        "amplitude": _r(amplitude, 1),
        "decimals": 3 if close < 2 else 2,
    }
