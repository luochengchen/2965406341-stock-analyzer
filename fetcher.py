"""行情数据入口：多源自动降级。

为什么不是单一的 baostock：

- baostock 只认**沪深 A 股**。北交所（43/83/87/92 开头，现已大量迁到 920 开头）、
  沪市 ETF/LOF（51x/58x）、可转债、港股（00700 这类 5 位代码）一律查不到 ——
  「能买的票加不进自选」根子在数据源，不在匹配逻辑。
- baostock 用进程级全局 socket，空闲久了被服务端断开（详见 `BaostockError`）。
- 单只 250 日线在 baostock 上要 2~7 秒，腾讯/东财约 0.15 秒。

所以这里按「覆盖广、快、稳」排序组合：

| 用途 | 首选 | 兜底 1 | 兜底 2 |
|---|---|---|---|
| 代码/名称 → 股票 | 新浪 suggest（覆盖最全，还能把北交所老代码换成新代码） | 东财 suggest | baostock |
| 日线 | 东财（带真实成交额） | 腾讯（成交额估算） | baostock |
| 最新价 | 腾讯 | 东财 | baostock |

任一源连续失败会被标记 5 分钟不再优先使用；调用方只看到「慢了一下」。
"""
from __future__ import annotations

import contextlib
import datetime
import os
import threading
import time

import baostock as bs
import pandas as pd

import em
import sina
import tq
from codes import norm_code as _norm_code

# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class FetchError(RuntimeError):
    """行情接口整体不可用（所有源都失败）。

    调用方应提示「行情接口暂时连不上，请稍后重试」，**不要**说成「没有这只股票」。
    """


#: 旧名字，保留兼容（web_app / 历史代码都在用它判断「接口断了」）
BaostockError = FetchError


class BaostockSessionError(FetchError):
    """baostock 返回了错误码：多半是连接空闲太久被服务端断开，`_logged_in` 却还是 True。"""


# ---------------------------------------------------------------------------
# 多源健康检查
# ---------------------------------------------------------------------------

_DOWN: dict[str, float] = {}
_COOLDOWN = 300.0


def _is_down(name: str) -> bool:
    ts = _DOWN.get(name)
    return bool(ts and time.time() - ts < _COOLDOWN)


def _mark_down(name: str) -> None:
    _DOWN[name] = time.time()


def _mark_up(name: str) -> None:
    _DOWN.pop(name, None)


def source_status() -> dict[str, bool]:
    """各数据源当前是否可用（前端/调试用）。"""
    return {
        "eastmoney": not _is_down("em"),
        "tencent": not _is_down("tq"),
        "sina": not _is_down("sina"),
        "baostock": not _is_down("bs"),
    }


# ---------------------------------------------------------------------------
# baostock 连接管理
# ---------------------------------------------------------------------------

_logged_in = False
_lock = threading.RLock()

# 全市场代码 -> 名称，按自然日缓存（推荐池一次要用 80+ 个名字）
_basic_map: dict[str, str] = {}
_basic_map_date = ""


def _rows(rs, what: str) -> list[list[str]]:
    """把一次查询的结果行读干净；错误码非 0 一律抛 BaostockSessionError。"""
    if getattr(rs, "error_code", "0") != "0":
        raise BaostockSessionError(f"{what}失败: {rs.error_msg}（code={rs.error_code}）")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return rows


def _query(fn, what: str):
    """执行一次 baostock 查询；遇到连接层错误就先重连再试一次。"""
    global _logged_in
    try:
        with _session():
            return fn()
    except BaostockSessionError:
        with _lock:
            try:
                if _logged_in:
                    bs.logout()
            except Exception:
                pass
            _logged_in = False
        with _session():
            return fn()


def _basic_rows(**kwargs) -> list[list[str]]:
    """query_stock_basic 的封装：返回 [[full_code, name, ipo, out, type, status], ...]。"""
    return _query(lambda: _rows(bs.query_stock_basic(**kwargs), "查询股票基本信息"), "股票基本信息")


def _ensure_login() -> None:
    """确保 baostock 已登录（调用方需持有 _lock）。"""
    global _logged_in
    if _logged_in:
        return
    lg = bs.login()
    if lg.error_code != "0":
        raise FetchError(f"Baostock 登录失败: {lg.error_msg}")
    _logged_in = True


@contextlib.contextmanager
def _session():
    """独占 baostock 连接的上下文：进入时保证已登录，退出时释放锁。"""
    global _logged_in
    with _lock:
        _ensure_login()
        try:
            yield
        except Exception:
            _logged_in = False
            raise


