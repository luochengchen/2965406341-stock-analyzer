"""不同投资大师的「分析逻辑」：同一只股票，用八套方法论各打分一次。

为什么这么设计：推荐/筛选那套加权规则是个黑盒，用户看不出「为什么这只入选」。
这里把几种公开、可复述的经典方法论翻译成能算的技术面条件，每一条都给出「过没过」和
「实际数值」，用户能顺着条款自己判断，而不是只接受一个结论。

说明：这些大师的真实方法里还有大量财报、估值、产业判断，本项目只有行情数据，
所以这里只用「价格/成交量能表达出来的那部分」，属于近似，不冒充原教旨。
"""
from __future__ import annotations

from snapshot import snap


def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


# ---------------------------------------------------------------------------
# 大师定义
# 每条标准：(说明, 权重, 判定函数)，判定函数返回 (是否通过, 展示用数值文本)
# ---------------------------------------------------------------------------

MASTERS: list[dict] = [
    {
        "id": "buffett",
        "name": "沃伦·巴菲特",
        "school": "价值投资",
        "title": "护城河 · 长期持有",
        "motto": "以合理价格买入优秀公司，然后坐得住。",
        "philosophy": "不看短期波动，只问两件事：生意是不是长期向上、价格是不是没被炒高。"
                      "技术面上对应「站上年线、年线向上、波动可控、不处于加速冲顶阶段」。",
        "criteria": [
            ("站上年线（250 日线）", 2.0,
             lambda c: (c["dist_ma250"] > 0, f"距年线 {c['dist_ma250']:+.1f}%")),
            ("年线本身在向上走", 2.0,
             lambda c: (c["ma250_up"], "年线 20 日斜率向上" if c["ma250_up"] else "年线走平或向下")),
            ("没有偏离年线太远（不追高）", 1.5,
             lambda c: (0 < c["dist_ma250"] <= 40, f"高出年线 {c['dist_ma250']:.1f}%")),
            ("波动小，拿得住", 1.5,
             lambda c: (c["atr_pct"] <= 3.0, f"日波动 {c['atr_pct']:.1f}%")),
            ("20 日回撤可控", 1.5,
             lambda c: (c["dd20"] >= -12, f"距 20 日高 {c['dd20']:.1f}%")),
            ("60 日涨幅温和（稳步向上，不是爆发）", 1.5,
             lambda c: (0 <= c["chg60"] <= 40, f"60 日 {c['chg60']:+.1f}%")),
        ],
    },
    {
        "id": "graham",
        "name": "本杰明·格雷厄姆",
        "school": "安全边际",
        "title": "便宜 · 打折买",
        "motto": "安全边际是投资的中心思想。",
        "philosophy": "核心是「别买贵」。技术面上找的是：离 250 日低点不远、离高点明显回撤、"
                      "当日没有跳空追高、波动不吓人——价格已经打折，风险相对小。",
        "criteria": [
            ("离一年低点不远（没被炒过）", 2.0,
             lambda c: (c["dist_low250"] <= 25, f"高于年内低点 {c['dist_low250']:.1f}%")),
            ("离一年高点已有折扣", 2.0,
             lambda c: (c["dist_high250"] <= -20, f"距年内高点 {c['dist_high250']:.1f}%")),
            ("股价处在年线下方或贴近", 1.5,
             lambda c: (c["dist_ma250"] <= 5, f"距年线 {c['dist_ma250']:+.1f}%")),
            ("波动低，下跌空间有限", 1.5,
             lambda c: (c["atr_pct"] <= 2.5, f"日波动 {c['atr_pct']:.1f}%")),
            ("当日没有追高买入", 1.0,
             lambda c: (c["pct"] < 3, f"当日 {c['pct']:+.2f}%")),
            ("成交活跃度够（能进能出）", 2.0,
             lambda c: (c["amount20"] >= 3e8, f"日均成交 {c['amount20'] / 1e8:.1f} 亿")),
        ],
    },
    {
        "id": "lynch",
        "name": "彼得·林奇",
        "school": "成长投资",
        "title": "找成长 · 生活里发现",
        "motto": "买你了解的公司，让盈利增长替你赚钱。",
        "philosophy": "偏好「业绩在增长、股价还没疯」的中型成长股。技术面上对应：中期均线多头、"
                      "20/60 日有稳健涨幅、回撤不深、量能温和放大而不是爆量。",
        "criteria": [
            ("中期趋势向上（MA60 在 MA120 上方）", 2.0,
             lambda c: (c["ma60"] > c["ma120"] > 0, f"MA60 {c['ma60']:.2f} / MA120 {c['ma120']:.2f}")),
            ("20 日涨幅健康（3%~20%）", 2.0,
             lambda c: (3 <= c["chg20"] <= 20, f"20 日 {c['chg20']:+.1f}%")),
            ("60 日涨幅在成长区间（5%~40%）", 2.0,
             lambda c: (5 <= c["chg60"] <= 40, f"60 日 {c['chg60']:+.1f}%")),
            ("没有大幅回调", 1.5,
             lambda c: (c["dist_high250"] >= -15, f"距年内高 {c['dist_high250']:.1f}%")),
            ("量能温和放大（1.0~2.0 倍）", 1.5,
             lambda c: (1.0 <= c["vol_ratio"] <= 2.0, f"量比 {c['vol_ratio']:.2f}")),
            ("波动可接受", 1.0,
             lambda c: (c["atr_pct"] <= 3.5, f"日波动 {c['atr_pct']:.1f}%")),
        ],
    },
    {
        "id": "oneil",
        "name": "威廉·欧奈尔",
        "school": "CANSLIM",
        "title": "强势股 · 突破买入",
        "motto": "买创新高的股票，而不是捡便宜货。",
        "philosophy": "CANSLIM 的技术面部分：股价要突破平台、创近期新高、放量确认、均线多头排列，"
                      "同时不能已经过热（RSI 太高就变成接最后一棒）。",
        "criteria": [
            ("收盘创 20 日新高（突破平台）", 2.5,
             lambda c: (c["breakout20"], f"20 日高 {c['high20']:.2f} / 现价 {c['close']:.2f}")),
            ("均线多头排列 MA5>MA10>MA20", 2.0,
             lambda c: (c["ma5"] > c["ma10"] > c["ma20"] > 0,
                        f"MA5 {c['ma5']:.2f} / MA10 {c['ma10']:.2f} / MA20 {c['ma20']:.2f}")),
            ("放量确认（量比 ≥ 1.3）", 2.0,
             lambda c: (c["vol_ratio"] >= 1.3, f"量比 {c['vol_ratio']:.2f}")),
            ("RSI 在强势但不极端区（55~80）", 1.5,
             lambda c: (55 <= c["rsi"] <= 80, f"RSI {c['rsi']:.1f}")),
            ("距离一年新高不远（≤ 8%）", 1.5,
             lambda c: (c["dist_high250"] >= -8, f"距年内高 {c['dist_high250']:.1f}%")),
            ("20 日涨幅温和（5%~30%）", 0.5,
             lambda c: (5 <= c["chg20"] <= 30, f"20 日 {c['chg20']:+.1f}%")),
        ],
    },
    {
        "id": "livermore",
        "name": "杰西·利弗莫尔",
        "school": "趋势交易",
        "title": "关键点 · 顺势加码",
        "motto": "钱是坐着赚来的，不是靠交易赚来的。",
        "philosophy": "只做趋势明确的票，在「关键点」突破时进场，趋势没坏就一直持有。"
                      "技术面看：站上中期均线、突破 60 日高点、MA20 上翘、量价配合。",
        "criteria": [
            ("站上 MA60（趋势已转多）", 2.0,
             lambda c: (c["close"] > c["ma60"] > 0, f"MA60 {c['ma60']:.2f} / 现价 {c['close']:.2f}")),
            ("突破 60 日关键点", 2.5,
             lambda c: (c["breakout60"], f"60 日高 {c['high60']:.2f}")),
            ("MA20 向上翘", 2.0,
             lambda c: (c["ma20_up"], "MA20 高于 10 日前" if c["ma20_up"] else "MA20 走平或下弯")),
            ("量价配合（放量上行或缩量回调）", 1.5,
             lambda c: (c["vol_ratio"] >= 1.1 or c["pct"] < 0, f"量比 {c['vol_ratio']:.2f}")),
            ("没有跌破 20 日低点", 1.0,
             lambda c: (c["close"] > c["low20"], f"20 日低 {c['low20']:.2f}")),
            ("不是「放巨量滞涨」", 1.0,
             lambda c: (not (c["pct"] < 0 and c["vol_ratio"] > 2), "无放量下跌")),
        ],
    },
    {
        "id": "soros",
        "name": "乔治·索罗斯",
        "school": "反身性 / 宏观动量",
        "title": "趋势自我强化 · 快进快出",
        "motto": "重要的不是你判断对错，而是对的时候赚多少。",
        "philosophy": "反身性理论认为价格会反过来强化基本面预期，形成自我加速的趋势。"
                      "技术面找的是「已经在加速、资金持续放大」的票，但过热就要减。",
        "criteria": [
            ("20 日涨幅超 10%（趋势已确立）", 2.5,
             lambda c: (c["chg20"] >= 10, f"20 日 {c['chg20']:+.1f}%")),
            ("资金持续放大（量比 ≥ 1.2）", 2.0,
             lambda c: (c["vol_ratio"] >= 1.2, f"量比 {c['vol_ratio']:.2f}")),
            ("站在 MA20 之上", 1.5,
             lambda c: (c["close"] > c["ma20"] > 0, f"MA20 {c['ma20']:.2f}")),
            ("有足够波动（弹性）", 1.0,
             lambda c: (c["atr_pct"] >= 2.0, f"日波动 {c['atr_pct']:.1f}%")),
            ("还没极端过热（RSI ≤ 85）", 1.5,
             lambda c: (c["rsi"] <= 85, f"RSI {c['rsi']:.1f}")),
            ("近 5 日仍在上涨", 1.5,
             lambda c: (c["chg5"] > 0, f"5 日 {c['chg5']:+.1f}%")),
        ],
    },
    {
        "id": "simons",
        "name": "詹姆斯·西蒙斯",
        "school": "量化 / 统计套利",
        "title": "均值回归 · 只赌概率",
        "motto": "我们不预测方向，我们只赚统计上的优势。",
        "philosophy": "大奖章基金做的是短期统计规律。这里用最朴素的一条：超跌 + 触及布林下轨 + "
                      "成交没枯竭，短期有均值回归的统计优势，持有一两周就走。",
        "criteria": [
            ("RSI 偏低（≤ 40，超跌）", 2.5,
             lambda c: (c["rsi"] <= 40, f"RSI {c['rsi']:.1f}")),
            ("20 日跌幅明显（≤ -8%）", 2.0,
             lambda c: (c["chg20"] <= -8, f"20 日 {c['chg20']:+.1f}%")),
            ("贴近布林下轨", 2.0,
             lambda c: (c["boll_dn"] > 0 and c["close"] <= c["boll_dn"] * 1.02,
                        f"下轨 {c['boll_dn']:.2f} / 现价 {c['close']:.2f}")),
            ("波动适中（1.5%~6%）", 1.5,
             lambda c: (1.5 <= c["atr_pct"] <= 6, f"日波动 {c['atr_pct']:.1f}%")),
            ("成交没枯竭", 1.0,
             lambda c: (c["amount20"] >= 2e8, f"日均成交 {c['amount20'] / 1e8:.1f} 亿")),
            ("没跌破年线太深（≥ -25%）", 1.0,
             lambda c: (c["dist_ma250"] >= -25, f"距年线 {c['dist_ma250']:+.1f}%")),
        ],
    },
    {
        "id": "templeton",
        "name": "约翰·邓普顿",
        "school": "逆向投资",
        "title": "极度悲观处买入",
        "motto": "牛市在悲观中诞生，在乐观中死亡。",
        "philosophy": "只在众人恐慌、价格远低于一年高点时出手。技术面近似：离高点回撤够深、"
                      "RSI 进入悲观区、离一年低点很近、但成交还没彻底枯竭（还得有人交易）。",
        "criteria": [
            ("距一年高点回撤 ≥ 25%", 2.5,
             lambda c: (c["dist_high250"] <= -25, f"距年内高 {c['dist_high250']:.1f}%")),
            ("RSI 进入悲观区（≤ 35）", 2.0,
             lambda c: (c["rsi"] <= 35, f"RSI {c['rsi']:.1f}")),
            ("接近一年低点（≤ 10%）", 2.0,
             lambda c: (c["dist_low250"] <= 10, f"高于年内低点 {c['dist_low250']:.1f}%")),
            ("成交未彻底枯竭", 1.5,
             lambda c: (c["amount20"] >= 1e8, f"日均成交 {c['amount20'] / 1e8:.1f} 亿")),
            ("股价在年线下方（没人愿意看）", 1.0,
             lambda c: (c["dist_ma250"] < 0, f"距年线 {c['dist_ma250']:+.1f}%")),
            ("波动没到失控（≤ 4%）", 1.0,
             lambda c: (c["atr_pct"] <= 4, f"日波动 {c['atr_pct']:.1f}%")),
        ],
    },
]


