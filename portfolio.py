"""Portfolio data layer — watchlist + position management via JSON file."""
from __future__ import annotations

import json
import os
from datetime import date

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json")


def load_portfolio() -> dict:
    """Read portfolio.json, return {"stocks": {...}}. Returns empty dict on failure."""
    if not os.path.exists(PORTFOLIO_FILE):
        return {"stocks": {}}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "stocks" not in data:
                return {"stocks": {}}
            return data
    except (json.JSONDecodeError, IOError):
        return {"stocks": {}}


def save_portfolio(data: dict) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_stock(code: str, name: str = "") -> bool:
    """Add a stock to watchlist. Returns True if added, False if already exists."""
    code = code.zfill(6)
    data = load_portfolio()
    if code in data["stocks"]:
        return False
    data["stocks"][code] = {
        "name": name,
        "added": date.today().isoformat(),
    }
    save_portfolio(data)
    return True


def remove_stock(code: str) -> bool:
    """Remove a stock from watchlist. Returns True if removed, False if not found."""
    code = code.zfill(6)
    data = load_portfolio()
    if code not in data["stocks"]:
        return False
    del data["stocks"][code]
    save_portfolio(data)
    return True


def set_position(code: str, shares: int, cost: float) -> bool:
    """Set or clear position for a watched stock. Returns True if updated."""
    code = code.zfill(6)
    data = load_portfolio()
    if code not in data["stocks"]:
        return False
    if shares <= 0 or cost <= 0:
        data["stocks"][code].pop("position", None)
    else:
        data["stocks"][code]["position"] = {"shares": shares, "cost": round(cost, 3)}
    save_portfolio(data)
    return True


def get_all_stocks() -> list[dict]:
    """Return list of all watched stocks with position info."""
    data = load_portfolio()
    result = []
    for code, info in data["stocks"].items():
        entry = {"code": code, "name": info.get("name", ""), "added": info.get("added", "")}
        pos = info.get("position")
        if pos:
            entry["has_position"] = True
            entry["shares"] = pos["shares"]
            entry["cost"] = pos["cost"]
        else:
            entry["has_position"] = False
            entry["shares"] = 0
            entry["cost"] = 0
        result.append(entry)
    result.sort(key=lambda x: x["code"])
    return result


def get_stock(code: str) -> dict | None:
    """Get single stock entry. Returns None if not found."""
    code = code.zfill(6)
    data = load_portfolio()
    info = data["stocks"].get(code)
    if info is None:
        return None
    entry = {"code": code, "name": info.get("name", ""), "added": info.get("added", "")}
    pos = info.get("position")
    if pos:
        entry["has_position"] = True
        entry["shares"] = pos["shares"]
        entry["cost"] = pos["cost"]
    else:
        entry["has_position"] = False
        entry["shares"] = 0
        entry["cost"] = 0
    return entry
