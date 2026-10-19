#!/usr/bin/env python
"""Stock Technical Analysis Tool — 股票技术分析工具

Usage:
    python main.py              # Interactive mode
    python main.py 000001       # Analyze stock 000001 (平安银行)
    python main.py 贵州茅台     # Analyze by name
"""

import sys
from rich.console import Console
from rich.panel import Panel

from fetcher import resolve_stock_code, fetch_daily_kline, get_stock_info
from indicators import calc_all
from analyzer import ShortTermAnalyzer as StockAnalyzer
from reporter import print_analysis

console = Console()


def analyze_stock(query: str) -> dict:
    """Full pipeline: resolve -> fetch -> calc indicators -> analyze."""
    # 1. Resolve code
    with console.status(f"[bold cyan]正在查找股票: {query}...[/bold cyan]"):
        code, name = resolve_stock_code(query)
    console.print(f"[dim]找到: {name} ({code})[/dim]")

    # 2. Fetch data
    with console.status(f"[bold cyan]正在获取 {name} 的K线数据...[/bold cyan]"):
        df = fetch_daily_kline(code)
    console.print(f"[dim]获取到 {len(df)} 个交易日数据[/dim]")

    # 3. Calculate indicators
    with console.status("[bold cyan]正在计算技术指标...[/bold cyan]"):
        df = calc_all(df)

    # 4. Analyze
    with console.status("[bold cyan]正在综合分析...[/bold cyan]"):
        analyzer = StockAnalyzer(df, name, code)
        result = analyzer.analyze()

    # 5. Get live quote
    try:
        info = get_stock_info(code)
        result["pct_change"] = info.get("pct_change", 0)
    except Exception:
        result["pct_change"] = 0

    # Attach the latest row for reporter use
    result["latest_row"] = df.iloc[-1]

    return result


def interactive_mode():
    """Interactive loop for stock input."""
    console.print(Panel(
        "[bold cyan]A股技术分析工具[/bold cyan]\n\n"
        "支持输入: 股票代码 (如 000001) 或 股票名称 (如 平安银行)\n"
        "输入 'q' 或 'quit' 退出",
        title="欢迎",
        border_style="cyan",
    ))

    while True:
        try:
            query = console.input("\n[bold yellow]请输入股票代码或名称 > [/bold yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]退出[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("q", "quit", "exit"):
            console.print("[dim]再见！[/dim]")
            break

        try:
            result = analyze_stock(query)
            print_analysis(result)
        except ValueError as e:
            console.print(f"[bold red]错误: {e}[/bold red]")
        except Exception as e:
            console.print(f"[bold red]分析出错: {e}[/bold red]")


def main():
    if len(sys.argv) > 1:
        # Single analysis mode
        query = " ".join(sys.argv[1:])
        try:
            result = analyze_stock(query)
            print_analysis(result)
        except Exception as e:
            console.print(f"[bold red]错误: {e}[/bold red]")
            sys.exit(1)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
