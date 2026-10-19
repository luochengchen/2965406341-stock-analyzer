"""账户级交易计划：把「个股结论 + 持仓数量 + 总资金」换算成能直接下单的建议。

`strategy.analyze_day()` 只回答「这只票今天该加还是该减」，不知道你手里有多少钱、
这只票已经占了多少仓位。本模块补上这一层：

- 用**总资金**算出成本、可用现金、持仓市值、总资产、仓位。
- 给每只票一个**目标权重**（由个股动作决定），差额换成人话的手数（A 股一手 100 股）。
- 组合层面看仓位、现金、集中度、亏损面，给出当日可执行的清单。

硬约束（都可调，写在下面的常量里）：单票不超过总资产 25%，始终留 10% 现金。
"""
from __future__ import annotations

import fees

LOT = 100                 # A 股一手 = 100 股
MAX_WEIGHT = 0.25         # 单票占「总资产」的上限
MIN_CASH_RATIO = 0.10     # 现金下限（占总资产）
ADD_WEIGHT_STEP = 0.05    # 「加仓」一次加 5 个百分点

# 目标权重：由个股动作推出来，差额才是要买卖的数量。
# (倍数, 固定值)：目标 = 当前权重 * 倍数，或固定占总资产比例
_TARGET = {
    "加仓": ("step", ADD_WEIGHT_STEP),
    "买入": ("fixed", 0.15),
    "持有": ("keep", 0.0),
    "观望": ("keep", 0.0),
    "减仓": ("mul", 0.60),
    "止损": ("fixed", 0.0),
    "卖出": ("fixed", 0.0),
}

LOGIC = {
    "rules": [
        "单票目标权重由个股动作决定：加仓 +5pp、减仓 ×0.6、止损/卖出 → 0、持有不动",
        f"单票上限总资产 {int(MAX_WEIGHT * 100)}%，超过就减到上限",
        f"现金下限 {int(MIN_CASH_RATIO * 100)}%，想加仓但钱不够时只提示不加",
        "买入按 100 股一手向下取整并留出手续费；卖出可精确到股，止损/卖出直接清仓不留零股",
        "金额保留两位小数，并给出含费用的实付/到手（佣金万 2.5 最低 5 元、印花税卖 0.05%、过户费 0.001%、ETF 免印花税）",
    ],
    "note": "现金 = 总资金 − 持仓成本；总资产 = 现金 + 持仓市值（浮盈浮亏都算总资产）",
}


def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def _target_weight(action: str, weight: float) -> float:
    mode, value = _TARGET.get(action, ("keep", 0.0))
    if mode == "keep":
        # 「持有」不等于「不管比例」：超过单票上限照样要减回上限
        return min(weight, MAX_WEIGHT)
    if mode == "fixed":
        return value
    if mode == "mul":
        return min(MAX_WEIGHT, weight * value)
    return min(MAX_WEIGHT, weight + value)


def build(holdings: list[dict], capital: float) -> dict:
    """生成账户级计划。

    Args:
        holdings: [{code, name, shares, cost, price, advice}]，
            advice 是 `strategy.analyze_day()` 的返回值。
        capital: 账户总资金（0 表示用户还没设）。

    Returns:
        {"account": {...}, "holdings": [...], "overall": {...}}
    """
    capital = max(0.0, float(capital or 0.0))
    settled = capital > 0

    rows = []
    cost_value = 0.0
    market_value = 0.0
    for item in holdings:
        shares = int(item.get("shares") or 0)
        cost = float(item.get("cost") or 0.0)
        price = float(item.get("price") or 0.0)
        advice = item.get("advice") or {}
        levels = advice.get("levels") or {}
        cv = shares * cost
        mv = shares * price
        cost_value += cv
        market_value += mv
        rows.append({
            "code": item.get("code", ""),
            "name": item.get("name", ""),
            "shares": shares,
            "cost": _r(cost, 3),
            "price": _r(price),
            "pct": advice.get("metrics", {}).get("pct", 0.0),
            "cost_value": _r(cv),
            "market_value": _r(mv),
            "profit": _r(mv - cv),
            "profit_pct": _r((price - cost) / cost * 100) if cost > 0 else 0.0,
            "action": advice.get("action", "观望"),
            "urgency": advice.get("urgency", "低"),
            "stop": levels.get("stop", 0.0),
            "target": levels.get("target", 0.0),
            "tomorrow": item.get("tomorrow"),
            "masters": item.get("masters"),
            "reasons": advice.get("reasons", []),
        })

    # 总资金 = 现金 + 持仓成本。用户只填了「现在的现金」时，这个差会是负数，
    # 直接拿它算仓位会把总资产算成负数——所以要夹到 0，并明确提示去改总资金。
    raw_cash = capital - cost_value if settled else 0.0
    cash = max(0.0, raw_cash)
    shortfall = _r(-raw_cash) if raw_cash < 0 else 0.0
    total_assets = cash + market_value if settled else market_value
    position_pct = market_value / total_assets * 100 if total_assets > 0 else 0.0
    cash_pct = cash / total_assets * 100 if total_assets > 0 else 0.0

    account = {
        "capital": _r(capital),
        "settled": settled,
        "cost_value": _r(cost_value),
        "cash": _r(cash),
        "shortfall": shortfall,
        "market_value": _r(market_value),
        "total_assets": _r(total_assets),
        "position_pct": _r(position_pct),
        "cash_pct": _r(cash_pct),
        "profit": _r(market_value - cost_value),
        "profit_pct": _r((market_value - cost_value) / cost_value * 100) if cost_value > 0 else 0.0,
    }

    for row in rows:
        row["weight"] = _r(row["market_value"] / total_assets * 100 if total_assets > 0 else 0.0)
        row["suggest"] = _suggest(row, account, settled)

    return {
        "account": account,
        "holdings": rows,
        "overall": _overall(rows, account, settled),
    }


