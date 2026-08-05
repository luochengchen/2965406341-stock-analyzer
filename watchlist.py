"""Watchlist manager - JSON-based stock watchlist."""
from __future__ import annotations
import json
import os
from datetime import datetime


WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


def load_watchlist() -> list[dict]:
    """Load watchlist from JSON file. Returns list of stock entries."""
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, IOError):
        return []


def save_watchlist(watchlist: list[dict]):
    """Save watchlist to JSON file."""
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)


def add_stock(code: str, name: str = "", notes: str = "") -> bool:
    """Add a stock to watchlist. Returns False if already exists."""
    watchlist = load_watchlist()
    code = code.zfill(6)
    for entry in watchlist:
        if entry.get("code") == code:
            return False  # Already exists

    watchlist.append({
        "code": code,
        "name": name,
        "notes": notes,
        "added": datetime.now().strftime("%Y-%m-%d"),
        "price": 0,
        "pct_change": 0,
        "short_verdict": "",
        "long_verdict": "",
        "last_updated": "",
    })
    save_watchlist(watchlist)
    return True


def remove_stock(code: str) -> bool:
    """Remove a stock from watchlist."""
    watchlist = load_watchlist()
    new_list = [e for e in watchlist if e.get("code") != code]
    if len(new_list) == len(watchlist):
        return False
    save_watchlist(new_list)
    return True


def update_stock_status(code: str, price: float, pct_change: float,
                         short_verdict: str, long_verdict: str, name: str = ""):
    """Update a stock's latest analysis results."""
    watchlist = load_watchlist()
    for entry in watchlist:
        if entry.get("code") == code:
            entry["price"] = round(price, 2)
            entry["pct_change"] = round(pct_change, 2)
            entry["short_verdict"] = short_verdict
            entry["long_verdict"] = long_verdict
            entry["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            if name:
                entry["name"] = name
            break
    save_watchlist(watchlist)


def import_from_text(text: str) -> int:
    """Import stocks from pasted text (one code or name per line). Returns count added."""
    lines = text.strip().split("\n")
    count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Extract stock code from possible formats:
        # "000001 平安银行", "000001", "平安银行", "sz000001"
        parts = line.split()
        code_part = parts[0] if parts else line
        # Remove market prefix
        code_part = code_part.replace("sh.", "").replace("sz.", "").replace("SH", "").replace("SZ", "")
        if code_part.isdigit() and len(code_part) == 6:
            if add_stock(code_part):
                count += 1
    return count


def get_all_codes() -> list[str]:
    """Get list of all stock codes in watchlist."""
    return [e["code"] for e in load_watchlist()]
