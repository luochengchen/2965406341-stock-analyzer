"""Portfolio data layer — watchlist + position management via JSON file."""
from __future__ import annotations

from codes import norm_code

import json
import os
import shutil
from datetime import date, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
# 数据放 data/ 子目录而不是脚本旁边：GUI（main_gui.py）、Flask（web_app.py）和
# DSH 插件起的是同一个进程文件，都用这一份，和 cwd 无关，升级/重打包也不会丢。
# 要换位置（比如放到网盘）设 STOCK_DATA_DIR 即可。
DATA_DIR = os.environ.get("STOCK_DATA_DIR") or os.path.join(ROOT, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
# 每次覆盖前在 data/backups/ 留一份快照：持仓是用户自己录的钱，一次误写就再也找不回来。
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_KEEP = 50

# 旧位置：早期版本把 portfolio.json 写在脚本旁边，watchlist.json 是更早的纯代码列表。
LEGACY_PORTFOLIO = os.path.join(ROOT, "portfolio.json")
LEGACY_WATCHLIST = os.path.join(ROOT, "watchlist.json")


def _bootstrap() -> None:
    """首次运行时把旧数据搬进 data/，一个自选都不丢。已存在则什么都不做。"""
    if os.path.exists(PORTFOLIO_FILE):
        return

    data: dict = {"stocks": {}}
    if os.path.exists(LEGACY_PORTFOLIO):
        try:
            with open(LEGACY_PORTFOLIO, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("stocks"), dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass

    if os.path.exists(LEGACY_WATCHLIST):
        try:
            with open(LEGACY_WATCHLIST, "r", encoding="utf-8") as f:
                codes = json.load(f)
        except (json.JSONDecodeError, OSError):
            codes = []
        if isinstance(codes, list):
            for raw in codes:
                code = norm_code(raw)
                if code.isdigit() and code not in data["stocks"]:
                    data["stocks"][code] = {"name": "", "added": date.today().isoformat()}

    save_portfolio(data)


def load_portfolio() -> dict:
    """Read portfolio.json, return {"capital": float, "stocks": {...}}."""
    _bootstrap()
    if not os.path.exists(PORTFOLIO_FILE):
        return {"capital": 0.0, "stocks": {}}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "stocks" not in data:
                return {"capital": 0.0, "stocks": {}}
            # 老文件没有 capital 字段：补 0 表示「还没设总资金」
            data.setdefault("capital", 0.0)
            return data
    except (json.JSONDecodeError, IOError):
        return {"capital": 0.0, "stocks": {}}


def _prune_backups() -> None:
    """只留最近 BACKUP_KEEP 份，别把磁盘塞满。"""
    try:
        files = sorted(os.listdir(BACKUP_DIR))
    except OSError:
        return
    for name in files[:-BACKUP_KEEP]:
        if not name.startswith("portfolio-") or not name.endswith(".json"):
            continue
        try:
            os.remove(os.path.join(BACKUP_DIR, name))
        except OSError:
            pass


def _backup_before_write() -> None:
    """写盘前给现有文件拍快照。失败不阻断保存（备份不能比数据本身更要紧）。"""
    if not os.path.exists(PORTFOLIO_FILE) or os.path.getsize(PORTFOLIO_FILE) == 0:
        return
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(PORTFOLIO_FILE, os.path.join(BACKUP_DIR, f"portfolio-{stamp}.json"))
        _prune_backups()
    except OSError:
        pass


def save_portfolio(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    _backup_before_write()
    # 先写临时文件再替换：中途崩掉不会留下半截 JSON，把自选全弄丢。
    tmp = f"{PORTFOLIO_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PORTFOLIO_FILE)


def list_backups() -> list[dict]:
    """列出可用快照（新的在前），带股票数与修改时间，便于用户自己挑一份回滚。"""
    try:
        names = [n for n in os.listdir(BACKUP_DIR)
                 if n.startswith("portfolio-") and n.endswith(".json")]
    except OSError:
        return []
    out = []
    for name in sorted(names, reverse=True):
        path = os.path.join(BACKUP_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stocks = data.get("stocks") or {}
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "name": name,
            "time": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
            "stocks": len(stocks),
            "capital": data.get("capital", 0.0),
            "positions": sum(1 for v in stocks.values() if v.get("position")),
        })
    return out


def restore_backup(name: str) -> bool:
    """把某个快照写回去（当前状态会先被备份，回滚本身也能再回滚）。"""
    if os.path.basename(name) != name or not name.endswith(".json"):
        return False
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or "stocks" not in data:
        return False
    save_portfolio(data)
    return True


def add_stock(code: str, name: str = "") -> bool:
    """Add a stock to watchlist. Returns True if added, False if already exists."""
    code = norm_code(code)
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
    code = norm_code(code)
    data = load_portfolio()
    if code not in data["stocks"]:
        return False
    del data["stocks"][code]
    save_portfolio(data)
    return True


def set_position(code: str, shares: int, cost: float) -> bool:
    """Set or clear position for a watched stock. Returns True if updated."""
    code = norm_code(code)
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
    code = norm_code(code)
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


# ---------------------------------------------------------------------------
# 资金账户
# ---------------------------------------------------------------------------

def get_capital() -> float:
    """账户总资金（元）。0 表示用户还没设置。"""
    try:
        return float(load_portfolio().get("capital") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def set_capital(value: float) -> float:
    """设置账户总资金，返回实际存下的值（负数按 0 处理）。"""
    value = max(0.0, round(float(value), 2))
    data = load_portfolio()
    data["capital"] = value
    save_portfolio(data)
    return value