def _logout() -> None:
    """Logout from baostock."""
    global _logged_in
    with _lock:
        if _logged_in:
            bs.logout()
            _logged_in = False


# ---------------------------------------------------------------------------
# 代码规范化
# ---------------------------------------------------------------------------

def norm_code(code: str) -> str:
    """统一股票代码（实现见 `codes.norm_code`，这里保留同名入口给老代码用）。"""
    return _norm_code(code)


def market_prefix(code: str) -> str:
    """代码 -> 市场前缀（sh / sz / bj / hk）。"""
    return tq.symbol_of(norm_code(code))[:2]


def full_code(code: str) -> str:
    """代码 -> 'sh.600519' 形式。"""
    code = norm_code(code)
    if "." in code:
        return code
    return f"{market_prefix(code)}.{code}"


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def resolve_stock_code(query: str) -> tuple[str, str]:
    """代码 / 名称 / 拼音 -> (code, name)。

    依次尝试新浪、东财、baostock，任何一源成功即返回。三源都失败时：
    - 至少一个是网络错误 → 抛 FetchError（调用方提示「稍后重试」）
    - 所有源都正常但都没找到 → 抛 ValueError（确实没这只票）
    """
    query = str(query).strip()
    if not query:
        raise ValueError("股票代码或名称不能为空")

    # 允许直接粘 `sh600519` / `sz000001` 这样的带前缀代码
    if len(query) > 2 and query[:2].lower() in ("sh", "sz", "bj", "hk") and query[2:].isdigit():
        query = query[2:]

    broken: list[str] = []

    if not _is_down("sina"):
        try:
            hit = _pick_candidate(query, sina.search(query))
            _mark_up("sina")
            if hit:
                return norm_code(hit["code"]), hit["name"]
        except sina.SinaError as exc:
            broken.append(str(exc))
            if isinstance(exc, sina.SinaNetworkError):
                _mark_down("sina")

    if not _is_down("em"):
        try:
            hit = _pick_candidate(query, em.search(query))
            _mark_up("em")
            if hit:
                return norm_code(hit["code"]), hit["name"]
        except em.EastmoneyError as exc:
            broken.append(str(exc))
            if isinstance(exc, em.EastmoneyNetworkError):
                _mark_down("em")

    try:
        rows = _basic_rows(code=full_code(query)) if "." in query or query.isdigit() else []
        if rows:
            _mark_up("bs")
            return norm_code(rows[0][0]), rows[0][1]
        rows = _basic_rows(code_name=query)
        if rows:
            _mark_up("bs")
            return norm_code(rows[0][0]), rows[0][1]
    except Exception as exc:  # baostock 只覆盖沪深 A 股，查不到很正常
        broken.append(str(exc))

    if broken:
        raise FetchError(f"行情接口暂时不可用：{broken[0]}")

    raise ValueError(f"未找到匹配的股票: {query}，请检查代码或名称")


def _pick_candidate(query: str, items: list[dict]) -> dict | None:
    """从搜索结果里挑出真正该要的那一只。

    两件事：
    1. `_plausible` 过滤 —— 联想接口对 `zzzz` 也会硬凑结果，不校验就会「查无此股」变成别的票。
    2. **市场一致性** —— 新浪把上证指数 `000001` 和 A 股 `000001` 都标成「A股」，
       谁排在前面谁就是结果。数字代码必须落在它该在的市场（000001 只能是深市平安银行，
       不能是上证指数），否则用户加自选会莫名其妙变成指数。
    """
    candidates = [x for x in items if _plausible(query, x)]
    if not candidates:
        return None

    q = query.strip()
    if q.isdigit() and len(q) == 6:
        want = tq.symbol_of(q)[:2]
        same_market = [x for x in candidates if str(x.get("secid") or "")[:2] == want]
        if same_market:
            return same_market[0]
        # 000300 沪深300 这类指数挂在 sh，但 `mkt_of` 会按「000 开头 = 深市」判错，
        # 此时候选里只有它一个，就认它；多个候选又不能区分时宁可报未找到，别乱猜。
        if len(candidates) == 1:
            return candidates[0]
        return None
    return candidates[0]


