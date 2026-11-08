"""Stock Analyzer Web App — mobile-friendly Flask server."""
from __future__ import annotations

from codes import norm_code

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

        # 大师视角直接并进搜索结果：同一份日线，只多算几毫秒
        try:
            from masters import analyze as masters_analyze
            masters = masters_analyze(df, name, code)
        except Exception as e:
            masters = {"error": f"大师分析失败: {e}"}

        return jsonify({
            "name": name,
            "code": code,
            "price": short["price"],
            "pct_change": round(pct, 2),
            "masters": masters,
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

    from fetcher import BaostockError
    from portfolio import add_stock

    # Batch import: multi-line text, each line is a code or a name
    if text and not code:
        from fetcher import resolve_stock_code

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        added, skipped, failed = 0, 0, []
        for line in lines:
            token = line.split()[0].strip()
            # Strip market prefixes like sh.600519 / sz000001
            for prefix in ("sh.", "sz.", "bj.", "SH.", "SZ.", "sh", "sz", "bj", "SH", "SZ", "BJ"):
                if token.startswith(prefix) and token != prefix:
                    token = token[len(prefix):]
                    break
            try:
                resolved_code, resolved_name = resolve_stock_code(token)
            except BaostockError as e:
                # 连接层故障：整批都别继续了，让用户重试
                return jsonify({"error": f"行情接口连接异常，请稍后重试（{e}）"}), 503
            except Exception:
                failed.append(token)
                continue
            if add_stock(resolved_code, resolved_name):
                added += 1
            else:
                skipped += 1
        return jsonify({"ok": True, "added": added, "skipped": skipped, "failed": failed})

    # Single stock add
    if not code:
        return jsonify({"error": "请输入股票代码"}), 400

    try:
        from fetcher import resolve_stock_code
        resolved_code, resolved_name = resolve_stock_code(code)
    except BaostockError as e:
        return jsonify({"error": f"行情接口连接异常，请稍后重试（{e}）"}), 503
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
    """改持仓或清仓。股数 0（或不传）＝清仓，负数视为输入错误。"""
    data = request.get_json(silent=True) or {}
    try:
        shares = int(data.get("shares") or 0)
        cost = float(data.get("cost") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "股数和成本必须是数字"}), 400
    if shares < 0 or cost < 0:
        return jsonify({"error": "股数和成本不能为负数"}), 400
    if shares > 0 and cost <= 0:
        return jsonify({"error": "填了持股数量就要填持仓成本（清仓请把数量填 0）"}), 400

    from portfolio import set_position
    ok = set_position(code, shares, cost)
    if not ok:
        return jsonify({"error": "请先将该股票加入自选"}), 404

    return jsonify({"ok": True, "code": norm_code(code), "shares": shares,
                    "cost": cost, "cleared": shares <= 0})


@app.route("/api/position", methods=["POST"])
def api_position_add():
    """从持仓页直接建仓：代码/名称 + 股数 + 成本，自动补进自选。

    PUT /api/position/<code> 要求股票已在自选里；这里省掉那一步。
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or data.get("code") or "").strip()
    try:
        shares = int(data.get("shares") or 0)
        cost = float(data.get("cost") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "股数和成本必须是数字"}), 400

    if not query:
        return jsonify({"error": "请输入股票代码或名称"}), 400
    if shares <= 0 or cost <= 0:
        return jsonify({"error": "股数和成本必须大于 0"}), 400

    from fetcher import BaostockError, resolve_stock_code
    from portfolio import add_stock, set_position

    try:
        code, name = resolve_stock_code(query)
    except BaostockError as e:
        return jsonify({"error": f"行情接口连接异常，请稍后重试（{e}）"}), 503
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    add_stock(code, name)
    set_position(code, shares, cost)
    return jsonify({"ok": True, "code": code, "name": name, "shares": shares, "cost": cost})


# ---------------------------------------------------------------------------
# 账户资金 + 组合计划
# ---------------------------------------------------------------------------

@app.route("/api/account", methods=["GET", "PUT"])
def api_account():
    """GET 读总资金；PUT {"capital": 200000} 改总资金。"""
    from portfolio import get_capital, set_capital

    if request.method == "GET":
        return jsonify({"capital": get_capital()})

    data = request.get_json(silent=True) or {}
    try:
        value = float(data.get("capital"))
    except (TypeError, ValueError):
        return jsonify({"error": "总资金必须是数字"}), 400
    if value < 0:
        return jsonify({"error": "总资金不能为负数"}), 400
    return jsonify({"ok": True, "capital": set_capital(value)})


@app.route("/api/backups", methods=["GET", "POST"])
def api_backups():
    """GET 列持仓快照；POST {"name": "portfolio-...json"} 回滚到某一份。

    每次保存 portfolio.json 前都会自动拍快照，所以误删/误改都能自己找回来。
    """
    from portfolio import list_backups, restore_backup

    if request.method == "GET":
        return jsonify({"backups": list_backups()})

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "缺少要恢复的快照名 name"}), 400
    if not restore_backup(name):
        return jsonify({"error": f"恢复失败：{name} 不存在或内容不合法"}), 404
    return jsonify({"ok": True, "restored": name})


@app.route("/api/portfolio")
def api_portfolio():
    """持仓全景：账户资金 + 每只票的行情/建议 + 明日预案 + 组合级计划（含该买卖多少股）。

    价格取**最新报价**（盘中会变），技术指标与止损位取日线（30 分钟缓存），
    所以这个接口既可以盘中反复刷新，也不会把行情源打爆。
    """
    from fetcher import fetch_daily_kline, get_stock_info
    from indicators import calc_all
    from masters import analyze as masters_analyze
    from plan import LOGIC as PLAN_LOGIC, build
    from portfolio import get_all_stocks, get_capital
    from strategy import analyze_day
    from tomorrow import plan as tomorrow_plan

    holdings: list[dict] = []
    errors: list[dict] = []
    for entry in get_all_stocks():
        if not entry.get("has_position"):
            continue
        code = entry["code"]
        name = entry.get("name") or code
        shares = int(entry.get("shares") or 0)
        cost = float(entry.get("cost") or 0)
        tomorrow = None
        try:
            df = calc_all(fetch_daily_kline(code, 120))
            advice = analyze_day(df, entry)
            price = advice["price"]
            try:
                live = get_stock_info(code)
                price = float(live.get("price") or price)
                name = live.get("name") or name
            except Exception:
                pass  # 报价失败就用收盘价，不影响整套建议
            tomorrow = tomorrow_plan(df, entry, advice)
            try:
                masters = masters_analyze(df, name, code, entry, detail=False)
            except Exception:
                masters = None  # 大师视角是附加信息，挂了不影响仓位建议
        except Exception as e:
            # 行情拿不到时按成本价计入账户，别让总资产凭空缩水
            errors.append({"code": code, "name": name, "error": f"{type(e).__name__}: {e}"})
            advice = {"action": "观望", "urgency": "低", "price": cost,
                      "reasons": [f"行情获取失败：{e}"], "metrics": {"pct": 0.0}, "levels": {}}
            price = cost
            tomorrow = {"bias": "未知", "score": 0, "confidence": 0, "action": "观望",
                        "levels": {}, "plan": ["行情获取失败，暂无明日预案"], "reasons": []}
            masters = None
        holdings.append({"code": code, "name": name, "shares": shares,
                         "cost": cost, "price": price, "advice": advice,
                         "tomorrow": tomorrow, "masters": masters})

    result = build(holdings, get_capital())
    result["errors"] = errors
    result["logic"] = PLAN_LOGIC
    result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(result)


# ---------------------------------------------------------------------------
# 实时盯盘：到达买卖点就报警
# ---------------------------------------------------------------------------

@app.route("/api/alerts")
def api_alerts():
    """用最新报价对照止损/加仓/止盈/MA20，返回当前触发的信号。

    前端每 60 秒轮询一次，触发时才弹通知；日线走 30 分钟缓存，
    所以这个接口只多花「每只一次报价」的时间（约 0.1 秒/只）。
    """
    from fetcher import fetch_daily_kline, get_stock_info
    from indicators import calc_all
    from portfolio import get_all_stocks
    from strategy import analyze_day

    items: list[dict] = []
    quotes: dict[str, float] = {}
    errors: list[dict] = []

    for entry in get_all_stocks():
        code = entry["code"]
        name = entry.get("name") or code
        has_pos = bool(entry.get("has_position"))
        shares = int(entry.get("shares") or 0)
        try:
            info = get_stock_info(code)
            price = float(info.get("price") or 0)
            name = info.get("name") or name
            if price <= 0:
                continue
            quotes[code] = price
            live_pct = float(info.get("pct_change") or 0)

            df = calc_all(fetch_daily_kline(code, 120))
            advice = analyze_day(df, {**entry, "has_position": has_pos})
            lv = advice.get("levels") or {}
            stop = float(lv.get("stop") or 0)
            target = float(lv.get("target") or 0)
            add = float((lv.get("add") or [0])[0] or 0)
            ma20 = float((advice.get("metrics") or {}).get("ma20") or 0)
            pct = float((advice.get("metrics") or {}).get("pct") or 0)

            def add_item(kind: str, level: str, text: str, trigger: float) -> None:
                items.append({
                    "key": f"{code}:{kind}",
                    "code": code, "name": name, "kind": kind, "level": level,
                    "price": round(price, 2), "trigger": round(trigger, 2),
                    "shares": shares, "has_position": has_pos,
                    "action": advice.get("action", "观望"),
                    "text": text,
                })

            if has_pos and stop > 0:
                if price <= stop:
                    add_item("stop", "danger",
                             f"{name} 现价 {price:.2f} 已跌破止损位 {stop:.2f}，按纪律离场", stop)
                elif price <= stop * 1.015:
                    add_item("near_stop", "warn",
                             f"{name} 现价 {price:.2f} 距止损位 {stop:.2f} 只剩 "
                             f"{(price - stop) / price * 100:.1f}%，盯紧", stop)
            if target > 0 and price >= target:
                add_item("target", "action",
                         f"{name} 现价 {price:.2f} 到达目标 {target:.2f}，可分批止盈", target)
            if not has_pos and add > 0 and price <= add * 1.005 and advice.get("action") in ("买入", "加仓"):
                add_item("add", "action",
                         f"{name} 现价 {price:.2f} 回到加仓位 {add:.2f}，符合买入条件", add)
            if has_pos and ma20 > 0 and price < ma20 and add <= price * 0.98:
                add_item("ma20", "warn",
                         f"{name} 现价 {price:.2f} 跌破 MA20 {ma20:.2f}，短线转弱", ma20)
            # 冲高用**实时涨跌幅**（日线收盘价的 pct 是昨天的事，盘中报警要当天口径）
            move = live_pct if live_pct else pct
            if has_pos and move >= 5:
                add_item("surge", "info", f"{name} 今日 {move:+.1f}%，冲高注意回落", price)
            elif has_pos and live_pct <= -5:
                add_item("surge", "info", f"{name} 今日 {live_pct:+.1f}%，跌得急，别急着割也别急着补", price)
        except Exception as e:
            errors.append({"code": code, "name": name, "error": f"{type(e).__name__}: {e}"})

    order = {"danger": 0, "warn": 1, "action": 2, "info": 3}
    items.sort(key=lambda x: (order.get(x["level"], 9), -abs(x["price"] - x["trigger"])))
    return jsonify({
        "ok": True,
        "checked_at": datetime.now().strftime("%H:%M:%S"),
        "items": items,
        "quotes": quotes,
        "errors": errors,
    })


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


@app.route("/api/recommend")
def api_recommend():
    """每日推荐：稳健 3 + 激进 3。

    GET /api/recommend         → 当天有缓存直接返回，否则后台开算并返回 running
    GET /api/recommend?force=1 → 丢掉缓存重算

    返回 status: done / running / error，running 时前端轮询。
    附带 logic：筛选与打分的规则说明（前端「筛选逻辑」面板直接渲染）。
    """
    from recommend import LOGIC, get_recommendations

    force = request.args.get("force", "0") in ("1", "true", "yes")
    try:
        payload = get_recommendations(force=force)
        payload["logic"] = LOGIC
        return jsonify(payload)
    except Exception as e:
        return jsonify({"status": "error", "data": None,
                        "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/masters")
def api_masters():
    """同一只股票，用八种投资大师的方法论各打一次分。

    GET /api/masters?query=600519（也接受名称）
    返回 {code,name,date,price,pct,masters:[...],consensus:{...}}
    """
    from fetcher import FetchError, fetch_daily_kline, resolve_stock_code
    from indicators import calc_all
    from masters import analyze
    from portfolio import get_stock

    query = (request.args.get("query") or request.args.get("code") or "").strip()
    if not query:
        return jsonify({"error": "缺少 query 参数（代码或名称）"}), 400

    try:
        code, name = resolve_stock_code(query)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400

    try:
        df = calc_all(fetch_daily_kline(code, 250))
        entry = get_stock(code)
        return jsonify(analyze(df, name, code, entry))
    except FetchError as e:
        return jsonify({"error": f"行情接口暂时不可用，请稍后重试（{e}）"}), 503
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/strategy")
def api_strategy():
    """自选股今日买卖策略：逐只算 MA/量价/RSI，按持仓状态给动作。

    返回 {date, count, results:[{code,name,ok,...成果或 error}]}
    """
    from fetcher import fetch_daily_kline
    from indicators import calc_all
    from masters import analyze as masters_analyze
    from portfolio import get_all_stocks
    from strategy import analyze_day

    results = []
    for entry in get_all_stocks():
        code = entry["code"]
        name = entry.get("name") or code
        try:
            df = calc_all(fetch_daily_kline(code, 120))
            advice = analyze_day(df, entry)
            try:
                masters = masters_analyze(df, name, code, entry, detail=False)
            except Exception:
                masters = None  # 大师视角是附加信息，挂了不影响当日策略
            results.append({
                "code": code,
                "name": name,
                "ok": True,
                "date": str(df["date"].iloc[-1])[:10],
                **advice,
                "masters": masters,
            })
        except Exception as e:
            results.append({"code": code, "name": name, "ok": False,
                            "error": f"{type(e).__name__}: {e}"})

    return jsonify({
        "count": len(results),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "results": results,
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