def _suggest(row: dict, account: dict, settled: bool) -> dict:
    """单只票：目标权重 → 要买卖多少股。

    取整口径（A 股实盘规则）：

    - **买入必须整手**（100 股的整数倍），向下取整并留出手续费，避免「差几块钱买不进」。
    - **卖出可以精确到股**；止损/卖出直接清掉全部持仓（含零股），不留尾巴。
    - 减仓取整手，但若减完剩不足一手，就一并卖出（A 股零股必须一次性卖出）。
    - 金额一律保留两位小数，并给出**含费用的实付/到手**，这样和券商账单对得上。
    """
    price = row["price"]
    action = row["action"]
    weight = row["weight"] / 100
    target = _target_weight(action, weight)

    head = {
        "action": action,
        "urgency": row["urgency"],
        "target_weight": _r(min(target, MAX_WEIGHT) * 100, 1),
    }
    if not settled:
        return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                "text": "先设置总资金，才能算该买多少股"}
    if price <= 0:
        return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                "text": "行情价格缺失，暂不下结论"}

    code = row.get("code", "")
    total_assets = account["total_assets"]
    held = int(row["shares"] or 0)
    delta_value = (target - weight) * total_assets
    lot_value = price * LOT
    delta_shares = int(abs(delta_value) // lot_value) * LOT

    def _sell(shares: int, verb: str) -> dict:
        """卖出/清仓：金额、费用、到手一次算清。"""
        shares = min(shares, held)
        cost = fees.estimate(code, "sell", price, shares)
        new_w = max(0.0, weight * 100 - shares * price / total_assets * 100) if total_assets > 0 else 0.0
        return {**head, "shares": -shares, "amount": _r(cost["amount"]), "fee": _r(cost["fee"]),
                "net": _r(cost["net"]), "kind": "clear" if shares >= held else "sell",
                "adjust": _adjust(action, "减仓"),
                "text": f"{verb} {shares} 股 ≈ {cost['amount']:,.2f} 元（费用 {cost['fee']:,.2f}，"
                        f"到手 {cost['net']:,.2f}），权重 {row['weight']:.1f}% → {new_w:.1f}%"}

    # 止损 / 卖出 / 目标权重为 0：清仓，不留零股
    if target <= 0 and held > 0:
        return _sell(held, "清仓")

    if abs(delta_value) < lot_value:
        # 差额不够一手：高价股（如茅台一手十几万）经常落在这里
        if delta_value < 0 and weight > MAX_WEIGHT and held > 0:
            return _sell(min(held, LOT), "先减")
        if delta_value < 0 and held > 0 and weight > MAX_WEIGHT:
            return _sell(held, "减")
        return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                "text": "仓位已接近目标，不必调整（差额不足一手）"}

    if delta_value > 0:
        # 加仓：受现金下限约束，且要留出手续费
        budget = account["cash"] - MIN_CASH_RATIO * total_assets
        if budget < price * LOT:
            return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                    "text": f"想加仓但现金只剩 {account['cash']:,.2f} 元（留足 10% 后不够一手）"}
        max_lots = int(budget // (price * LOT * (1 + fees.COMMISSION_RATE)))
        delta_shares = min(delta_shares, max_lots * LOT)
        # 再按含费金额复核一次，宁可少一手也不让实付超预算
        while delta_shares >= LOT and fees.estimate(code, "buy", price, delta_shares)["net"] > budget:
            delta_shares -= LOT
        if delta_shares < LOT:
            return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                    "text": f"想加仓但扣掉手续费后现金不够一手（可用 {budget:,.2f} 元）"}
        cost = fees.estimate(code, "buy", price, delta_shares)
        return {**head, "shares": delta_shares, "amount": _r(cost["amount"]), "fee": _r(cost["fee"]),
                "net": _r(cost["net"]), "kind": "buy",
                "adjust": _adjust(action, "加仓"),
                "text": f"加 {delta_shares} 股 ≈ {cost['amount']:,.2f} 元（费用 {cost['fee']:,.2f}，"
                        f"实付 {cost['net']:,.2f}），权重 {row['weight']:.1f}% → "
                        f"{_r(weight * 100 + delta_shares * price / total_assets * 100, 1)}%"}

    if held <= 0:
        return {**head, "shares": 0, "amount": 0.0, "fee": 0.0, "net": 0.0, "kind": "hold",
                "text": "没有持仓，无需卖出"}

    # 减仓：整手向下取整；若剩不足一手就一并卖掉
    sell = delta_shares
    if sell > held:
        sell = held
    elif held - sell < LOT:
        sell = held
    return _sell(sell, "减")