def _plausible(query: str, item: dict) -> bool:
    """搜索结果是否真的对应这个查询。

    新浪/东财的联想接口对 `zzzz` 这类输入也会硬凑几条（能凑出「深证传媒」），
    不校验的话「不存在的代码」会莫名其妙变成一只不相干的股票。
    """
    code = str(item.get("code") or "")
    name = str(item.get("name") or "")
    pinyin = str(item.get("pinyin") or "").lower()
    kind = str(item.get("type") or "")
    q = query.strip().lower()

    if q.isdigit():
        if code.lstrip("0") == q.lstrip("0"):
            return True
        # 北交所老代码（43/83/87 开头）已迁到 92 开头，接口直接返回新代码
        return len(q) == 6 and q[0] in "48" and kind in ("A股", "沪A", "深A", "京A")

    if not q.isascii():  # 中文：要求互相包含
        return q in name or name in q

    # 纯字母：先排除「zzzz」「aaaa」这种无意义串——东财给「深证转债」的拼音正好是 ZZZZ
    if len(set(q)) < 2:
        return False
    if q in name.lower():
        return True
    # 拼音只用来匹配个股/基金，指数不参与（「深证转债」的拼音是 SZZZ）
    return (len(q) >= 4 and bool(pinyin) and pinyin.startswith(q)
            and kind not in ("指数", "板块", "概念"))


def _kline_baostock(code: str, days: int) -> pd.DataFrame:
    """baostock 日线（只有沪深 A 股）。"""
    full = full_code(code)
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=int(days * 1.8))).strftime("%Y-%m-%d")
    fields = "date,open,high,low,close,volume,amount,preclose"

    def _fetch() -> list[list[str]]:
        rs = bs.query_history_k_data_plus(
            full, fields, start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2",  # 前复权，与 em/tq 同口径
        )
        return _rows(rs, "获取 K 线")

    data = _query(_fetch, "K 线数据")
    if not data:
        raise FetchError(f"未获取到 {code} 的K线数据")

    df = pd.DataFrame(data, columns=fields.split(","))
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "amount", "preclose"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["close"].notna() & (df["close"] > 0)].copy()
    df = df.sort_values("date").tail(days).reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]


def fetch_daily_kline(symbol: str, days: int = 250) -> pd.DataFrame:
    """日线（前复权），列：date, open, high, low, close, volume, amount。

    自动降级：东财（真实成交额，全市场）→ 腾讯（估算成交额，沪深/北/港/ETF）
    → 新浪（估算成交额，补北交所）→ baostock（仅沪深 A 股）。

    某个源只返回几根 K 线（腾讯对北交所就是这样）时**继续试下一个源**，
    而不是直接报「样本不足」。
    行情一时取不到时抛 FetchError，调用方应提示「稍后重试」，不要当成「没有这只票」。
    """
    code = norm_code(symbol)
    cached = _read_cache(code, days)
    if cached is not None:
        return cached

    errors: list[str] = []
    shortest = 0

    sources = (
        ("em", "东财", em.kline, em.EastmoneyError, em.EastmoneyNetworkError),
        ("tq", "腾讯", tq.kline, tq.TencentError, tq.TencentNetworkError),
        ("sina", "新浪", sina.kline, sina.SinaError, sina.SinaNetworkError),
    )
    for key, label, loader, base_err, net_err in sources:
        if _is_down(key):
            continue
        try:
            df = loader(code, days)
        except base_err as exc:
            if isinstance(exc, net_err):
                _mark_down(key)
            errors.append(f"{label}: {exc}")
            continue

        _mark_up(key)
        if df is None or df.empty:
            errors.append(f"{label}: 数据为空")
            continue
        df = df.tail(max(days, 250)).reset_index(drop=True)
        if len(df) >= 30:
            _write_cache(code, days, df)
            return df
        shortest = max(shortest, len(df))
        errors.append(f"{label}: 只有 {len(df)} 根")

    if shortest:
        raise FetchError(f"{code} 只有 {shortest} 个交易日数据，不足以分析（需≥30天）")

    if not em.is_hk(code):
        try:
            df = _kline_baostock(code, days)
            _mark_up("bs")
            df = _finish_kline(df, code, days)
            _write_cache(code, days, df)
            return df
        except Exception as exc:
            _mark_down("bs")
            errors.append(f"baostock: {exc}")

    raise FetchError(f"取不到 {code} 的日线数据（{'；'.join(errors)}）")


# ---------------------------------------------------------------------------
# 日线缓存
# ---------------------------------------------------------------------------
# 为什么要落盘：策略页 / 持仓页 / 大师页 / 每日推荐会反复要同一只票的日线，
# 每次重拉会被东财、腾讯按 IP 限流（实测连续几十次后整站 501 / 断连）。
# 缓存 30 分钟：盘中刷新能拿到新数据，同时把请求量压到原来的几分之一。

