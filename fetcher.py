"""Stock data fetcher using baostock."""
from __future__ import annotations
import baostock as bs
import pandas as pd


# Login state
_logged_in = False


def _ensure_login():
    """Ensure baostock is logged in."""
    global _logged_in
    if not _logged_in:
        lg = bs.login()
        if lg.error_code != "0":
            raise ConnectionError(f"Baostock 登录失败: {lg.error_msg}")
        _logged_in = True


def _logout():
    """Logout from baostock."""
    global _logged_in
    if _logged_in:
        bs.logout()
        _logged_in = False


def resolve_stock_code(query: str) -> tuple[str, str]:
    """Resolve stock name or partial code to (full_code, name).

    Supports:
    - Full code: 'sh.000001', 'sz.000001'
    - Plain code: '000001'
    - Name: '平安银行', '贵州茅台'
    - Fuzzy name: '平安' -> first match
    """
    _ensure_login()

    query = query.strip()

    # Check if query is already in baostock format with dot
    if "." in query:
        # Already has market prefix, try code lookup
        rs = bs.query_stock_basic(code=query)
        if rs.error_code == "0":
            while rs.next():
                row = rs.get_row_data()
                return row[0].replace("sh.", "").replace("sz.", ""), row[1]
        raise ValueError(f"未找到匹配的股票代码: {query}")

    # Try as plain 6-digit code
    if query.isdigit() and len(query) <= 6:
        code = query.zfill(6)
        # Determine market
        if code.startswith(("60", "68")):
            full_code = f"sh.{code}"
        else:
            full_code = f"sz.{code}"

        rs = bs.query_stock_basic(code=full_code)
        if rs.error_code == "0":
            while rs.next():
                row = rs.get_row_data()
                return row[0].replace("sh.", "").replace("sz.", ""), row[1]

    # Try by name (fuzzy match) via code_name parameter
    rs = bs.query_stock_basic(code_name=query)
    if rs.error_code == "0":
        while rs.next():
            row = rs.get_row_data()
            code = row[0]
            name = row[1]  # code_name is at index 1
            clean_code = code.replace("sh.", "").replace("sz.", "")
            return clean_code, name

    raise ValueError(f"未找到匹配的股票: {query}，请检查代码或名称")


def fetch_daily_kline(symbol: str, days: int = 250) -> pd.DataFrame:
    """Fetch daily K-line data for a stock.

    Args:
        symbol: 6-digit stock code (e.g., '000001')
        days: number of trading days to fetch (approx)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, amount
    """
    _ensure_login()

    # Determine market prefix
    if symbol.startswith(("60", "68")):
        full_code = f"sh.{symbol}"
    else:
        full_code = f"sz.{symbol}"

    # Calculate start date for ~days trading days (~1.5x calendar days)
    import datetime
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=int(days * 1.8))).strftime("%Y-%m-%d")

    fields = "date,open,high,low,close,volume,amount,preclose"
    rs = bs.query_history_k_data_plus(
        full_code,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",  # 前复权
    )

    if rs.error_code != "0":
        raise ValueError(f"获取K线数据失败: {rs.error_msg}")

    data = []
    while rs.next():
        data.append(rs.get_row_data())

    if not data:
        raise ValueError(f"未获取到 {symbol} 的K线数据")

    df = pd.DataFrame(data, columns=fields.split(","))
    df["date"] = pd.to_datetime(df["date"])

    # Convert to float
    for col in ["open", "high", "low", "close", "volume", "amount", "preclose"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter out rows with NaN (non-trading days)
    df = df[df["close"].notna() & (df["close"] > 0)].copy()

    # Take last N trading days
    df = df.sort_values("date").tail(days).reset_index(drop=True)

    if len(df) < 30:
        raise ValueError(f"{symbol} 只有 {len(df)} 个交易日数据，不足以分析（需≥30天）")

    return df[["date", "open", "high", "low", "close", "volume", "amount"]]


def get_stock_info(symbol: str) -> dict:
    """Get basic stock info (name, price, change%)."""
    _ensure_login()

    # Determine full code
    if symbol.startswith(("60", "68")):
        full_code = f"sh.{symbol}"
    else:
        full_code = f"sz.{symbol}"

    rs = bs.query_stock_basic(code=full_code)
    name = symbol
    if rs.error_code == "0":
        while rs.next():
            row = rs.get_row_data()
            name = row[1]  # code_name is at index 1

    # Get latest price
    fields = "date,close,preclose"
    import datetime
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=5)).strftime("%Y-%m-%d")

    rs2 = bs.query_history_k_data_plus(full_code, fields, start_date=start_date, end_date=end_date, frequency="d", adjustflag="2")
    price = 0
    pct = 0
    if rs2.error_code == "0":
        while rs2.next():
            row = rs2.get_row_data()
            if len(row) >= 3 and row[1] != "" and row[2] != "":
                close_val = float(row[1])
                preclose_val = float(row[2])
                price = close_val
                pct = (close_val - preclose_val) / preclose_val * 100 if preclose_val > 0 else 0

    return {"name": name, "price": price, "pct_change": pct}
