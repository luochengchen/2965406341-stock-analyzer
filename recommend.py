"""每日推荐：从股票池里挑 3 只「稳健」+ 3 只「激进」。

放在哪：结果落 `<软件目录>/data/recommend.json`，按自然日缓存，同一天只算一次。
怎么算：拿每个候选最近 250 个交易日的日线 → 算指标 → 生成一份「当天快照指标」→
       用两套打分分别排序 → 头部再补买点/止损/目标价和理由。
多慢：85 只票 × 约 0.4 秒 ≈ 30~50 秒，所以放后台线程算，前端轮询进度，算完落盘。

为什么用固定股票池而不是全市场：baostock 是逐只拉日线的，全市场 5000+ 只按 0.4 秒算要
半小时，放进 Web 服务里没法用。这里挑的是流动性最好、覆盖面够的一批主流标的
（沪深主板 + 创业板 + 科创板代表股），叠加用户自选，兼顾速度和代表性。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date

from indicators import calc_all
from positions import PositionCalculator
from snapshot import num as _num, snap as _snapshot

DATA_DIR = os.environ.get("STOCK_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
)
CACHE_FILE = os.path.join(DATA_DIR, "recommend.json")

# 推荐池：代码 -> 别名（只做兜底名字，真实名称以 baostock 为准，ST 也按它过滤）
UNIVERSE: list[str] = [
    # 银行 / 保险 / 券商
    "600036", "601398", "601288", "601988", "601166", "601318", "601601",
    "600030", "601688", "300059",
    # 白酒 / 食品 / 家电 / 免税
    "600519", "000858", "000568", "600809", "002304", "603288", "600887",
    "000895", "601888", "000333", "000651", "600690",
    # 医药
    "600276", "300760", "603259", "000538", "600196", "300015",
    # 新能源 / 电力设备
    "300750", "002594", "601012", "300274", "002460", "600438", "600089", "300124",
    # 半导体 / 电子
    "688981", "603501", "002371", "603986", "688012", "002415", "000725",
    "002475", "002241",
    # 计算机 / 通信 / 传媒
    "002230", "300308", "300502", "000063", "600050", "601138", "688111", "002027",
    # 汽车 / 军工
    "601633", "600104", "000625", "601127", "002050", "600760", "600893", "002179",
    # 资源 / 周期 / 基建
    "601899", "603993", "600111", "601088", "600028", "601857", "600585",
    "600019", "601668",
    # 公用 / 机械 / 地产 / 农业 / 交运
    "600900", "601985", "600031", "000157", "000002", "600048",
    "002714", "002352", "601919", "600233",
]

# 后台任务状态（单例，一次只跑一个）
_JOB = {"running": False, "done": 0, "total": 0, "error": None, "started_at": None}
_JOB_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def _limit_pct(code: str) -> float:
    """涨跌停幅度：创业板/科创板 20%，北交所 30%，其余 10%。"""
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("43", "83", "87", "88", "92")):
        return 30.0
    return 10.0


def _strip_verdict(text: str) -> str:
    """把 '[多] 偏多 -- 可考虑入场' 压成 '偏多 -- 可考虑入场'。"""
    if not text:
        return ""
    return text.split("]", 1)[-1].strip() if text.startswith("[") else text


# ---------------------------------------------------------------------------
# 两套打分（每一项都记录「过没过 + 实际数值」，前端可以摊开给用户看）
# ---------------------------------------------------------------------------

def _f(label: str, value: str, points: float, hit: bool) -> dict:
    """一条打分项。命中得 points（可为负），没命中得 0。"""
    return {
        "label": label,
        "value": value,
        "weight": _r(points, 1),
        "points": _r(points, 1) if hit else 0.0,
        "hit": bool(hit),
    }


def _conservative_score(s: dict) -> tuple[float, list[dict]]:
    """稳健：趋势向上、波动小、不追高、流动性够。"""
    f: list[dict] = []

    if s["ma60"] > 0 and s["close"] > s["ma60"]:
        f.append(_f("站上 MA60（中期趋势向上）", f"MA60 {s['ma60']:.2f}", 1.2, True))
    elif s["ma60"] > 0:
        f.append(_f("跌破 MA60（扣分）", f"MA60 {s['ma60']:.2f} / 现价 {s['close']:.2f}", -1.0, True))
    else:
        f.append(_f("站上 MA60（中期趋势向上）", "MA60 数据不足", 0, False))

    f.append(_f(
        "MA20 在 MA60 上方（均线逐级抬高）",
        f"MA20 {s['ma20']:.2f} / MA60 {s['ma60']:.2f}",
        1.0, s["ma20"] > 0 and s["ma20"] > s["ma60"],
    ))

    f.append(_f(
        "MA60 在 MA120 上方（中期趋势确认）",
        f"MA60 {s['ma60']:.2f} / MA120 {s['ma120']:.2f}",
        0.7, s["ma120"] > 0 and s["ma60"] > s["ma120"],
    ))

    if s["ma250"] > 0 and 0 < s["dist_ma250"] <= 30:
        f.append(_f("高出年线但不夸张（0~30%）", f"距年线 {s['dist_ma250']:+.1f}%", 0.7, True))
    elif s["ma250"] > 0 and s["dist_ma250"] < 0:
        f.append(_f("跌破年线（扣分）", f"距年线 {s['dist_ma250']:+.1f}%", -1.2, True))
    else:
        f.append(_f("高出年线但不夸张（0~30%）", f"距年线 {s['dist_ma250']:+.1f}%", 0.7, False))

    if s["atr_pct"] <= 2.5:
        f.append(_f("日波动 ≤ 2.5%（走得稳）", f"{s['atr_pct']:.1f}%", 1.0, True))
    elif s["atr_pct"] <= 3.5:
        f.append(_f("日波动 ≤ 3.5%", f"{s['atr_pct']:.1f}%", 0.5, True))
    elif s["atr_pct"] > 5:
        f.append(_f("日波动 > 5%（扣分，不够稳）", f"{s['atr_pct']:.1f}%", -1.2, True))
    else:
        f.append(_f("日波动 ≤ 2.5%（走得稳）", f"{s['atr_pct']:.1f}%", 1.0, False))

    f.append(_f("20 日涨幅在 -6%~15%（不追高也不破位）",
                f"{s['chg20']:+.1f}%", 0.6, -6 <= s["chg20"] <= 15))

    f.append(_f("20 日回撤 ≥ -8%（没有大起大落）", f"{s['dd20']:.1f}%", 0.5, s["dd20"] >= -8))

    f.append(_f("日均成交 ≥ 3 亿（流动性充足）",
                f"{s['amount20'] / 1e8:.1f} 亿", 0.3, s["amount20"] >= 3e8))

    f.append(_f("RSI ≤ 70（不算超买）", f"{s['rsi']:.1f}", 0.3, s["rsi"] <= 70))

    f.append(_f("量比 ≤ 1.8（没有异常放量）", f"{s['vol_ratio']:.2f}", 0.4, s["vol_ratio"] <= 1.8))

    return sum(x["points"] for x in f), f


def _aggressive_score(s: dict) -> tuple[float, list[dict]]:
    """激进：短期动能强、放量、突破，能接受更大波动。"""
    f: list[dict] = []

    mom5 = max(-1.0, min(1.0, s["chg5"] / 8))
    mom20 = max(-1.0, min(1.0, s["chg20"] / 25))
    f.append(_f("近 5 日动能", f"{s['chg5']:+.1f}%", mom5 * 1.2, mom5 > 0))
    f.append(_f("近 20 日动能", f"{s['chg20']:+.1f}%", mom20 * 1.2, mom20 > 0))

    f.append(_f("收盘站上 20 日高点（突破形态）",
                f"20 日高 {s['high20']:.2f} / 现价 {s['close']:.2f}", 1.2, s["breakout20"]))

    if s["vol_ratio"] >= 1.4:
        f.append(_f("明显放量（量比 ≥ 1.4）", f"{s['vol_ratio']:.2f}", 1.0, True))
    elif s["vol_ratio"] >= 1.15:
        f.append(_f("温和放量（量比 ≥ 1.15）", f"{s['vol_ratio']:.2f}", 0.5, True))
    else:
        f.append(_f("放量（量比 ≥ 1.4）", f"{s['vol_ratio']:.2f}", 1.0, False))

    f.append(_f("MA5>MA10>MA20（短线多头排列）",
                f"MA5 {s['ma5']:.2f} / MA10 {s['ma10']:.2f} / MA20 {s['ma20']:.2f}",
                0.8, s["ma5"] > s["ma10"] > s["ma20"] > 0))

    if s["rsi"] > 80:
        f.append(_f("RSI > 80（过热扣分）", f"{s['rsi']:.1f}", -1.2, True))
    elif 55 <= s["rsi"] <= 75:
        f.append(_f("RSI 在 55~75（强势不极端）", f"{s['rsi']:.1f}", 0.3, True))
    else:
        f.append(_f("RSI 在 55~75（强势不极端）", f"{s['rsi']:.1f}", 0.3, False))

    if 2.5 <= s["atr_pct"] <= 7:
        f.append(_f("日波动 2.5%~7%（弹性够、没失控）", f"{s['atr_pct']:.1f}%", 0.6, True))
    elif s["atr_pct"] > 9:
        f.append(_f("日波动 > 9%（扣分，太野）", f"{s['atr_pct']:.1f}%", -1.0, True))
    else:
        f.append(_f("日波动 2.5%~7%（弹性够、没失控）", f"{s['atr_pct']:.1f}%", 0.6, False))

    f.append(_f("20 日回撤 ≥ -4%（没在高位横盘回落）", f"{s['dd20']:.1f}%", 0.4, s["dd20"] >= -4))

    f.append(_f("近 20 日量能高于 60 日均量（资金在进场）",
                f"{s['vol20_60']:.2f}", 0.4, s["vol20_60"] >= 1.2))

    return sum(x["points"] for x in f), f


# 给前端「筛选逻辑」面板用的说明（文案与上面的代码一一对应）
LOGIC: dict = {
    "pool": "候选池 = 内置 84 只主流标的（银行/白酒/医药/新能源/半导体/汽车/军工/资源/公用等）"
            "+ 你自己加的自选股",
    "filters": [
        "剔除 ST、退市整理股",
        "剔除日均成交额 < 1.5 亿的（买不进卖不出）",
        "剔除当日涨停/跌停的（买不进、或者已经跌停）",
        "剔除北交所（波动与流动性规则不同）",
        "稳健额外剔除：日波动 > 5%、5 日涨幅 > 20%",
        "激进额外剔除：5 日涨幅 > 25%、日波动 > 9%、当日涨幅 > 5%、RSI > 80、短线评分为明显偏空",
    ],
    "scorers": {
        "conservative": "稳健分：均线结构（站上 MA60 / MA20>MA60 / MA60>MA120）+ 高于年线但不夸张 "
                        "+ 低波动 + 20 日不追高不破位 + 回撤小 + 流动性 + 不超买 + 不异常放量",
        "aggressive": "激进分：5 日/20 日动能 + 突破 20 日高 + 放量 + 短线均线多头排列 "
                      "+ RSI 强势区 + 弹性适中 + 回撤小 + 资金进场",
    },
    "rank": "按总分从高到低排序，同分再看成交额，各取前 3；稳健选出的票不会重复出现在激进里",
    "note": "分数是各项分值的加总，点开任意推荐的「为什么」可以看到这只票逐条过没过、拿了多少分。",
}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _cached() -> dict | None:
    """读当天缓存；日期不符/文件坏了就当作没有。"""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("for_date") != date.today().isoformat():
        return None
    if not data.get("conservative") and not data.get("aggressive"):
        return None
    # 旧版缓存没有逐项打分明细（factors），当过期处理，等重算
    for item in (data.get("conservative") or []) + (data.get("aggressive") or []):
        if "factors" not in item:
            return None
    return data


def _write_cache(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    # 带 pid 的临时名：多 worker 各自算的时候不会互相踩同一个 tmp 文件
    tmp = f"{CACHE_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_FILE)


def _pool() -> list[str]:
    """推荐池 = 内置池 + 用户自选（去重保序）。"""
    codes = list(UNIVERSE)
    try:
        from portfolio import get_all_stocks
        for entry in get_all_stocks():
            if entry.get("code") and entry["code"] not in codes:
                codes.append(entry["code"])
    except Exception:
        pass
    return codes


def _deep(df, name: str) -> dict:
    """对入围股补一层深度信息：短线/长线评分、买点、止损、目标价。"""
    from analyzer import LongTermAnalyzer, ShortTermAnalyzer

    short = ShortTermAnalyzer(df, name, "").analyze()
    long_ = LongTermAnalyzer(df, name, "").analyze()
    levels = PositionCalculator(df, short["supports"], short["resistances"]).calculate_all()

    stop = _num(levels["stop_loss"]["price"])
    add = [_num(x["price"]) for x in levels["add_position"]]
    take = [_num(x["price"]) for x in levels["take_profit"]]
    close = _num(df["close"].iloc[-1])
    buy = add[0] if add and 0 < add[0] < close else close

    # 价位兜底：止损必须低于现价，且至少比买入参考位低 3%（贴着买点止损没意义）；
    # 目标必须比现价高至少 2%（最近压力位太近就没参考价值）
    if 0 < stop < close:
        stop = min(stop, buy * 0.97)
    else:
        stop = buy * 0.95
    above = [p for p in take if p > close * 1.02]
    target = above[0] if above else close * 1.08

    return {
        "short_score": _r(short["total_score"], 1),
        "short_verdict": _strip_verdict(short["verdict"]),
        "long_score": _r(long_["total_score"], 1),
        "long_verdict": _strip_verdict(long_["verdict"]),
        "buy_point": _r(buy),
        "stop_loss": _r(stop),
        "target": _r(target),
    }


def _run() -> None:
    """后台线程主体：拉数据 → 打分 → 选出 3+3 → 落盘。"""
    global _JOB
    started = time.time()
    failed: list[dict] = []
    try:
        from fetcher import fetch_daily_kline, fetch_stock_basic_map

        names = fetch_stock_basic_map()
        pool = _pool()
        with _JOB_LOCK:
            _JOB.update({"done": 0, "total": len(pool), "error": None})

        rows: list[tuple[dict, object]] = []
        data_date = ""
        for idx, code in enumerate(pool, 1):
            try:
                df = fetch_daily_kline(code, 250)
                df = calc_all(df)
                name = names.get(code, code)
                snap = _snapshot(df, code, name)
                if not snap:
                    raise ValueError("快照指标为空")
                if not data_date:
                    data_date = str(df["date"].iloc[-1])[:10]
                rows.append((snap, df))
            except Exception as exc:  # 单只失败不影响整体
                failed.append({"code": code, "error": str(exc)[:120]})
            with _JOB_LOCK:
                _JOB["done"] = idx

        conservative = _pick(rows, _conservative_score, "conservative")
        aggressive = _pick(rows, _aggressive_score, "aggressive",
                           exclude={x["code"] for x in conservative})

        payload = {
            "for_date": date.today().isoformat(),
            "data_date": data_date,
            "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            "elapsed_sec": round(time.time() - started, 1),
            "universe": len(pool),
            "ok_count": len(rows),
            "failed_count": len(failed),
            "conservative": conservative,
            "aggressive": aggressive,
        }
        _write_cache(payload)
        with _JOB_LOCK:
            _JOB.update({"running": False, "done": len(pool), "total": len(pool)})
    except Exception as exc:
        with _JOB_LOCK:
            _JOB.update({"running": False, "error": f"{type(exc).__name__}: {exc}"})


def _pick(rows, scorer, kind: str, exclude: set[str] | None = None) -> list[dict]:
    """按指定打分函数排序，过滤掉不能买的，取前 3。"""
    exclude = exclude or set()
    scored = []
    for snap, df in rows:
        code = snap["code"]
        if code in exclude:
            continue
        name = snap["name"] or code
        if "ST" in name.upper() or "退" in name:
            continue
        if snap["amount20"] < 1.5e8:  # 日均成交 < 1.5 亿，流动性不足
            continue
        limit = _limit_pct(code)
        if snap["pct"] >= limit * 0.97:   # 涨停买不进
            continue
        if snap["pct"] <= -limit * 0.97:
            continue
        if code.startswith(("43", "83", "87", "88", "92")):  # 北交所，波动/流动性另算
            continue
        if kind == "conservative":
            if snap["atr_pct"] > 5.0 or snap["chg5"] > 20:
                continue
        else:
            # 激进不等于追高：单日冲太猛、RSI 极端、5日涨幅过大都排除
            if snap["chg5"] > 25 or snap["atr_pct"] > 9:
                continue
            if snap["pct"] > 5 or snap["rsi"] > 80:
                continue

        score, factors = scorer(snap)
        hits = sorted((x for x in factors if x["hit"] and x["points"] > 0),
                      key=lambda x: x["points"], reverse=True)
        reasons = [f"{x['label']} · {x['value']}" for x in hits[:3]]

        try:
            extra = _deep(df, name)
        except Exception:
            extra = {}

        # 激进票必须短线不偏空，否则「激进推荐 + 短线偏空」自相矛盾
        if kind == "aggressive" and extra.get("short_score", 0) <= -1.0:
            continue

        scored.append({
            "code": code,
            "name": name,
            "price": _r(snap["close"]),
            "pct": _r(snap["pct"]),
            "chg5": _r(snap["chg5"]),
            "chg20": _r(snap["chg20"]),
            "score": _r(score, 1),
            "vol_ratio": _r(snap["vol_ratio"]),
            "atr_pct": _r(snap["atr_pct"]),
            "rsi": _r(snap["rsi"], 1),
            "amount20": _r(snap["amount20"] / 1e8),  # 亿元
            "reasons": reasons,
            "factors": factors,
            "risk": _risk_note(kind, snap),
            **extra,
        })

    scored.sort(key=lambda x: (x["score"], x["amount20"]), reverse=True)
    return scored[:3]


def _risk_note(kind: str, s: dict) -> str:
    if kind == "conservative":
        if s["atr_pct"] <= 2.5:
            return "低波动品种，跌破MA60或止损位再走"
        return "波动略大，仓位别一次打满"
    if s["rsi"] >= 75:
        return "短线已偏热，只做快进快出，跌破买点就撤"
    if s["atr_pct"] >= 5:
        return "波动大，严格按止损位执行，别扛单"
    return "弹性品种，追高需设好止损，次日冲高不追"


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def get_recommendations(force: bool = False) -> dict:
    """给前端的统一出口。

    status:
      done    - data 里是今天的推荐
      running - 正在后台算，progress 给进度，稍后再来
      error   - 出错，error 里有原因
      empty   - 还没有结果
    """
    if force:
        # 强制刷新：清掉旧缓存与上一次的错误，重新排队
        with _JOB_LOCK:
            _JOB["error"] = None
        try:
            os.remove(CACHE_FILE)
        except OSError:
            pass
    else:
        cached = _cached()
        if cached:
            return {"status": "done", "data": cached, "progress": _progress()}

    with _JOB_LOCK:
        running = _JOB["running"]
        error = _JOB["error"]
        started_at = _JOB.get("started_at")
        if not running and error:
            return {"status": "error", "data": None, "error": error, "progress": _progress()}

    # 线程跟着进程走：进程重启过（或线程意外死掉）会留下「永远 running」，超过 20 分钟就当失败
    if running and started_at:
        try:
            age = time.time() - time.mktime(time.strptime(started_at, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            age = 0
        if age > 1200:
            with _JOB_LOCK:
                _JOB.update({"running": False,
                             "error": "上一次计算超过 20 分钟没有结果，请点「刷新」重试"})
            running = False

    if not running:
        start_job()

    cached = _cached()
    if cached:
        return {"status": "done", "data": cached, "progress": _progress()}

    return {"status": "running", "data": None, "progress": _progress(), "error": None}


def start_job() -> None:
    with _JOB_LOCK:
        if _JOB["running"]:
            return
        _JOB.update({
            "running": True, "done": 0, "total": len(_pool()),
            "error": None, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    threading.Thread(target=_run, name="recommend-job", daemon=True).start()


def _progress() -> dict:
    with _JOB_LOCK:
        return {
            "running": _JOB["running"],
            "done": _JOB["done"],
            "total": _JOB["total"],
            "error": _JOB["error"],
            "started_at": _JOB["started_at"],
        }