def _adjust(action: str, want: str) -> str:
    """个股信号与仓位调节方向不一致时，标出真正要做的动作（如「持有→减仓」）。"""
    if want == "减仓" and action not in ("减仓", "止损", "卖出"):
        return "减仓"
    if want == "加仓" and action not in ("加仓", "买入"):
        return "加仓"
    return ""


def _overall(rows: list[dict], account: dict, settled: bool) -> dict:
    """组合层面：仓位 / 现金 / 集中度 / 亏损面，输出可执行清单。"""
    lines: list[str] = []
    suggestions: list[dict] = []

    if not rows:
        return {"level": "空仓", "score": 0, "lines": ["还没有持仓记录"],
                "suggestions": [{"title": "先加一只", "detail": "在「持仓」里填代码、股数、成本，才能算仓位和买卖数量",
                                 "level": "info"}]}

    pct = account["position_pct"]
    if pct >= 90:
        level = "满仓"
    elif pct >= 70:
        level = "重仓"
    elif pct >= 30:
        level = "中性"
    else:
        level = "轻仓"

    if not settled:
        lines.append(f"还没设置总资金，当前只能按持仓市值 {account['market_value']:,.0f} 元算相对占比")
    else:
        lines.append(f"总资产 {account['total_assets']:,.0f} 元：持仓 {account['market_value']:,.0f} 元"
                     f"（{pct:.1f}%）、现金 {account['cash']:,.0f} 元（{account['cash_pct']:.1f}%）")
        lines.append(f"持仓成本 {account['cost_value']:,.0f} 元，浮动盈亏 {account['profit']:+,.0f} 元"
                     f"（{account['profit_pct']:+.2f}%）")

    # 0) 总资金填得比持仓成本还小 —— 后面的仓位、现金全是错的，先纠这个
    if account.get("shortfall"):
        suggestions.append({
            "title": "总资金填少了",
            "detail": (f"总资金 {account['capital']:,.2f} 元 < 持仓成本 {account['cost_value']:,.2f} 元，"
                       f"差额 {account['shortfall']:,.2f} 元。总资金请填「可用现金 + 持仓成本」，"
                       f"现在现金按 0 算，仓位与可买数量都不可信"),
            "level": "danger",
        })

    # 1) 先处理「该走」的票
    exits = [r for r in rows if r["action"] in ("止损", "卖出")]
    for r in exits:
        stop = r["stop"]
        suggestions.append({
            "title": f"{r['name']} 触发{r['action']}",
            "detail": (r["reasons"][-1] if r["reasons"] else "") +
                      (f"，止损位 {stop:.2f}" if stop else "") +
                      (f"；按计划清仓可收回约 {r['market_value']:,.0f} 元" if r["shares"] else ""),
            "level": "danger",
        })

    # 2) 现金与仓位
    if settled and account["cash_pct"] < MIN_CASH_RATIO * 100 and not exits:
        suggestions.append({
            "title": "现金偏少",
            "detail": f"现金只占 {account['cash_pct']:.1f}%，低于 {int(MIN_CASH_RATIO * 100)}% 的安全垫；"
                      f"回调时没子弹，可先减掉最弱的一只",
            "level": "warn",
        })
    elif settled and pct > 75:
        suggestions.append({
            "title": "仓位偏重",
            "detail": f"仓位 {pct:.1f}%，超过 75% 后大盘或个别票回撤会明显伤本金，"
                      f"建议减到 60~70%",
            "level": "warn",
        })
    elif settled and pct < 20 and rows:
        suggestions.append({
            "title": "仓位偏轻",
            "detail": f"仓位只有 {pct:.1f}%，若整体看多可以按个股动作分批加，不必一次打满",
            "level": "info",
        })

    if settled and account["cash_pct"] > 40 and rows and not exits:
        spendable = account["cash"] - MIN_CASH_RATIO * account["total_assets"]
        suggestions.append({
            "title": f"现金 {account['cash']:,.0f} 元还没干活",
            "detail": f"扣掉 {int(MIN_CASH_RATIO * 100)}% 安全垫，可部署约 {spendable:,.0f} 元；"
                      f"按单票 {int(MAX_WEIGHT * 100)}% 上限最多能放 {int(spendable / (MAX_WEIGHT * account['total_assets'])) or 1} 只，"
                      f"建议分 2~3 批进，别一天打满",
            "level": "info",
        })

    # 3) 集中度
    for r in sorted(rows, key=lambda x: -x["weight"])[:2]:
        if r["weight"] > MAX_WEIGHT * 100:
            suggestions.append({
                "title": f"{r['name']} 过度集中",
                "detail": f"占总资产 {r['weight']:.1f}%，超过 {int(MAX_WEIGHT * 100)}% 上限；"
                          f"单票黑天鹅会把整个账户拖下水",
                "level": "warn",
            })

    # 4) 亏损面
    losers = [r for r in rows if r["profit_pct"] <= -8]
    for r in losers:
        suggestions.append({
            "title": f"{r['name']} 浮亏 {r['profit_pct']:.1f}%",
            "detail": f"成本 {r['cost']:.2f}、现价 {r['price']:.2f}"
                      + (f"、止损位 {r['stop']:.2f}" if r["stop"] else "")
                      + "；跌破止损位按纪律走，别扛",
            "level": "danger",
        })

    # 5) 今日可执行清单（按金额从大到小，按含费实付/到手汇总）
    moves = [r for r in rows if r["suggest"]["shares"] != 0]
    if moves:
        buys = [r for r in moves if r["suggest"]["shares"] > 0]
        sells = [r for r in moves if r["suggest"]["shares"] < 0]
        total_buy = sum(r["suggest"]["net"] for r in buys)
        total_sell = sum(r["suggest"]["net"] for r in sells)
        parts = []
        if total_buy:
            parts.append(f"买入实付约 {total_buy:,.2f} 元")
        if total_sell:
            parts.append(f"卖出到手约 {total_sell:,.2f} 元")
        head = "今日可执行" + (f"（{' / '.join(parts)}）" if parts else "")
        cash_after = account["cash"] + total_sell - total_buy
        detail = "；".join(f"{r['name']} {r['suggest']['text']}" for r in
                           sorted(moves, key=lambda x: -abs(x['suggest']['amount'])))
        if settled:
            detail += f"。全部执行后现金约 {cash_after:,.2f} 元"
        suggestions.insert(0, {
            "title": head,
            "detail": detail,
            "level": "action",
        })

    score = 50
    score += 15 if 30 <= pct <= 70 else (-15 if pct > 85 or pct < 10 else 0)
    score -= 10 * len([r for r in rows if r["weight"] > MAX_WEIGHT * 100])
    score -= 8 * len(losers)
    score += 5 if account["profit_pct"] > 0 else 0
    score = max(0, min(100, score)) if settled else 0

    if not lines:
        lines.append("设置总资金后，这里会按仓位、集中度给出完整建议")

    return {
        "level": level,
        "score": score,
        "lines": lines,
        "suggestions": suggestions[:6],
    }
