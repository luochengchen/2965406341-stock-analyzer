"""Report generator — verdict-first, split-panel layout."""
from __future__ import annotations
from datetime import datetime
import pandas as pd

W = 36  # Width of each side panel
SEP = "=" * 78


def generate_report(result: dict) -> str:
    lines = []

    # ===== VERDICT BOX (top, most important) =====
    short = result.get("short_term", {})
    long_ = result.get("long_term", {})
    positions = result.get("positions", {})

    s_color = short.get("color", "dim")
    l_color = long_.get("color", "dim")
    short_tag = _tag(short.get("verdict", ""), s_color)
    long_tag = _tag(long_.get("verdict", ""), l_color)

    lines.append(SEP)
    lines.append(f"  {result['name']} ({result['code']})  |  现价: {result['price']:.2f}")
    pct = result.get("pct_change", 0)
    sign = "+" if pct > 0 else ""
    pct_color = "G" if pct >= 0 else "R"
    lines.append(f"  涨跌: {sign}{pct:.2f}%  |  分析时间: {datetime.now().strftime('%m-%d %H:%M')}")
    lines.append(SEP)
    lines.append("")

    # Split verdict
    lines.append(f"  {'短线(1-2周)':<18} {'':>6} {'长线(3-12月)':<18}")
    lines.append(f"  {'─'*18} {'':>6} {'─'*18}")
    lines.append(f"  {_pad(short_tag, 20):<18} {'':>6} {_pad(long_tag, 20):<18}")
    lines.append("")

    # Key price levels
    sl = positions.get("stop_loss", {})
    ap = positions.get("add_position", [])
    tp = positions.get("take_profit", [])

    lines.append(f"  {'止损位':<8} {_fmt_price(sl):<16}  {'加仓位':<8} {_fmt_ap(ap):<18}  止盈位 {_fmt_tp(tp)}")
    lines.append("")
    lines.append(SEP)
    lines.append("")

    # ===== SIDE-BY-SIDE ANALYSIS =====
    # Build left and right columns
    left_lines = _build_short_panel(result)
    right_lines = _build_long_panel(result)

    # Pad to same height
    max_rows = max(len(left_lines), len(right_lines))
    while len(left_lines) < max_rows:
        left_lines.append(" " * W)
    while len(right_lines) < max_rows:
        right_lines.append(" " * W)

    # Column headers
    lines.append(f"  +{'─'* (W-1)}+     +{'─'* (W-1)}+")
    lines.append(f"  |{' 短线分析 (1-2周)':<{W}}|     |{' 长线分析 (3-12月)':<{W}}|")
    lines.append(f"  +{'─'* (W-1)}+     +{'─'* (W-1)}+")

    # Side by side rows
    for i in range(max_rows):
        left = left_lines[i] if i < len(left_lines) else ""
        right = right_lines[i] if i < len(right_lines) else ""
        lines.append(f"  |{_pad(left, W)}|     |{_pad(right, W)}|")

    lines.append(f"  +{'─'* (W-1)}+     +{'─'* (W-1)}+")

    return "\n".join(lines)


