"""Comprehensive stock analysis and entry recommendation."""
import pandas as pd
import numpy as np
from indicators import find_support_resistance


class ShortTermAnalyzer:
    """Short-term (1-2 week) analysis for entry timing."""

    def __init__(self, df: pd.DataFrame, name: str, code: str):
        self.df = df
        self.name = name
        self.code = code
        self.latest = df.iloc[-1]
        self.prev = df.iloc[-2] if len(df) > 1 else self.latest
        self.scores = {}
        self.details = {}

    def analyze(self) -> dict:
        """Run full analysis and return results."""
        self._analyze_ma_trend()
        self._analyze_macd()
        self._analyze_kdj()
        self._analyze_rsi()
        self._analyze_volume_price()
        self._analyze_bollinger()
        self._analyze_support_distance()

        total = sum(self.scores.values())
        max_score = 7  # 7 dimensions, +1 each

        # Normalize to -5 ~ +5 scale
        normalized = total

        if normalized >= 3:
            verdict = "[多] 偏多 -- 可考虑入场"
            color = "green"
        elif normalized >= 1:
            verdict = "[中] 中性偏多 -- 谨慎入场"
            color = "yellow"
        elif normalized >= -1:
            verdict = "[观] 观望为主 -- 信号不明确"
            color = "dim"
        else:
            verdict = "[空] 偏空 -- 不建议入场"
            color = "red"

        return {
            "name": self.name,
            "code": self.code,
            "price": self.latest["close"],
            "scores": self.scores,
            "details": self.details,
            "total_score": normalized,
            "max_score": max_score,
            "verdict": verdict,
            "color": color,
            "supports": self._supports,
            "resistances": self._resistances,
        }

    def _analyze_ma_trend(self):
        ma5 = self.latest.get("MA5")
        ma10 = self.latest.get("MA10")
        ma20 = self.latest.get("MA20")
        ma60 = self.latest.get("MA60")
        close = self.latest["close"]

        if pd.isna(ma60):
            self.scores["均线排列"] = 0
            self.details["均线排列"] = "数据不足，需至少60日K线"
            return

        if ma5 > ma10 > ma20 > ma60:
            self.scores["均线排列"] = 1
            self.details["均线排列"] = "多头排列(MA5>MA10>MA20>MA60)短期强势，短线顺势做多"
        elif ma5 < ma10 < ma20 < ma60:
            self.scores["均线排列"] = -1
            self.details["均线排列"] = "空头排列(MA5<MA10<MA20<MA60)均线全面压制，不宜做多"
        elif close > ma60:
            self.scores["均线排列"] = 0.5
            self.details["均线排列"] = "价格站上MA60中期均线，趋势偏多但未完全确认"
        else:
            self.scores["均线排列"] = -0.5
            self.details["均线排列"] = "价格在MA60下方运行，中期趋势走弱，等待站回MA60再考虑"

    def _analyze_macd(self):
        """Score based on MACD."""
        dif = self.latest.get("DIF")
        dea = self.latest.get("DEA")
        bar = self.latest.get("MACD_BAR")
        prev_bar = self.prev.get("MACD_BAR")

        if pd.isna(dif) or pd.isna(dea):
            self.scores["MACD"] = 0
            self.details["MACD"] = "数据不足"
            return

        score = 0
        signals = []

        if dif > dea:
            score += 0.5
            signals.append("DIF在DEA上方(短期动能向上)")
        else:
            score -= 0.5
            signals.append("DIF在DEA下方(短期动能向下)")

        if dif > 0:
            score += 0.25
            signals.append("DIF>0处于零轴上方(多头市场)")
        else:
            score -= 0.25
            signals.append("DIF<0处于零轴下方(空头市场)")

        if pd.notna(prev_bar) and bar > 0 > prev_bar:
            score += 0.5
            signals.append("红柱刚出现(DIF上穿DEA金叉确认)可用加仓")

        if pd.notna(prev_bar) and bar < 0 < prev_bar:
            score -= 0.5
            signals.append("绿柱刚出现(DIF下穿DEA死叉)短线应减仓或离场")

        self.scores["MACD"] = round(score, 2)
        self.details["MACD"] = "；".join(signals)

    def _analyze_kdj(self):
        """Score based on KDJ."""
        k = self.latest.get("K")
        d = self.latest.get("D")
        j = self.latest.get("J")
        prev_k = self.prev.get("K")
        prev_d = self.prev.get("D")

        if pd.isna(j):
            self.scores["KDJ"] = 0
            self.details["KDJ"] = "数据不足"
            return

        score = 0
        signals = []

        if j < 20:
            score += 1
            signals.append(f"J={j:.1f}超卖区，抛压衰竭可博短线反弹")
        elif j > 80:
            score -= 1
            signals.append(f"J={j:.1f}超买区，获利盘堆积小心回落")
        elif 40 <= j <= 60:
            signals.append(f"J={j:.1f}中性区，无明显超买超卖")

        if pd.notna(prev_k) and pd.notna(prev_d):
            if k > d and prev_k <= prev_d:
                score += 0.5
                signals.append("K线刚上穿D线(金叉)，短线看涨确认")
            elif k < d and prev_k >= prev_d:
                score -= 0.5
                signals.append("K线刚下穿D线(死叉)，短线卖出信号")

        self.scores["KDJ"] = round(score, 2)
        self.details["KDJ"] = "；".join(signals)

    def _analyze_rsi(self):
        """Score based on RSI14."""
        rsi = self.latest.get("RSI14")

        if pd.isna(rsi):
            self.scores["RSI"] = 0
            self.details["RSI"] = "数据不足"
            return

        if rsi < 30:
            self.scores["RSI"] = 1
            self.details["RSI"] = f"RSI14={rsi:.1f}深度超卖，卖压衰竭，短线反弹概率较高"
        elif rsi > 70:
            self.scores["RSI"] = -1
            self.details["RSI"] = f"RSI14={rsi:.1f}超买过热，追高风险大，等回调再入"
        elif 45 <= rsi <= 55:
            self.scores["RSI"] = 0
            self.details["RSI"] = f"RSI14={rsi:.1f}多空平衡，无明确方向"
        elif 55 < rsi <= 70:
            self.scores["RSI"] = 0.5
            self.details["RSI"] = f"RSI14={rsi:.1f}偏强但未过热，多头控盘"
        else:
            self.scores["RSI"] = -0.5
            self.details["RSI"] = f"RSI14={rsi:.1f}偏弱，空头力量占优"

    def _analyze_volume_price(self):
        """Score based on volume-price relationship."""
        close = self.latest["close"]
        prev_close = self.prev["close"]
        vol = self.latest["volume"]
        vol_ma5 = self.latest.get("VOL_MA5")

        if pd.isna(vol_ma5):
            self.scores["量价关系"] = 0
            self.details["量价关系"] = "数据不足"
            return

        vol_ratio = vol / vol_ma5 if vol_ma5 > 0 else 1
        price_chg = (close - prev_close) / prev_close * 100

        score = 0
        signals = [f"量比={vol_ratio:.2f}"]

        if price_chg > 0 and vol_ratio > 1.2:
            score = 1
            signals.append("价涨量增，主力真金白银买入，上涨有支撑")
        elif price_chg > 0 and vol_ratio < 0.8:
            score = -0.5
            signals.append("价涨但量缩，上涨无力，提防诱多出货")
        elif price_chg < 0 and vol_ratio > 1.2:
            score = -1
            signals.append("价跌量增放量下跌，大资金在出逃，不宜接刀")
        elif price_chg < 0 and vol_ratio < 0.8:
            score = 0.5
            signals.append("价跌但缩量，抛压在减弱，恐慌盘已释放")
        elif abs(price_chg) < 0.5 and vol_ratio < 0.6:
            score = 0
            signals.append("缩量横盘等待方向选择，暂不操作")
        else:
            signals.append("量价配合正常，无明显背离")

        self.scores["量价关系"] = score
        self.details["量价关系"] = "；".join(signals)

    def _analyze_bollinger(self):
        """Score based on Bollinger Band position."""
        close = self.latest["close"]
        mid = self.latest.get("BOLL_MID")
        up = self.latest.get("BOLL_UP")
        dn = self.latest.get("BOLL_DN")

        if pd.isna(mid):
            self.scores["布林带"] = 0
            self.details["布林带"] = "数据不足"
            return

        if close >= up:
            self.scores["布林带"] = -1
            self.details["布林带"] = "突破布林上轨，短期超买，高位不追等回调"
        elif close <= dn:
            self.scores["布林带"] = 1
            self.details["布林带"] = "跌破布林下轨，短期超卖，恐慌后可关注反弹"
        elif close > mid:
            self.scores["布林带"] = 0.5
            self.details["布林带"] = "价格在中轨上方，短期处于上升通道"
        else:
            self.scores["布林带"] = -0.5
            self.details["布林带"] = "价格在中轨下方，短期处于下降通道"

    def _analyze_support_distance(self):
        """Score based on distance to nearest support/resistance."""
        close = self.latest["close"]
        self._supports, self._resistances = find_support_resistance(self.df)

        if not self._supports or not self._resistances:
            self.scores["支撑压力"] = 0
            self.details["支撑压力"] = "无明确支撑/压力位"
            return

        nearest_support = min(self._supports, key=lambda s: close - s if close > s else 9999, default=0)
        nearest_resistance = min(self._resistances, key=lambda r: r - close if r > close else 9999, default=0)

        dist_to_support = (close - nearest_support) / close * 100 if nearest_support else 999
        dist_to_resistance = (nearest_resistance - close) / close * 100 if nearest_resistance else 999

        # Closer to support = more attractive entry
        if dist_to_support < 3:
            self.scores["支撑压力"] = 1
            self.details["支撑压力"] = f"距下方支撑{nearest_support:.2f}仅{dist_to_support:.1f}%，下跌空间有限风险可控"
        elif dist_to_resistance < 2:
            self.scores["支撑压力"] = -1
            self.details["支撑压力"] = f"紧贴上方压力{nearest_resistance:.2f}仅{dist_to_resistance:.1f}%，上涨空间受阻不宜追"
        elif dist_to_support < dist_to_resistance:
            self.scores["支撑压力"] = 0.5
            self.details["支撑压力"] = "距支撑比距压力近，盈亏比尚可"
        else:
            self.scores["支撑压力"] = -0.5
            self.details["支撑压力"] = "距压力比距支撑近，上涨空间小于下跌空间"