def _verdict(pct: float, stance: str) -> str:
    """契合度文案必须跟操作倾向一致，不能出现「高度契合 · 回避」这种自相矛盾。"""
    if stance == "值得关注":
        return "高度契合"
    if pct >= 55:
        return "较为契合"
    if pct >= 35:
        return "部分契合"
    return "不符合其标准"


def _stance(master: dict, items: list[dict], pct: float) -> str:
    """给一个操作倾向：核心两条都过 + 契合度过半 才算「值得关注」。"""
    core_ok = all(it["pass"] for it in items[:2])
    if pct >= 55 and core_ok:
        return "值得关注"
    if pct >= 35:
        return "再观察"
    return "不符合，回避"


def _summary(items: list[dict], pct: float, stance: str) -> str:
    ok = [it for it in items if it["pass"]]
    miss = [it for it in items if not it["pass"]]
    head = f"通过 {len(ok)}/{len(items)} 条，契合度 {pct:.0f}%"
    if stance == "值得关注":
        tail = "核心条件成立，可以放进观察池。"
    elif stance == "再观察":
        tail = "部分条件成立，等更明确的信号。" if miss else "条件基本成立。"
    else:
        tail = "核心条件不成立，先别看。"
    if miss and stance != "值得关注":
        tail += f" 主要卡在：{miss[0]['label']}。"
    return head + "。" + tail