def _build_short_panel(result: dict) -> list[str]:
    """Build left panel: short-term analysis lines."""
    lines = []
    latest = result["latest_row"]
    details = result.get("short_term", {}).get("details", {})
    scores = result.get("short_term", {}).get("scores", {})

    # MA
    lines.append(" 均线位置:")
    for period in [5, 10, 20, 60]:
        ma = latest.get(f"MA{period}")
        if pd.notna(ma):
            arrow = ">" if latest["close"] > ma else "<"
            lines.append(f"   MA{period:<3} {ma:>8.2f} {arrow} {'支撑' if latest['close'] > ma else '压力'}")

    lines.append("")

    # Indicators
    dif = latest.get("DIF")
    dea = latest.get("DEA")
    bar = latest.get("MACD_BAR")
    if pd.notna(dif):
        prev_two = result.get("short_term", {})
        golden = "金叉(看涨)" if bar > 0 else "死叉(看跌)" if bar < 0 else ""
        lines.append(f" MACD: DIF={dif:.3f} DEA={dea:.3f}")
        lines.append(f"   BAR={bar:.3f} {golden}")
        lines.append(f"   -> DIF{'上穿' if dif > dea else '下穿'}DEA 短期动能{'偏多' if dif > dea else '偏空'}")

    k = latest.get("K")
    d = latest.get("D")
    j = latest.get("J")
    if pd.notna(k):
        state = "超买区(短期回调风险)" if j > 80 else ("超卖区(短期反弹机会)" if j < 20 else "中性区")
        lines.append(f" KDJ: K={k:.1f} D={d:.1f} J={j:.1f}")
        lines.append(f"   -> J值处于{state}")

    rsi14 = latest.get("RSI14")
    if pd.notna(rsi14):
        if rsi14 > 70:
            rsi_state = "超买(卖压积累, 不宜追高)"
        elif rsi14 < 30:
            rsi_state = "超卖(买入力量积蓄, 可关注反弹)"
        elif rsi14 > 50:
            rsi_state = "偏强(多头占优)"
        else:
            rsi_state = "偏弱(空头占优)"
        lines.append(f" RSI14: {rsi14:.1f} -> {rsi_state}")

    boll_up = latest.get("BOLL_UP")
    boll_mid = latest.get("BOLL_MID")
    boll_dn = latest.get("BOLL_DN")
    if pd.notna(boll_mid):
        lines.append(f" 布林: 上{boll_up:.2f} 中{boll_mid:.2f} 下{boll_dn:.2f}")
        if latest["close"] >= boll_up:
            lines.append("   -> 价格突破上轨, 短线超买, 注意回调")
        elif latest["close"] <= boll_dn:
            lines.append("   -> 价格跌破下轨, 短线超卖, 可能反弹")
        elif latest["close"] > boll_mid:
            lines.append("   -> 价格在中轨上方, 短期趋势偏强")
        else:
            lines.append("   -> 价格在中轨下方, 短期趋势偏弱")

    # Volume
    vol_ratio = latest.get("VOL_RATIO")
    if pd.notna(vol_ratio):
        lines.append(f" 量比: {vol_ratio:.2f}x (今日/5日均量)")
        if vol_ratio > 1.5:
            lines.append("   -> 显著放量, 资金关注度高")
        elif vol_ratio < 0.6:
            lines.append("   -> 严重缩量, 交投清淡")
        elif vol_ratio > 1:
            lines.append("   -> 温和放量, 正常交投")
        else:
            lines.append("   -> 缩量, 资金参与度下降")

    # Scores
    lines.append("")
    lines.append(" 评分明细:")
    for dim, score in scores.items():
        s_str = f"+{score:.1f}" if score > 0 else f"{score:.1f}"
        lines.append(f"   {dim}: {s_str}")
    total = result.get("short_term", {}).get("total_score", 0)
    t_str = f"+{total:.1f}" if total > 0 else f"{total:.1f}"
    lines.append(f"   {'─'*14}")
    lines.append(f"   短线总分: {t_str}")

    return lines


