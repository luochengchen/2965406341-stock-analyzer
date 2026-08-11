"""Stock Analyzer Web App — mobile-friendly Flask server."""
from __future__ import annotations

from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)


def _is_bullish(color: str) -> bool:
    """green or yellow = bullish signal."""
    return color in ("green", "yellow")


def _is_bearish(color: str) -> bool:
    """dim or red = bearish signal."""
    return color in ("dim", "red")


def _compute_advice(short_term: dict, long_term: dict, positions: dict,
                    has_position: bool, profit_pct: float) -> dict | None:
    """Generate trading recommendation based on analysis + position.

    Returns None if no position, otherwise {"action", "urgency", "reason"}.
    """
    if not has_position:
        return None

    short_color = short_term.get("color", "dim")
    long_color = long_term.get("color", "dim")
    short_bull = _is_bullish(short_color)
    long_bull = _is_bullish(long_color)
    both_bull = short_bull and long_bull
    both_bear = _is_bearish(short_color) and _is_bearish(long_color)

    # Check distance to stop-loss
    sl = positions.get("stop_loss", {})
    sl_price = sl.get("price", 0)
    current_price = float(short_term.get("price", 0) or 0)
    at_stop = sl_price > 0 and current_price > 0 and current_price <= sl_price

    # Check distance to nearest add-position level
    ap_list = positions.get("add_position", [])
    near_add = False
    add_price = 0
    if ap_list and current_price > 0:
        nearest = min(ap_list, key=lambda x: abs(x["price"] - current_price))
        add_price = nearest["price"]
        if add_price > 0:
            dist = abs(current_price - add_price) / add_price
            near_add = dist < 0.02

    # --- Decision tree ---

    # Stop-loss: heavy loss + bearish, or price below stop
    if profit_pct < -8 and both_bear:
        return {"action": "止损", "urgency": "高",
                "reason": f"亏损{abs(profit_pct):.1f}%且长短线均偏空，建议止损离场"}
    if at_stop:
        return {"action": "止损", "urgency": "高",
                "reason": f"现价已触及止损位{sl_price:.2f}，建议止损"}

    # Reduce: large profit + one signal bearish, or moderate loss + short bearish
    if profit_pct > 15 and not both_bull:
        return {"action": "减仓", "urgency": "中",
                "reason": f"浮盈{profit_pct:.1f}%较多，技术信号转弱，建议减仓锁定利润"}
    if profit_pct < -5 and _is_bearish(short_color):
        return {"action": "减仓", "urgency": "中",
                "reason": f"亏损{abs(profit_pct):.1f}%且短线偏空，建议减仓控制风险"}

    # Add: near add-point or all bullish with profit
    if near_add:
        return {"action": "加仓", "urgency": "高",
                "reason": f"现价接近加仓位{add_price:.2f}，回踩支撑可加仓"}
    if both_bull and profit_pct > 0:
        return {"action": "加仓", "urgency": "中",
                "reason": "短线多头+长线多头，浮盈中可顺势加仓"}

    # Hold: default
    return {"action": "持有", "urgency": "低",
            "reason": "信号不极端，维持现有仓位观察"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception:
        return "<h1>Stock Analyzer</h1><p>Template not found. API is available at /api/ping</p>"


@app.route("/api/ping")
def api_ping():
    return jsonify({"status": "ok", "msg": "server is running"})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "请输入股票代码或名称"}), 400

    try:
        from fetcher import resolve_stock_code, fetch_daily_kline, get_stock_info
        from indicators import calc_all
        from analyzer import ShortTermAnalyzer, LongTermAnalyzer
        from positions import PositionCalculator

        code, name = resolve_stock_code(query)
        df = fetch_daily_kline(code)
        df = calc_all(df)

        short = ShortTermAnalyzer(df, name, code).analyze()
        long_ = LongTermAnalyzer(df, name, code).analyze()
        pos = PositionCalculator(df, short["supports"], short["resistances"]).calculate_all()

        try:
            info = get_stock_info(code)
            pct = info.get("pct_change", 0)
        except Exception:
            pct = 0

        return jsonify({
            "name": name,
            "code": code,
            "price": short["price"],
            "pct_change": round(pct, 2),
            "short_term": {
                "verdict": short["verdict"],
                "total_score": short["total_score"],
                "scores": short["scores"],
                "details": short["details"],
                "color": short["color"],
            },
            "long_term": {
                "verdict": long_["verdict"],
                "total_score": long_["total_score"],
                "scores": long_["scores"],
                "details": long_["details"],
                "color": long_["color"],
            },
            "positions": {
                "stop_loss": pos["stop_loss"],
                "add_position": [
                    {"price": l["price"], "dist_pct": l["dist_pct"], "trigger": l["trigger"]}
                    for l in pos["add_position"][:2]
                ],
                "take_profit": [
                    {"price": l["price"], "dist_pct": l["dist_pct"], "trigger": l["trigger"]}
                    for l in pos["take_profit"][:2]
                ],
            },
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"分析失败: {e}"}), 500


# ---------------------------------------------------------------------------
# Watchlist (自选股) routes
# ---------------------------------------------------------------------------

