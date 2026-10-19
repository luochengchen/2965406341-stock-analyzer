"""股票代码规范化 —— 独立小模块，不依赖任何行情库。

为什么单独一层：`portfolio.py` / `watchlist.py` / `web_app.py` 都要把用户输入的代码
统一成内部形式，但它们不该为此 import `fetcher`（连带 baostock、pandas，慢且重）。
"""
from __future__ import annotations


def norm_code(code: str) -> str:
    """统一股票代码：去掉市场前缀，A 股补足 6 位，港股保持 5 位。

    'sh.600519' / '600519' -> '600519'
    '00700' -> '00700'（**不能**补成 000700，那是模塑科技，A 股和港股会串）
    'bj920566' -> '920566'
    """
    text = str(code).strip().lower()
    for prefix in ("sh.", "sz.", "bj.", "hk."):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for prefix in ("sh", "sz", "bj", "hk"):
        if text.startswith(prefix) and text[len(prefix):].isdigit():
            text = text[len(prefix):]
            break
    if text.isdigit():
        if len(text) == 5:  # 港股
            return text
        if len(text) < 6:
            return text.zfill(6)
    return text
