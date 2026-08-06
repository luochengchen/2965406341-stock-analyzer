"""Stock Analyzer Web App — mobile-friendly Flask server."""
from __future__ import annotations
import sys
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Lazy import to catch startup errors
fetcher = None
indicators = None
analyzer = None
positions_module = None

def _lazy_import():
    global fetcher, indicators, analyzer, positions_module
    if fetcher is None:
        from fetcher import resolve_stock_code, fetch_daily_kline, get_stock_info
        from indicators import calc_all
        from analyzer import ShortTermAnalyzer, LongTermAnalyzer
        from positions import PositionCalculator
        import fetcher as _fetcher
        import indicators as _indicators
        import analyzer as _analyzer
        import positions as _positions
        fetcher = _fetcher
        indicators = _indicators
        analyzer = _analyzer
        positions_module = _positions


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ping")
def api_ping():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Analyze a stock by code or name. Returns JSON."""
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "请输入股票代码或名称"}), 400

    try:
        _lazy_import()
        code, name = fetcher.resolve_stock_code(query)
        df = fetcher.fetch_daily_kline(code)
        df = indicators.calc_all(df)

        short = analyzer.ShortTermAnalyzer(df, name, code).analyze()
        long_ = analyzer.LongTermAnalyzer(df, name, code).analyze()
        pos = positions_module.PositionCalculator(df, short["supports"], short["resistances"]).calculate_all()

        try:
            info = fetcher.get_stock_info(code)
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


@app.route("/api/search", methods=["POST"])
def api_search():
    """Search for stock by partial name."""
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify([])
    try:
        import baostock as bs
        bs.login()
        rs = bs.query_stock_basic(code_name=query)
        results = []
        while rs.next():
            row = rs.get_row_data()
            results.append({"code": row[0].replace("sh.", "").replace("sz.", ""), "name": row[1]})
        bs.logout()
        return jsonify(results[:10])
    except Exception:
        return jsonify([])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