def _build_long_panel(result: dict) -> list[str]:
    """Build right panel: long-term analysis lines."""
    lines = []
    latest = result["latest_row"]
    details = result.get("long_term", {}).get("details", {})
    scores = result.get("long_term", {}).get("scores", {})

    # MA250 position
    ma250 = latest.get("MA250")
    if pd.notna(ma250):
        dist = (latest["close"] - ma250) / ma250 * 100
        arrow = ">" if latest["close"] > ma250 else "<"
        lines.append(" 年线(MA250)位置:")
        lines.append(f"   MA250={ma250:.2f} 现价={latest['close']:.2f}")
        lines.append(f"   偏离{dist:+.1f}% (多头{'强势' if dist > 10 else '区域' if dist > 0 else '弱势'})")

    # Long MAs
    for period in [60, 120, 250]:
        ma = latest.get(f"MA{period}")
        if pd.notna(ma):
            arrow = ">" if latest["close"] > ma else "<"
            lines.append(f"   MA{period:<3} {ma:>8.2f} {arrow} {'支' if latest['close'] > ma else '压'}")

    lines.append("")

    # ADX
    adx = latest.get("ADX")
    plus_di = latest.get("PLUS_DI")
    minus_di = latest.get("MINUS_DI")
    if pd.notna(adx):
        if adx > 40:
            adx_state = "极强趋势, 顺势持仓不猜顶底"
        elif adx > 25:
            adx_state = "趋势明确, 可沿趋势方向操作"
        elif adx > 15:
            adx_state = "趋势较弱, 价格可能震荡"
        else:
            adx_state = "无趋势(盘整), 适合观望或做波段"
        lines.append(f" ADX(趋势强度): {adx:.1f}")
        lines.append(f"   +DI={plus_di:.1f} -DI={minus_di:.1f}")
        lines.append(f"   -> {adx_state}")
        if pd.notna(plus_di) and pd.notna(minus_di):
            if plus_di > minus_di:
                lines.append("   -> 多头力量强于空头, 长期看涨")
            else:
                lines.append("   -> 空头力量强于多头, 长期看跌")

    # ATR
    atr = latest.get("ATR")
    atr_pct = latest.get("ATR_PCT")
    if pd.notna(atr):
        lines.append(f" ATR(日均波幅): {atr:.2f} ({atr_pct:.1f}%)")
        if atr_pct < 2:
            lines.append("   -> 低波动股票, 适合稳健持仓")
        elif atr_pct < 4:
            lines.append("   -> 正常波动, 可承受")
        else:
            lines.append("   -> 高波动, 长线需承受较大回撤")

    # 52-week position
    high_52w = latest["high"] if "high" in latest.index else 0
    low_52w = latest["low"] if "low" in latest.index else 0
    # Find 52-week extremes from the dataframe
    if hasattr(result.get("latest_row", {}), "name"):
        pass

    lines.append("")

    # Scores
    lines.append(" 评分明细:")
    for dim, score in scores.items():
        s_str = f"+{score:.1f}" if score > 0 else f"{score:.1f}"
        lines.append(f"   {dim}: {s_str}")
    total = result.get("long_term", {}).get("total_score", 0)
    t_str = f"+{total:.1f}" if total > 0 else f"{total:.1f}"
    lines.append(f"   {'─'*14}")
    lines.append(f"   长线总分: {t_str}")

    return lines


# ===== HELPERS =====

def _tag(verdict: str, color: str) -> str:
    """Extract clean tag from verdict string."""
    if "多" in verdict and "空" not in verdict:
        return verdict.replace("[多]", "[买入]").replace("[长多]", "[持有]")[:18]
    elif "空" in verdict:
        return verdict[:18]
    elif "观" in verdict:
        return verdict[:18]
    return verdict[:18]


def _pad(s: str, width: int) -> str:
    """Pad string to exact width, handling CJK characters."""
    # Count: CJK chars = 2 width, ASCII = 1
    actual = 0
    result = []
    for ch in s:
        if '一' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯':
            if actual + 2 <= width:
                result.append(ch)
                actual += 2
        else:
            if actual + 1 <= width:
                result.append(ch)
                actual += 1
    return ''.join(result) + ' ' * (width - actual)


def _fmt_price(sl: dict) -> str:
    if not sl or not sl.get("price"):
        return "暂无数据"
    return f"{sl['price']:.2f} (-{sl.get('dist_pct', 0):.1f}%)"


def _fmt_ap(levels: list) -> str:
    if not levels:
        return "暂无数据"
    return ", ".join(f"{l['price']:.2f}" for l in levels[:2])


def _fmt_tp(levels: list) -> str:
    if not levels:
        return "暂无数据"
    return ", ".join(f"{l['price']:.2f}" for l in levels[:2])
