"""Rich terminal output for stock analysis."""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich import box


console = Console()


def print_header(name: str, code: str, price: float, pct_change: float):
    """Print stock header with price info."""
    color = "red" if pct_change < 0 else "green"
    sign = "+" if pct_change > 0 else ""
    text = Text()
    text.append(f"\n{'='*60}\n", style="bold cyan")
    text.append(f"  {name} ({code})", style="bold white")
    text.append(f"\n  最新价: {price:.2f}  涨跌幅: {sign}{pct_change:.2f}%", style=f"bold {color}")
    text.append(f"\n{'='*60}", style="bold cyan")
    console.print(text)


def print_ma_info(latest, supports, resistances):
    """Print moving average and support/resistance levels."""
    ma_table = Table(title="均线系统", box=box.ROUNDED, header_style="bold cyan")
    ma_table.add_column("均线", style="dim")
    ma_table.add_column("数值", style="bold")
    ma_table.add_column("位置", style="italic")

    close = latest["close"]
    for period in [5, 10, 20, 60]:
        ma_val = latest.get(f"MA{period}")
        if pd.isna(ma_val):
            continue
        arrow = "↑" if close > ma_val else "↓"
        color = "green" if close > ma_val else "red"
        ma_table.add_row(
            f"MA{period}",
            f"{ma_val:.2f}",
            f"[{color}]{arrow} 价格{'之上' if close > ma_val else '之下'}[/{color}]",
        )

    console.print(ma_table)

    # Support / Resistance
    sr_table = Table(title="压力位 & 支撑位", box=box.ROUNDED, header_style="bold yellow")
    sr_table.add_column("类型", style="bold")
    sr_table.add_column("价格", style="bold")
    sr_table.add_column("距离(%)", style="dim")

    for r in resistances:
        dist = (r - close) / close * 100
        sr_table.add_row("[R] 压力位", f"{r:.2f}", f"+{dist:.2f}%")
    for s in supports:
        dist = (close - s) / close * 100
        sr_table.add_row("[S] 支撑位", f"{s:.2f}", f"-{dist:.2f}%")

    console.print(sr_table)


def print_indicators(latest, details):
    """Print MACD, KDJ, RSI values."""
    ind_table = Table(title="技术指标", box=box.ROUNDED, header_style="bold magenta")
    ind_table.add_column("指标", style="bold")
    ind_table.add_column("数值", style="bold")
    ind_table.add_column("信号", style="italic")

    # MACD
    dif = latest.get("DIF")
    dea = latest.get("DEA")
    bar = latest.get("MACD_BAR")
    if not pd.isna(dif):
        bar_color = "green" if bar > 0 else "red"
        ind_table.add_row(
            "MACD",
            f"DIF={dif:.3f}  DEA={dea:.3f}\nBAR=[{bar_color}]{bar:.3f}[/{bar_color}]",
            details.get("MACD", ""),
        )

    # KDJ
    k = latest.get("K")
    d = latest.get("D")
    j = latest.get("J")
    if not pd.isna(k):
        j_color = "green" if j < 30 else ("red" if j > 80 else "yellow")
        ind_table.add_row(
            "KDJ",
            f"K={k:.2f}  D={d:.2f}  J=[{j_color}]{j:.2f}[/{j_color}]",
            details.get("KDJ", ""),
        )

    # RSI
    rsi6 = latest.get("RSI6")
    rsi14 = latest.get("RSI14")
    if not pd.isna(rsi14):
        ind_table.add_row(
            "RSI",
            f"RSI6={rsi6:.1f}  RSI14={rsi14:.1f}",
            details.get("RSI", ""),
        )

    # Bollinger
    boll_up = latest.get("BOLL_UP")
    boll_mid = latest.get("BOLL_MID")
    boll_dn = latest.get("BOLL_DN")
    if not pd.isna(boll_mid):
        ind_table.add_row(
            "布林带",
            f"上={boll_up:.2f}  中={boll_mid:.2f}  下={boll_dn:.2f}",
            details.get("布林带", ""),
        )

    console.print(ind_table)


def print_volume_info(latest, details):
    """Print volume analysis."""
    vol_ratio = latest.get("VOL_RATIO")
    vol_table = Table(title="成交量分析", box=box.ROUNDED, header_style="bold blue")
    vol_table.add_column("指标", style="bold")
    vol_table.add_column("数值", style="bold")

    vol_ratio_val = vol_ratio if not pd.isna(vol_ratio) else 1
    ratio_color = "green" if vol_ratio_val > 1.2 else ("red" if vol_ratio_val < 0.6 else "white")
    vol_table.add_row("量比(今日/5日均量)", f"[{ratio_color}]{vol_ratio_val:.2f}x[/{ratio_color}]")
    vol_table.add_row("今日成交量", f"{latest['volume']:,.0f} 手")
    vol_table.add_row("5日均量", f"{latest.get('VOL_MA5', 0):,.0f} 手")
    vol_table.add_row("信号", details.get("量价关系", ""))

    console.print(vol_table)


def print_scores(scores: dict, total: float, verdict: str, color: str, details: dict = None):
    """Print scoring breakdown and final verdict."""
    if details is None:
        details = {}
    score_table = Table(title="综合评分", box=box.ROUNDED, header_style="bold cyan")
    score_table.add_column("维度", style="bold")
    score_table.add_column("得分", style="bold", justify="center")
    score_table.add_column("详情", style="italic")

    for dim, score in scores.items():
        s_color = "green" if score > 0 else ("red" if score < 0 else "dim")
        s_text = f"[{s_color}]{score:+.1f}[/{s_color}]"
        score_table.add_row(dim, s_text, details.get(dim, ""))

    score_table.add_section()
    score_table.add_row(
        "[bold]总分[/bold]",
        f"[bold {color}]{total:+.1f}[/bold {color}]",
        "",
    )

    console.print(score_table)

    # Final verdict panel
    verdict_color_map = {
        "green": "green",
        "yellow": "yellow",
        "dim": "white",
        "red": "red",
    }
    vc = verdict_color_map.get(color, "white")
    console.print(Panel(
        f"[bold {vc}]{verdict}[/bold {vc}]",
        title="入场判断",
        border_style=vc,
        box=box.DOUBLE,
    ))
    console.print("")



def print_analysis(result: dict):
    """Print full analysis result."""
    # Header
    print_header(
        result["name"], result["code"],
        result["price"],
        result.get("pct_change", 0),
    )

    # MA + Support/Resistance
    print_ma_info(
        result["latest_row"],
        result["supports"],
        result["resistances"],
    )

    # Technical indicators
    print_indicators(result["latest_row"], result["details"])

    # Volume
    print_volume_info(result["latest_row"], result["details"])

    # Scores
    print_scores(result["scores"], result["total_score"], result["verdict"], result["color"], result["details"])


# Need pandas for pd.isna checks
import pandas as pd
