"""东方财富行情（免费、无需 key、覆盖比 baostock 宽）。

baostock 只认沪深 A 股：北交所（43/83/87/92 开头，现已大量迁到 920 开头）、
沪市 ETF/LOF（51x/58x）、可转债、港股（00700 这类 5 位代码）都查不到，
所以「能买的票加不进自选」根子在数据源，不在匹配逻辑。

这里用东财的公开接口补上这一层：

- 搜索：`searchapi.eastmoney.com/api/suggest/get` —— 代码/名称/拼音都能搜，
  返回 `MktNum`（市场号）+ `SecurityTypeName`（品种）
- 快照：`push2.eastmoney.com/api/qt/stock/get` —— 现价/昨收/涨跌幅
- 日线：`push2his.eastmoney.com/api/qt/stock/kline/get` —— `fqt=1` 前复权，
  与 baostock 的 `adjustflag=2` 同口径

市场号：0=深/北，1=沪，116=港股。

接口没有文档，字段靠实测（见 README）。任何一步失败都抛 `EastmoneyError`，
由 fetcher 决定是否回落到 baostock。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

#: 允许加入自选/持仓的品种（其他的都是美股、期货、期权之类，行情口径对不上）
_ALLOED_TYPES = {"沪A", "深A", "京A", "沪B", "深B", "港股", "基金", "债券", "指数"}

#: A 股优先：同样的搜索词命中多只时，先给 A 股
_TYPE_RANK = {"沪A": 0, "深A": 0, "京A": 0, "基金": 1, "债券": 1, "港股": 2,
              "沪B": 3, "深B": 3, "指数": 4}

_SEARCH_URL = ("https://searchapi.eastmoney.com/api/suggest/get"
               "?input={kw}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count={n}")
_QUOTE_URL = ("https://push2.eastmoney.com/api/qt/stock/get?secid={secid}"
              "&fields=f43,f57,f58,f59,f60,f47,f48,f170")
_KLINE_URL = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
              "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
              "&klt=101&fqt=1&end=20500101&lmt={lmt}")


class EastmoneyError(RuntimeError):
    """东财接口返回了空数据（这只票没有，或字段不认识）。"""


class EastmoneyNetworkError(EastmoneyError):
    """东财接口连不上（被限流 / 断网）。只有这类错误才该把整个源标记为不可用。"""


def _get_json(url: str) -> dict:
    last: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # 网络抖动重试一次
            last = exc
            time.sleep(0.3)
    raise EastmoneyNetworkError(f"东财接口请求失败: {last}")


def is_hk(code: str) -> bool:
    """港股代码是 5 位数字（00700），A 股/基金/债券都是 6 位。"""
    return len(code) == 5 and code.isdigit()


def mkt_of(code: str) -> str:
    """按代码推断市场号：0=深/北，1=沪，116=港股。"""
    code = _norm(code)
    if is_hk(code):
        return "116"
    if code.startswith("92"):  # 北交所新号段（老号段 43/83/87 也是北交所，落到下面的 0）
        return "0"
    if code.startswith(("6", "5", "9", "11")):  # 沪主板/科创、沪基金、沪B、沪转债
        return "1"
    return "0"


def secid(code: str, mkt: str | None = None) -> str:
    """'600519' -> '1.600519'；港股 '00700' -> '116.00700'。"""
    code = _norm(code)
    return f"{mkt or mkt_of(code)}.{code}"


def _norm(code: str) -> str:
    """去掉 sh./sz./bj./hk. 前缀，保留原始位数（港股 5 位不能补零成 6 位）。"""
    text = str(code).strip().lower()
    for prefix in ("sh.", "sz.", "bj.", "hk."):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def search(query: str, limit: int = 10) -> list[dict]:
    """按代码/名称/拼音搜索，返回 [{code, name, mkt, type, secid}]。

    只保留能当「股票」分析的品种；同分时 A 股排前面。
    """
    query = query.strip()
    if not query:
        return []
    data = _get_json(_SEARCH_URL.format(kw=urllib.parse.quote(query), n=limit))
    table = data.get("QuotationCodeTable") or {}
    items = table.get("Data") or []

    out: list[dict] = []
    for item in items:
        sec_type = (item.get("SecurityTypeName") or "").strip()
        if sec_type not in _ALLOED_TYPES:
            continue
        code = str(item.get("Code") or "").strip()
        if not code or not item.get("MktNum"):
            continue
        out.append({
            "code": code,
            "name": (item.get("Name") or "").strip(),
            "pinyin": (item.get("PinYin") or "").strip(),
            "mkt": str(item.get("MktNum")),
            "type": sec_type,
            "secid": f"{item['MktNum']}.{code}",
        })
    return out


def best_match(query: str) -> dict | None:
    """把搜索结果排成「最可能是用户想要的那只」。

    优先级：代码完全一致 > 名称完全一致 > A 股 > 其他品种 > 原顺序。
    """
    items = search(query)
    if not items:
        return None

    def score(rank: int, item: dict) -> tuple:
        same_code = 0 if item["code"] == query else 1
        same_name = 0 if item["name"] == query else 1
        return (same_code, same_name, _TYPE_RANK.get(item["type"], 9), rank)

    return min(((i, it) for i, it in enumerate(items)), key=lambda p: score(p[0], p[1]))[1]


def quote(code: str, mkt: str | None = None) -> dict:
    """最新快照。价格按接口返回的小数位数（f59）还原，ETF/港股不会被放大 10 倍。"""
    data = _get_json(_QUOTE_URL.format(secid=secid(code, mkt)))
    d = data.get("data") or {}
    if not d or d.get("f43") in ("-", None):
        raise EastmoneyError(f"东财没有 {code} 的实时报价（可能停牌或代码不存在）")

    scale = 10 ** int(d.get("f59") or 2)
    raw = d.get("f43")
    price = raw / scale if isinstance(raw, (int, float)) else float(raw)
    pct = d.get("f170")
    pct = pct / 100 if isinstance(pct, (int, float)) else 0.0
    return {
        "name": (d.get("f58") or "").strip(),
        "price": round(float(price), 4),
        "pct_change": float(pct),
    }


def kline(code: str, days: int = 250, mkt: str | None = None) -> pd.DataFrame:
    """前复权日线。列：date, open, high, low, close, volume, amount。

    volume 单位是**手**（baostock 是股），只影响绝对值；量比/均量比都是比值，口径不变。
    """
    lmt = max(int(days), 250)  # 多拿一些，MA250 才有值
    data = _get_json(_KLINE_URL.format(secid=secid(code, mkt), lmt=lmt))
    d = data.get("data") or {}
    rows = d.get("klines") or []
    if not rows:
        raise EastmoneyError(f"东财没有 {code} 的日线数据")

    recs = []
    for row in rows:
        parts = row.split(",")
        if len(parts) < 7:
            continue
        recs.append(parts[:7])

    df = pd.DataFrame(recs, columns=["date", "open", "close", "high", "low", "volume", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]
