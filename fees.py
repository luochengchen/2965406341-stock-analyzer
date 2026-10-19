"""交易费用估算。

为什么要单独一层：账户页给出的「加仓 400 股 ≈ 4,658 元」如果不扣手续费，
用户对不上券商 App 里的实际成交金额；减仓/清仓时尤其明显——实际到手比
「股数 × 价格」少一截，浮亏看起来就和真实亏损对不上。

费率按 2026 年散户常见口径（可改常量）：

- A 股：佣金万 2.5（最低 5 元，双向）、印花税 0.05%（**仅卖出**）、过户费 0.001%（双向）
- ETF/LOF：免印花税、免过户费，只有佣金
- 港股：佣金万 2.5（最低 5 元）、印花税 0.1%（双向）、其余费用合计约 0.01%

港股按港币计价，不做汇率换算（与仓位口径一致）。
"""
from __future__ import annotations

COMMISSION_RATE = 0.00025   # 佣金：万 2.5
COMMISSION_MIN = 5.0        # 单笔最低 5 元
STAMP_RATE = 0.0005         # 印花税：0.05%，只收卖出方
TRANSFER_RATE = 0.00001     # 过户费：0.001%，双向
HK_STAMP_RATE = 0.001       # 港股印花税：0.1%，双向
HK_OTHER_RATE = 0.0001      # 港股交易费 + 交易征费 + 结算费（合并估算）


def kind(code: str) -> str:
    """'hk' / 'etf' / 'stock'。"""
    code = str(code or "").strip().lower()
    for prefix in ("sh", "sz", "bj", "hk"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    if len(code) == 5 and code.isdigit():
        return "hk"
    if code.startswith(("15", "16", "50", "51", "52", "56", "58")):
        return "etf"
    return "stock"


def estimate(code: str, side: str, price: float, shares: int) -> dict:
    """估算一笔交易的费用。

    Args:
        code: 股票代码（用来判断 A 股 / ETF / 港股）。
        side: "buy" 或 "sell"。
        price: 成交价。
        shares: 股数（必须 > 0）。

    Returns:
        {"amount", "commission", "stamp", "transfer", "fee", "net"}
        net 是买入的实付、卖出的实收（已扣费）。
    """
    shares = max(0, int(shares or 0))
    amount = max(0.0, float(price or 0.0)) * shares
    if amount <= 0:
        return {"amount": 0.0, "commission": 0.0, "stamp": 0.0, "transfer": 0.0,
                "fee": 0.0, "net": 0.0}

    category = kind(code)
    commission = max(COMMISSION_MIN, amount * COMMISSION_RATE)

    if category == "hk":
        stamp = amount * HK_STAMP_RATE
        transfer = 0.0
        other = max(2.0, min(100.0, amount * HK_OTHER_RATE))
    elif category == "etf":
        stamp = 0.0
        transfer = 0.0
        other = 0.0
    else:
        stamp = amount * STAMP_RATE if side == "sell" else 0.0
        transfer = amount * TRANSFER_RATE
        other = 0.0

    fee = commission + stamp + transfer + other
    net = amount - fee if side == "sell" else amount + fee
    return {
        "amount": round(amount, 2),
        "commission": round(commission, 2),
        "stamp": round(stamp, 2),
        "transfer": round(transfer, 2),
        "fee": round(fee, 2),
        "net": round(net, 2),
    }