def analyze(df, name: str, code: str, entry: dict | None = None, detail: bool = True) -> dict:
    """对一只股票跑一遍所有大师方法论。

    Args:
        df: 需已经过 indicators.calc_all()。
        entry: 有持仓时会带上成本/盈亏供参考。
        detail: True 带每套的逐条标准（搜索页展开用）；False 只留名称/契合度/倾向/摘要，
            自选与持仓一次要跑好几只，不要再把几十条 criteria 塞进同一个响应。
    """
    s = snap(df, code, name)
    if not s:
        raise ValueError("行情数据不足，无法分析")

    results = []
    for m in MASTERS:
        items = []
        score = 0.0
        max_score = 0.0
        for label, weight, fn in m["criteria"]:
            try:
                passed, value = fn(s)
            except Exception:
                passed, value = False, "-"
            max_score += weight
            if passed:
                score += weight
            items.append({
                "label": label,
                "weight": weight,
                "pass": bool(passed),
                "value": value,
            })
        pct = score / max_score * 100 if max_score else 0.0
        stance = _stance(m, items, pct)
        row = {
            "id": m["id"],
            "name": m["name"],
            "school": m["school"],
            "title": m["title"],
            "pct": _r(pct, 0),
            "verdict": _verdict(pct, stance),
            "stance": stance,
            "summary": _summary(items, pct, stance),
        }
        if detail:
            row.update({
                "motto": m["motto"],
                "philosophy": m["philosophy"],
                "score": _r(score, 1),
                "max_score": _r(max_score, 1),
                "criteria": items,
            })
        results.append(row)

    bull = [x["name"] for x in results if x["stance"] == "值得关注"]
    avg = sum(x["pct"] for x in results) / len(results)

    if len(bull) >= 5:
        consensus = "多数方法论认可，属于「怎么买都对」的类型（往往也意味着已经涨了不少）。"
    elif len(bull) >= 3:
        consensus = "分歧中有共识：一半左右的方法论认可，值得结合自己的风格取舍。"
    elif len(bull) >= 1:
        consensus = "只有少数方法论认可，属于风格票——适不适合取决于你信哪一套。"
    else:
        consensus = "目前没有方法论给出买入理由，属于「都不建议现在动手」的状态。"

    return {
        "code": code,
        "name": name,
        "date": str(df["date"].iloc[-1])[:10],
        "price": _r(s["close"]),
        "pct": _r(s["pct"]),
        "entry": entry or None,
        "masters": results,
        "consensus": {
            "bull_count": len(bull),
            "total": len(results),
            "bull_names": bull,
            "avg_pct": _r(avg, 0),
            "text": consensus,
        },
    }
