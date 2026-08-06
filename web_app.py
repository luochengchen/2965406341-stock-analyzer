"""Stock Analyzer Web App — mobile-friendly Flask server."""
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


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


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