CACHE_DIR = os.environ.get("STOCK_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_KLINE_CACHE = os.path.join(CACHE_DIR, "cache", "kline")
CACHE_TTL = 1800


def _cache_path(code: str, days: int) -> str:
    return os.path.join(_KLINE_CACHE, f"{code}_{max(int(days), 250)}.pkl")


def _read_cache(code: str, days: int) -> pd.DataFrame | None:
    path = _cache_path(code, days)
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL:
            return None
        return pd.read_pickle(path)
    except Exception:
        return None


def _write_cache(code: str, days: int, df: pd.DataFrame) -> None:
    path = _cache_path(code, days)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        df.to_pickle(tmp)
        os.replace(tmp, path)
    except Exception:
        pass  # 缓存失败不影响主流程


def _finish_kline(df: pd.DataFrame, code: str, days: int) -> pd.DataFrame:
    """统一收尾：按天数截断、样本太少直接报错。"""
    if df is None or df.empty:
        raise FetchError(f"{code} 的 K 线为空")
    df = df.tail(max(days, 250)).reset_index(drop=True)
    if len(df) < 30:
        raise FetchError(f"{code} 只有 {len(df)} 个交易日数据，不足以分析（需≥30天）")
    return df


def get_stock_info(symbol: str) -> dict:
    """最新价与涨跌幅（不落 K 线，快）。"""
    code = norm_code(symbol)
    errors: list[str] = []
    for name, fn in (("tq", tq.quote), ("em", em.quote)):
        if _is_down(name):
            continue
        try:
            info = fn(code)
            _mark_up(name)
            if info.get("price"):
                return info
        except Exception as exc:
            if type(exc).__name__.endswith("NetworkError"):
                _mark_down(name)
            errors.append(str(exc))

    if em.is_hk(code):  # baostock 没有港股，别白跑一趟
        raise FetchError(f"取不到 {code} 的报价（{'；'.join(errors)}）")

    # baostock 兜底：名称 + 最近两根收盘
    rows = _basic_rows(code=full_code(code))
    name = rows[0][1] if rows else code
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")

    def _fetch() -> list[list[str]]:
        rs = bs.query_history_k_data_plus(
            full_code(code), "date,close,preclose",
            start_date=start_date, end_date=end_date, frequency="d", adjustflag="2",
        )
        return _rows(rs, "获取最新价")

    price = pct = 0.0
    for row in _query(_fetch, "最新价"):
        if len(row) >= 3 and row[1] != "" and row[2] != "":
            close_val, preclose_val = float(row[1]), float(row[2])
            price = close_val
            pct = (close_val - preclose_val) / preclose_val * 100 if preclose_val > 0 else 0.0
    return {"name": name, "price": price, "pct_change": pct}


def fetch_stock_basic_map(force: bool = False) -> dict[str, str]:
    """全市场「代码 -> 名称」，按自然日缓存。

    推荐池要一次拿 80+ 只票的名字，逐只查太慢，这里用一次全量查询换掉。
    拿不到时返回空字典（调用方会退化成用代码当名字），不阻断推荐计算。
    """
    global _basic_map, _basic_map_date
    today = datetime.date.today().isoformat()
    if _basic_map and _basic_map_date == today and not force:
        return _basic_map

    try:
        rows = _query(lambda: _rows(bs.query_stock_basic(), "获取股票列表"), "股票列表")
    except Exception:
        return _basic_map or {}

    mapping = {norm_code(row[0]): row[1] for row in rows}
    _basic_map = mapping
    _basic_map_date = today
    return mapping


def latest_trading_date() -> str:
    """最近一个交易日（YYYY-MM-DD），用于标注「基于哪天收盘」。"""
    try:
        df = tq.kline("sh000001", 5)  # 上证指数，指数也能走腾讯日线
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        pass

    try:
        def _fetch() -> list[list[str]]:
            rs = bs.query_trade_dates(
                start_date=(datetime.date.today() - datetime.timedelta(days=15)).strftime("%Y-%m-%d"),
                end_date=datetime.date.today().strftime("%Y-%m-%d"),
            )
            return _rows(rs, "获取交易日历")

        latest = ""
        for row in _query(_fetch, "交易日历"):
            if len(row) >= 2 and row[1] == "1":
                latest = row[0]
        return latest
    except Exception:
        return datetime.date.today().isoformat()
