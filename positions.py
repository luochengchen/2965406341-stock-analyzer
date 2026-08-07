"""Position management: stop-loss, add-position, take-profit levels."""
from __future__ import annotations
import pandas as pd
import numpy as np


class PositionCalculator:
    """Calculate key trading levels based on technical analysis."""

    def __init__(self, df: pd.DataFrame, supports: list[float], resistances: list[float]):
        self.df = df
        self.latest = df.iloc[-1]
        self.close = self.latest["close"]
        self.atr = self.latest.get("ATR", 0)
        self.atr_pct = self.latest.get("ATR_PCT", 3)
        self.supports = supports
        self.resistances = resistances

    def calc_stop_loss(self) -> dict:
        """Calculate stop-loss level (maximum protection).

        Uses the HIGHEST of:
        - MA60 (trend stop)
        - Recent swing low (structure stop)
        - ATR * 2 (volatility stop)

        Returns dict with price, distance%, and rationale.
        """
        candidates = []

        # MA60 stop
        ma60 = self.latest.get("MA60")
        if pd.notna(ma60) and ma60 < self.close:
            candidates.append((ma60, f"MA60均线止损 ({ma60:.2f})"))

        # Recent swing low (from last 20 bars)
        recent_low = self.df["low"].tail(20).min()
        if recent_low < self.close:
            candidates.append((recent_low, f"近期低点止损 ({recent_low:.2f})"))

        # ATR * 2 volatility stop
        if pd.notna(self.atr) and self.atr > 0:
            atr_stop = self.close - 2 * self.atr
            candidates.append((atr_stop, f"ATR波动止损 ({atr_stop:.2f})"))

        if not candidates:
            # Fallback: 5% below current price
            fallback = self.close * 0.95
            candidates.append((fallback, f"固定5%止损 ({fallback:.2f})"))

        # Pick the HIGHEST stop (tightest protection)
        best = max(candidates, key=lambda x: x[0])
        dist_pct = (self.close - best[0]) / self.close * 100

        return {
            "price": round(best[0], 2),
            "dist_pct": round(dist_pct, 2),
            "method": best[1],
            "all_candidates": [{"price": round(c[0], 2), "method": c[1]} for c in sorted(candidates, key=lambda x: x[0], reverse=True)],
        }

    def calc_add_position(self) -> list[dict]:
        """Calculate add-position (加仓) levels.

        Trigger conditions where it may be favorable to add:
        - Price pulls back to MA20/MA60
        - Price pulls back to BOLL middle band
        - Price approaches key support level
        """
        levels = []

        # MA20 pullback
        ma20 = self.latest.get("MA20")
        if pd.notna(ma20) and ma20 < self.close:
            dist = (self.close - ma20) / self.close * 100
            levels.append({
                "price": round(ma20, 2),
                "dist_pct": round(dist, 2),
                "trigger": f"回踩MA20均线 ({ma20:.2f})",
                "priority": "高",
            })

        # MA60 pullback
        ma60 = self.latest.get("MA60")
        if pd.notna(ma60) and ma60 < self.close:
            dist = (self.close - ma60) / self.close * 100
            levels.append({
                "price": round(ma60, 2),
                "dist_pct": round(dist, 2),
                "trigger": f"回踩MA60均线 ({ma60:.2f})",
                "priority": "中",
            })

        # BOLL middle band
        boll_mid = self.latest.get("BOLL_MID")
        if pd.notna(boll_mid) and boll_mid < self.close:
            dist = (self.close - boll_mid) / self.close * 100
            levels.append({
                "price": round(boll_mid, 2),
                "dist_pct": round(dist, 2),
                "trigger": f"回踩布林中轨 ({boll_mid:.2f})",
                "priority": "高",
            })

        # Support levels
        for s in self.supports:
            if s < self.close:
                dist = (self.close - s) / self.close * 100
                levels.append({
                    "price": round(s, 2),
                    "dist_pct": round(dist, 2),
                    "trigger": f"触及支撑位 ({s:.2f})",
                    "priority": "中",
                })

        # Sort by distance (closest first)
        levels.sort(key=lambda x: x["dist_pct"])
        return levels[:4]

    def calc_take_profit(self) -> list[dict]:
        """Calculate take-profit (止盈) levels.

        Where to consider taking profits:
        - BOLL upper band
        - Recent swing high resistance
        - ATR * 3 extension from current
        """
        levels = []

        # BOLL upper band
        boll_up = self.latest.get("BOLL_UP")
        if pd.notna(boll_up) and boll_up > self.close:
            dist = (boll_up - self.close) / self.close * 100
            levels.append({
                "price": round(boll_up, 2),
                "dist_pct": round(dist, 2),
                "trigger": f"布林上轨 ({boll_up:.2f})",
                "priority": "高",
            })

        # Resistance levels
        for r in self.resistances:
            if r > self.close:
                dist = (r - self.close) / self.close * 100
                levels.append({
                    "price": round(r, 2),
                    "dist_pct": round(dist, 2),
                    "trigger": f"前期压力位 ({r:.2f})",
                    "priority": "高" if dist < 5 else "中",
                })

        # ATR-based extension
        if pd.notna(self.atr) and self.atr > 0:
            atr_tp = self.close + 3 * self.atr
            dist = (atr_tp - self.close) / self.close * 100
            levels.append({
                "price": round(atr_tp, 2),
                "dist_pct": round(dist, 2),
                "trigger": f"ATR通道上沿 ({atr_tp:.2f})",
                "priority": "低",
            })

        # If no levels found, suggest 10% upside
        if not levels:
            tp = self.close * 1.1
            levels.append({
                "price": round(tp, 2),
                "dist_pct": 10.0,
                "trigger": f"固定10%止盈 ({tp:.2f})",
                "priority": "低",
            })

        levels.sort(key=lambda x: x["dist_pct"])
        return levels[:4]

    def calc_trailing_stop(self, entry_price: float = None) -> dict:
        """Calculate trailing stop for existing positions.

        If no entry_price, assumes current price as entry.
        Uses ATR * 1.5 as trailing distance.
        """
        if entry_price is None:
            entry_price = self.close

        trail_dist = max(self.atr * 1.5, self.close * 0.03) if pd.notna(self.atr) and self.atr > 0 else self.close * 0.03
        trail_price = self.close - trail_dist

        return {
            "entry": round(entry_price, 2),
            "current": round(self.close, 2),
            "trail_price": round(trail_price, 2),
            "trail_dist_pct": round(trail_dist / self.close * 100, 2),
            "profit_pct": round((self.close - entry_price) / entry_price * 100, 2),
        }

    def calculate_all(self) -> dict:
        """Calculate all position levels."""
        return {
            "stop_loss": self.calc_stop_loss(),
            "add_position": self.calc_add_position(),
            "take_profit": self.calc_take_profit(),
        }