# Backward compatibility alias
StockAnalyzer = ShortTermAnalyzer


class LongTermAnalyzer:
    """Long-term (3-12 month) analysis for position/holding decisions."""

    def __init__(self, df: pd.DataFrame, name: str, code: str):
        self.df = df
        self.name = name
        self.code = code
        self.latest = df.iloc[-1]
        self.scores = {}
        self.details = {}

    def analyze(self) -> dict:
        """Run long-term analysis."""
        self._analyze_ma250_position()
        self._analyze_adx_trend()
        self._analyze_volatility_risk()
        self._analyze_long_ma_alignment()
        self._analyze_52week_position()
        self._analyze_avg_volume_trend()

        total = sum(self.scores.values())

        if total >= 3:
            verdict = "[长多] 适合长期持有 -- 趋势明确，可分批建仓"
            color = "green"
        elif total >= 1:
            verdict = "[长中] 可小仓位建仓观察 -- 趋势偏多但需确认"
            color = "yellow"
        elif total >= -1:
            verdict = "[长观] 观望等待 -- 信号不明确，等趋势明朗"
            color = "dim"
        else:
            verdict = "[长空] 不建议长线持有 -- 趋势偏弱，风险大于机会"
            color = "red"

        return {
            "scores": self.scores,
            "details": self.details,
            "total_score": total,
            "max_score": 6,
            "verdict": verdict,
            "color": color,
        }

    def _analyze_ma250_position(self):
        """Score based on position relative to MA250 (年线)."""
        ma250 = self.latest.get("MA250")
        close = self.latest["close"]

        if pd.isna(ma250):
            self.scores["年线位置"] = 0
            self.details["年线位置"] = "数据不足(需250日K线)"
            return

        dist = (close - ma250) / ma250 * 100

        if dist > 15:
            self.scores["年线位置"] = 1.5
            self.details["年线位置"] = f"高出年线{dist:.1f}%长线强势，处于牛市通道"
        elif dist > 5:
            self.scores["年线位置"] = 1
            self.details["年线位置"] = f"高出年线{dist:.1f}%趋势向好，长期持仓安全边际够"
        elif dist > 0:
            self.scores["年线位置"] = 0.5
            self.details["年线位置"] = f"略高于年线{dist:.1f}%刚站稳年线，需确认不跌破"
        elif dist > -5:
            self.scores["年线位置"] = -0.5
            self.details["年线位置"] = f"在年线下方{dist:.1f}%弱势震荡，年线形成压制"
        elif dist > -15:
            self.scores["年线位置"] = -1
            self.details["年线位置"] = f"低于年线{abs(dist):.1f}%趋势转弱，长线持仓应考虑减仓"
        else:
            self.scores["年线位置"] = -1.5
            self.details["年线位置"] = f"深跌年线下方{abs(dist):.1f}%处于熊市，不适合长线持有"

    def _analyze_adx_trend(self):
        """Score based on ADX trend strength."""
        adx = self.latest.get("ADX")
        plus_di = self.latest.get("PLUS_DI")
        minus_di = self.latest.get("MINUS_DI")

        if pd.isna(adx):
            self.scores["趋势强度"] = 0
            self.details["趋势强度"] = "数据不足"
            return

        if adx > 40:
            if plus_di > minus_di:
                self.scores["趋势强度"] = 1.5
                self.details["趋势强度"] = f"ADX={adx:.1f}趋势极强且+DI>-DI，坚定持仓不轻易下车"
            else:
                self.scores["趋势强度"] = -1
                self.details["趋势强度"] = f"ADX={adx:.1f}极强下跌趋势，不要逆势抄底"
        elif adx > 25:
            if plus_di > minus_di:
                self.scores["趋势强度"] = 1
                self.details["趋势强度"] = f"ADX={adx:.1f}趋势明确向上，回调即加仓机会"
            else:
                self.scores["趋势强度"] = -0.5
                self.details["趋势强度"] = f"ADX={adx:.1f}趋势明确向下，反弹应减仓"
        elif adx > 15:
            self.scores["趋势强度"] = 0
            self.details["趋势强度"] = f"ADX={adx:.1f}无明确趋势，价格在区间震荡"
        else:
            if plus_di > minus_di:
                self.scores["趋势强度"] = 0.5
                self.details["趋势强度"] = f"ADX={adx:.1f}低波动横盘，偏多盘整"
            else:
                self.scores["趋势强度"] = -0.5
                self.details["趋势强度"] = f"ADX={adx:.1f}低波动横盘，偏空盘整"

    def _analyze_volatility_risk(self):
        """Score based on ATR volatility risk."""
        atr_pct = self.latest.get("ATR_PCT")

        if pd.isna(atr_pct):
            self.scores["波动风险"] = 0
            self.details["波动风险"] = "数据不足"
            return

        if atr_pct < 2:
            self.scores["波动风险"] = 1
            self.details["波动风险"] = f"日波幅{atr_pct:.1f}%波动小，适合长期稳健持仓"
        elif atr_pct < 3:
            self.scores["波动风险"] = 0.5
            self.details["波动风险"] = f"日波幅{atr_pct:.1f}%正常范围，长线持有无压力"
        elif atr_pct < 5:
            self.scores["波动风险"] = -0.5
            self.details["波动风险"] = f"日波幅{atr_pct:.1f}%波动偏大，持股体验差需强心脏"
        else:
            self.scores["波动风险"] = -1
            self.details["波动风险"] = f"日波幅{atr_pct:.1f}%激烈波动，不适合重仓长持"

    def _analyze_long_ma_alignment(self):
        ma60 = self.latest.get("MA60")
        ma120 = self.latest.get("MA120")
        ma250 = self.latest.get("MA250")

        if pd.isna(ma250):
            self.scores["长线均线"] = 0
            self.details["长线均线"] = "数据不足，需至少250日数据"
            return

        if pd.notna(ma120) and ma60 > ma120 > ma250:
            self.scores["长线均线"] = 1.5
            self.details["长线均线"] = "长线多头排列(MA60>120>250)长线牛股形态"
        elif pd.notna(ma120) and ma60 < ma120 < ma250:
            self.scores["长线均线"] = -1.5
            self.details["长线均线"] = "长线空头排列(MA60<120<250)长期熊股远离"
        elif pd.notna(ma120) and ma60 > ma120:
            self.scores["长线均线"] = 0.5
            self.details["长线均线"] = "中期向好(MA60>MA120)但年线未确认，趋势在修复中"
        else:
            self.scores["长线均线"] = -0.5
            self.details["长线均线"] = "中期走弱(MA60<MA120)长线需要更多时间确认筑底"

    def _analyze_52week_position(self):
        """Score based on position relative to 52-week high/low."""
        high_52w = self.df["high"].tail(250).max()
        low_52w = self.df["low"].tail(250).min()
        close = self.latest["close"]

        if pd.isna(high_52w) or pd.isna(low_52w) or high_52w == low_52w:
            self.scores["历史位置"] = 0
            self.details["历史位置"] = "数据不足"
            return

        pct_from_low = (close - low_52w) / low_52w * 100
        pct_from_high = (high_52w - close) / high_52w * 100

        if pct_from_low < 15:
            self.scores["历史位置"] = 1.5
            self.details["历史位置"] = f"距年内最低仅{pct_from_low:.1f}%处于低位，下跌空间有限"
        elif pct_from_low < 30:
            self.scores["历史位置"] = 0.5
            self.details["历史位置"] = f"距年内低点{pct_from_low:.1f}%位置偏低，有一定安全边际"
        elif pct_from_high < 10:
            self.scores["历史位置"] = -1
            self.details["历史位置"] = f"距年内最高仅{pct_from_high:.1f}%高位接盘风险大，等回调再入"
        elif pct_from_high < 20:
            self.scores["历史位置"] = -0.5
            self.details["历史位置"] = f"距年内高点{pct_from_high:.1f}%位置偏高，追高需谨慎"
        else:
            self.scores["历史位置"] = 0
            self.details["历史位置"] = "处于年内中间位置，不上不下方向待定"

    def _analyze_avg_volume_trend(self):
        """Score based on long-term volume trend."""
        if len(self.df) < 60:
            self.scores["量能趋势"] = 0
            self.details["量能趋势"] = "数据不足"
            return

        vol_20 = self.df["volume"].tail(20).mean()
        vol_60 = self.df["volume"].tail(60).mean()

        if vol_60 == 0:
            self.scores["量能趋势"] = 0
            self.details["量能趋势"] = "数据异常"
            return

        ratio = vol_20 / vol_60

        if ratio > 1.3:
            self.scores["量能趋势"] = 1
            self.details["量能趋势"] = f"近20日量是60日的{ratio:.1f}倍显著放量，资金在流入"
        elif ratio > 1.0:
            self.scores["量能趋势"] = 0.5
            self.details["量能趋势"] = f"近20日量是60日的{ratio:.1f}倍温和放量，交投渐活跃"
        elif ratio > 0.7:
            self.scores["量能趋势"] = 0
            self.details["量能趋势"] = "量能正常"
        else:
            self.scores["量能趋势"] = -0.5
            self.details["量能趋势"] = f"近20日量是60日的{ratio:.1f}倍持续缩量，资金关注度下降"
