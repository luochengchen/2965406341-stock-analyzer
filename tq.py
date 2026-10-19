"""腾讯行情（`qt.gtimg.cn` / `web.ifzq.gtimg.cn`）。

东财的 push2 接口会按 IP 限流（实测突发十几个请求后直接 `RemoteDisconnected`），
所以行情主源换成腾讯：同样免费、不用 key，覆盖沪深主板/创业板/科创板、北交所
（`bj920566`）、ETF/LOF（`sh510300`）、港股（`hk00700`），而且单只日线约 0.15s。

两个注意点：

- 日线**没有成交额字段**，只有成交量（单位：A 股/ETF 是手，港股是股）。
  `kline()` 用 `量 × 100 × (高+低+收)/3` 估算成交额（港股不乘 100）。
  估算只用于「日均成交 1.5 亿 / 3 亿」这类粗阈值，不影响量比、均线等技术指标。
- 港股前复权数据键名是 `day` 而不是 `qfqday`，且每行多一个除权信息字典。
"""
from __future__ import annotations

import json
import time
import urllib.request

import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}

_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"
# 新老两个日线接口：老的 web.ifzq.gtimg.cn 会按 IP 返回 501（实测连续请求后整站不通），
# 新的 proxy.finance.qq.com 覆盖更全（北交所也给满 250 根），优先用它。
_KLINE_URLS = (
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    "?param={symbol},day,,,{lmt},{fq}",
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param={symbol},day,,,{lmt},{fq}",
)


class TencentError(RuntimeError):
    """腾讯没有这只票的数据（或字段不认识）。"""


class TencentNetworkError(TencentError):
    """腾讯接口连不上（断网 / 被限流）。"""


def symbol_of(code: str) -> str:
    """'600519' -> 'sh600519'；'920566' -> 'bj920566'；'00700' -> 'hk00700'。"""
    from em import is_hk, mkt_of  # 复用同一套市场判断，避免两处规则不一致

    code = str(code).strip().lower()
    for prefix in ("sh", "sz", "bj", "hk"):
        if code.startswith(prefix):
            return code
    if is_hk(code):
        return f"hk{code}"
    if code.startswith(("43", "83", "87", "92")):  # 北交所在腾讯用 bj 前缀
        return f"bj{code}"
    return ("sh" if mkt_of(code) == "1" else "sz") + code


def _fetch(url: str) -> str:
    last: Exception | None = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("gbk", "ignore")
        except Exception as exc:
            last = exc
            time.sleep(0.3)
    raise TencentNetworkError(f"腾讯行情请求失败: {last}")


def quote(code: str) -> dict:
    """最新价 + 涨跌幅。停牌时腾讯返回空字段，抛 TencentError 让上层回落。"""
    text = _fetch(_QUOTE_URL.format(symbols=symbol_of(code)))
    body = text.split('"')[1] if '"' in text else ""
    parts = body.split("~")
    if len(parts) < 5 or not parts[3]:
        raise TencentError(f"腾讯没有 {code} 的报价")

    price = float(parts[3])
    prev = float(parts[4]) if parts[4] else 0.0
    pct = (price - prev) / prev * 100 if prev > 0 else 0.0
    return {"name": parts[1].strip(), "price": price, "pct_change": round(pct, 2)}


def kline(code: str, days: int = 250) -> pd.DataFrame:
    """前复权日线，列与 baostock 版一致：date, open, high, low, close, volume, amount。"""
    sym = symbol_of(code)
    fq = "qfq"
    lmt = max(int(days), 250)

    node: dict = {}
    last: Exception | None = None
    for url in _KLINE_URLS:
        try:
            data = json.loads(_fetch(url.format(symbol=sym, lmt=lmt, fq=fq)))
        except Exception as exc:
            last = exc
            continue
        node = (data.get("data") or {}).get(sym) or {}
        if (node.get("qfqday") or node.get("day")):
            break

    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        if last and not isinstance(last, TencentError):
            raise TencentNetworkError(f"腾讯日线接口不可用: {last}")
        raise TencentError(f"腾讯没有 {code} 的日线数据")

    recs = []
    for row in rows:
        if len(row) < 6:
            continue
        recs.append(row[:6])

    df = pd.DataFrame(recs, columns=["date", "open", "close", "high", "low", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 成交量 -> 成交额（估算）：A 股/ETF 的量单位是手，港股是股
    factor = 1.0 if sym.startswith("hk") else 100.0
    df["amount"] = df["volume"] * factor * (df["high"] + df["low"] + df["close"]) / 3

    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]