@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_list():
    from portfolio import get_all_stocks
    stocks = get_all_stocks()
    return jsonify({"count": len(stocks), "stocks": stocks})


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    data = request.get_json()
    text = data.get("text", "").strip()
    code = data.get("code", "").strip()

    from portfolio import add_stock

    # Batch import: multi-line text
    if text and not code:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        added = 0
        for line in lines:
            # Take first whitespace-delimited token
            token = line.split()[0].strip()
            # Strip market prefixes
            for prefix in ("sh.", "sz.", "SH", "SZ"):
                if token.startswith(prefix):
                    token = token[len(prefix):]
                    break
            if token.isdigit() and len(token) == 6:
                if add_stock(token):
                    added += 1
        return jsonify({"ok": True, "added": added})

    # Single stock add
    if not code:
        return jsonify({"error": "请输入股票代码"}), 400

    try:
        from fetcher import resolve_stock_code
        resolved_code, resolved_name = resolve_stock_code(code)
    except Exception as e:
        return jsonify({"error": f"无法识别股票代码: {e}"}), 404

    ok = add_stock(resolved_code, resolved_name)
    if not ok:
        return jsonify({"error": "已在自选列表中"}), 409

    return jsonify({"ok": True, "code": resolved_code, "name": resolved_name})


@app.route("/api/watchlist/<code>", methods=["DELETE"])
def api_watchlist_delete(code):
    from portfolio import remove_stock
    ok = remove_stock(code)
    if not ok:
        return jsonify({"error": "自选股不存在"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Position (持仓) routes
# ---------------------------------------------------------------------------

@app.route("/api/position/<code>", methods=["PUT"])
def api_position_set(code):
    data = request.get_json()
    shares = int(data.get("shares", 0))
    cost = float(data.get("cost", 0))

    from portfolio import set_position
    ok = set_position(code, shares, cost)
    if not ok:
        return jsonify({"error": "请先将该股票加入自选"}), 404

    return jsonify({"ok": True, "code": code.zfill(6), "shares": shares, "cost": cost})


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

@app.route("/api/batch_analyze", methods=["POST"])
def api_batch_analyze():
    from portfolio import get_all_stocks

    stocks = get_all_stocks()
    if not stocks:
        return jsonify({"error": "自选股列表为空，请先添加"}), 400

    try:
        from fetcher import resolve_stock_code, fetch_daily_kline, get_stock_info
        from indicators import calc_all
        from analyzer import ShortTermAnalyzer, LongTermAnalyzer
        from positions import PositionCalculator
    except Exception as e:
        return jsonify({"error": f"导入模块失败: {e}"}), 500

    results = []
    for entry in stocks:
        stock_code = entry["code"]
        try:
            df = fetch_daily_kline(stock_code)
            df = calc_all(df)
            name = entry["name"] or stock_code

            short = ShortTermAnalyzer(df, name, stock_code).analyze()
            long_ = LongTermAnalyzer(df, name, stock_code).analyze()
            pos = PositionCalculator(df, short["supports"], short["resistances"]).calculate_all()

            try:
                info = get_stock_info(stock_code)
                pct = info.get("pct_change", 0)
            except Exception:
                pct = 0

            current_price = float(short.get("price", 0) or 0)
            has_pos = entry.get("has_position", False)
            profit_pct = 0.0
            profit_amt = 0.0
            market_value = 0.0
            if has_pos and current_price > 0:
                shares = entry.get("shares", 0)
                cost_basis = entry.get("cost", 0)
                if shares > 0 and cost_basis > 0:
                    profit_pct = (current_price - cost_basis) / cost_basis * 100
                    profit_amt = (current_price - cost_basis) * shares
                    market_value = current_price * shares

            advice = _compute_advice(short, long_, pos, has_pos, profit_pct)

            result = {
                "code": stock_code,
                "name": name,
                "price": short["price"],
                "pct_change": round(pct, 2),
                "has_position": has_pos,
                "position": {
                    "shares": entry.get("shares", 0),
                    "cost": entry.get("cost", 0),
                    "market_value": round(market_value, 2),
                    "profit_pct": round(profit_pct, 2),
                    "profit_amount": round(profit_amt, 2),
                } if has_pos else None,
                "short_term": {
                    "verdict": short["verdict"],
                    "total_score": short["total_score"],
                    "scores": short["scores"],
                    "details": short["details"],
                    "color": short["color"],
                },
                "long_term": {
                    "verdict": long_["verdict"],
                    "total_score": long_["total_score"],
                    "scores": long_["scores"],
                    "details": long_["details"],
                    "color": long_["color"],
                },
                "positions": {
                    "stop_loss": pos["stop_loss"],
                    "add_position": [
                        {"price": l["price"], "dist_pct": l["dist_pct"], "trigger": l["trigger"]}
                        for l in pos["add_position"][:2]
                    ],
                    "take_profit": [
                        {"price": l["price"], "dist_pct": l["dist_pct"], "trigger": l["trigger"]}
                        for l in pos["take_profit"][:2]
                    ],
                },
                "recommendation": advice,
            }
            results.append(result)
        except Exception as e:
            results.append({
                "code": stock_code,
                "name": entry.get("name", stock_code),
                "error": str(e),
            })

    return jsonify({
        "count": len(results),
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "results": results,
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
