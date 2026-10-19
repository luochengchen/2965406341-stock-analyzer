"""新浪搜索（`suggest3.sinajs.cn`）。

用于「代码/名称/拼音 → 股票」这一步，因为它覆盖面最广：沪深 A 股、北交所
（`bj920566`）、ETF/LOF（`sh510300`）、港股（`00700`），而且还会把北交所已停用
的老代码（`832566`）自动换成新代码（`920566`）。

返回格式（GBK）：

    var suggestdata="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,99,1,ESG,,;...";

每段按 `,` 拆分：`[0]` 名称、`[1]` 类型码、`[2]` 不带前缀的代码、
`[3]` 带市场前缀的标识（`sh600519` / `bj920566` / 港股直接是 `00700`）。
场外基金给的是 `of510300` 这种前缀，正好用来过滤掉「不能在场内买」的品种。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_URL = "https://suggest3.sinajs.cn/suggest/type=&key={key}&name=suggestdata"
_KLINE_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
              "CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={n}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

#: 类型码含义（实测）：11=A 股，31=港股，203/204=沪深 ETF/LOF
_TYPE_NAME = {"11": "A股", "31": "港股", "203": "沪基金", "204": "深基金"}

#: 排序权重：A 股优先，其次场内基金，再次港股
_TYPE_RANK = {"11": 0, "203": 1, "204": 1, "31": 2}


class SinaError(RuntimeError):
    """新浪搜索不通。"""


class SinaNetworkError(SinaError):
    """新浪接口连不上（断网 / 被限流）。"""


def _fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("gbk", "ignore")
    except Exception as exc:
        raise SinaNetworkError(f"新浪搜索失败: {exc}") from exc


def search(query: str) -> list[dict]:
    """返回 [{code, name, market, secid, type}]，已过滤掉场外基金等不可交易品种。"""
    query = query.strip()
    if not query:
        return []

    text = _fetch(_URL.format(key=urllib.parse.quote(query)))
    if '"' not in text:
        return []
    body = text.split('"', 2)[1]
    if not body:
        return []

    out: list[dict] = []
    for chunk in body.split(";"):
        parts = chunk.split(",")
        if len(parts) < 5:
            continue
        raw_name, type_code, code, full = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
        display_name = parts[4].strip() if len(parts) > 4 else ""
        pinyin = parts[5].strip() if len(parts) > 5 else ""
        if not code:
            continue
        # 按代码搜索时，第 0 段是带前缀的代码（sh600519），名称在第 4 段
        name = display_name if re.fullmatch(r"(sh|sz|bj|hk)?\d+", raw_name) and display_name else raw_name

        market = ""
        for prefix in ("sh", "sz", "bj", "hk"):
            if full.startswith(prefix):
                market = prefix
                full = full[len(prefix):]
                break
        if not market and len(code) == 5 and code.isdigit():  # 港股不带前缀
            market = "hk"

        if not market:  # of510300 之类（场外基金）直接丢掉
            continue

        out.append({
            "code": code,
            "name": name,
            "pinyin": pinyin,
            "market": market,
            "secid": f"{market}{code}",
            "type": _TYPE_NAME.get(type_code, type_code),
        })
    return out


def best_match(query: str) -> dict | None:
    """代码全等 > 名称全等 > A 股 > 场内基金 > 港股 > 原顺序。"""
    items = search(query)
    if not items:
        return None

    def score(rank: int, item: dict) -> tuple:
        return (
            0 if item["code"] == query else 1,
            0 if item["name"] == query else 1,
            _TYPE_RANK.get({"A股": "11", "港股": "31", "沪基金": "203", "深基金": "204"}.get(item["type"], ""), 9),
            rank,
        )

    return min(((i, it) for i, it in enumerate(items)), key=lambda p: score(p[0], p[1]))[1]


def kline(code: str, days: int = 250) -> "pd.DataFrame":
    """日线（覆盖北交所，腾讯对北交所只给 1 根）。

    新浪只给成交量（单位：股），成交额按 `量 × (高+低+收)/3` 估算，
    与 tq.kline 的估算口径一致，够用于「日均成交 1.5 亿」这类粗阈值。
    """
    import pandas as pd

    sym = _symbol(code)
    url = (_KLINE_URL.format(symbol=sym, n=max(int(days), 250)))
    text = _fetch(url)
    if not text or text.strip() in ("null", "[]"):
        raise SinaError(f"新浪没有 {code} 的日线数据")

    rows = json.loads(text)
    if not rows:
        raise SinaError(f"新浪没有 {code} 的日线数据")

    df = pd.DataFrame(rows)
    df = df.rename(columns={"day": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["amount"] = df["volume"] * (df["high"] + df["low"] + df["close"]) / 3
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]


def _symbol(code: str) -> str:
    """'920566' -> 'bj920566'，'600519' -> 'sh600519'，港股新浪日线不提供。"""
    text = str(code).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            return text
    if len(text) == 5 and text.isdigit():
        raise SinaError("新浪日线不提供港股数据")
    if text.startswith(("43", "83", "87", "92")):  # 北交所
        return "bj" + text
    return ("sh" if text.startswith(("6", "5", "9", "11")) else "sz") + text
