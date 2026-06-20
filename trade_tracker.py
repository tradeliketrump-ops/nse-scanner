"""
Trade Performance Tracker (SQLite)
==================================
Tracks "BUY NOW" signals from the NSE Swing Scanner as live positions,
monitors them against 5% stop-loss and 10% profit targets,
and provides portfolio performance reporting.

Data stored in SQLite database (trades_history.db) for reliability.
"""
import os, sqlite3, logging, threading
from datetime import datetime, date, timedelta
from typing import Optional
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────
CAPITAL_PER_POSITION = 150000
STOP_LOSS_PCT = 0.05
PROFIT_TARGET_PCT = 0.10
ENTRY_TIME_IST = "09:30"
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

# Persistent storage path
if os.path.exists("/data"):
    DATA_DIR = "/data"
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "trades_history.db")

STATUS_PENDING_ENTRY = "pending_entry"
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"

_lock = threading.Lock()


class TradeTracker:
    """
    SQLite-backed trade tracker. Thread-safe.
    All methods maintain the same API as before but use a database.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _connect(self):
        """Get a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Create the positions table if it doesn't exist."""
        with _lock:
            conn = self._connect()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        sector TEXT DEFAULT '',
                        signal_date TEXT NOT NULL,
                        signal_price REAL DEFAULT 0,
                        entry_date TEXT,
                        entry_price REAL,
                        stop_loss REAL,
                        target REAL,
                        capital REAL DEFAULT 150000,
                        quantity INTEGER DEFAULT 1,
                        status TEXT DEFAULT 'pending_entry',
                        close_date TEXT,
                        close_price REAL,
                        close_reason TEXT,
                        pnl REAL,
                        pnl_percent REAL,
                        current_price REAL DEFAULT 0,
                        entry_zone TEXT DEFAULT '',
                        suggested_stop TEXT DEFAULT '',
                        rr TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON positions(symbol)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON positions(status)")
                conn.commit()
            except Exception as e:
                logger.error(f"DB init error: {e}")
            finally:
                conn.close()

    # ─── Position CRUD ──────────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        """Convert a sqlite3.Row to a dict, handling None values."""
        if row is None:
            return None
        d = dict(row)
        for k, v in d.items():
            if v is None and k in ("pnl", "pnl_percent", "entry_price", "current_price", "signal_price", "stop_loss", "target", "close_price", "quantity"):
                pass  # keep None
        return d

    def _get_positions(self, status_filter: Optional[str] = None) -> list[dict]:
        """Get all positions, optionally filtered by status."""
        with _lock:
            conn = self._connect()
            try:
                if status_filter:
                    rows = conn.execute(
                        "SELECT * FROM positions WHERE status = ? ORDER BY signal_date DESC, symbol ASC",
                        (status_filter,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM positions ORDER BY signal_date DESC, symbol ASC"
                    ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def _upsert_position(self, pos_id: str, data: dict):
        """Insert or update a single position."""
        with _lock:
            conn = self._connect()
            try:
                columns = ", ".join(data.keys())
                placeholders = ", ".join("?" * len(data))
                updates = ", ".join(f"{k}=excluded.{k}" for k in data.keys() if k != "id")
                sql = f"""
                    INSERT INTO positions ({columns}) VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {updates}
                """
                conn.execute(sql, list(data.values()))
                conn.commit()
            except Exception as e:
                logger.error(f"DB upsert error for {pos_id}: {e}")
            finally:
                conn.close()

    def _delete_all(self):
        """Clear all positions (for testing)."""
        with _lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM positions")
                conn.commit()
            finally:
                conn.close()

    # ─── Price Fetching ─────────────────────────────────────────────

    @staticmethod
    def fetch_price(symbol: str, date_str: Optional[str] = None) -> Optional[float]:
        try:
            if date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                start = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
                end = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
                df = yf.download(symbol + ".NS", start=start, end=end, progress=False, auto_adjust=True)
                if df.empty:
                    return None
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(symbol + ".NS", axis=1, level=1) if symbol + ".NS" in df.columns.get_level_values(1).unique() else df.xs(symbol, axis=1, level=0)
                target_dt = pd.Timestamp(date_str)
                if target_dt in df.index:
                    row = df.loc[target_dt]
                    open_price = row.get("Open") if isinstance(row, pd.Series) else row.iloc[0]["Open"]
                    return float(open_price) if pd.notna(open_price) else None
                for idx in df.index:
                    if idx >= target_dt:
                        row = df.loc[idx]
                        open_price = row.get("Open") if isinstance(row, pd.Series) else row.iloc[0]["Open"]
                        return float(open_price) if pd.notna(open_price) else None
                return None
            else:
                df = yf.download(symbol + ".NS", period="5d", interval="1d", progress=False, auto_adjust=True)
                if df.empty:
                    return None
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(df.columns.get_level_values(1)[0], axis=1, level=1)
                close_price = df["Close"].iloc[-1]
                return float(close_price) if pd.notna(close_price) else None
        except Exception as e:
            logger.error(f"fetch_price({symbol}, {date_str}): {e}")
            return None

    # ─── Position Creation ──────────────────────────────────────────

    def create_positions_from_results(self, results: list[dict], signal_date: Optional[str] = None, same_day_entry: bool = False) -> list[str]:
        if signal_date is None:
            signal_date = date.today().isoformat()

        created = []

        for row in results:
            setup = row.get("1H_Setup", "")
            if setup not in ("BUY-R", "BUY-B"):
                continue
            symbol = row.get("Symbol", "")
            if not symbol:
                continue

            # Check for existing active/pending position for this symbol
            existing = None
            with _lock:
                conn = self._connect()
                try:
                    existing_row = conn.execute(
                        "SELECT * FROM positions WHERE symbol = ? AND status IN (?, ?) LIMIT 1",
                        (symbol, STATUS_PENDING_ENTRY, STATUS_ACTIVE)
                    ).fetchone()
                    if existing_row:
                        existing = self._row_to_dict(existing_row)
                finally:
                    conn.close()

            if existing:
                # Update existing position
                signal_price = float(row.get("Price", existing.get("signal_price", 0)))
                sector = row.get("Sector", existing.get("sector", ""))
                update_data = {
                    "signal_price": signal_price,
                    "current_price": signal_price,
                    "sector": sector,
                    "entry_zone": row.get("Entry", existing.get("entry_zone", "")),
                    "suggested_stop": row.get("Stop", existing.get("suggested_stop", "")),
                    "rr": row.get("R:R", existing.get("rr", "")),
                }
                if existing["status"] == STATUS_PENDING_ENTRY and same_day_entry:
                    update_data.update({
                        "entry_date": signal_date,
                        "entry_price": signal_price,
                        "stop_loss": round(signal_price * (1 - STOP_LOSS_PCT), 2),
                        "target": round(signal_price * (1 + PROFIT_TARGET_PCT), 2),
                        "quantity": max(1, int(CAPITAL_PER_POSITION / signal_price)),
                        "status": STATUS_ACTIVE,
                    })
                self._upsert_position(existing["id"], {**existing, **update_data})
                created.append(existing["id"])
                continue

            # Create new position
            pos_id = f"{symbol}-{signal_date}"
            sector = row.get("Sector", "Unknown")
            signal_price = float(row.get("Price", 0))
            stop_loss = round(signal_price * (1 - STOP_LOSS_PCT), 2) if same_day_entry else None
            target = round(signal_price * (1 + PROFIT_TARGET_PCT), 2) if same_day_entry else None
            quantity = max(1, int(CAPITAL_PER_POSITION / signal_price)) if same_day_entry else None
            status = STATUS_ACTIVE if same_day_entry else STATUS_PENDING_ENTRY

            data = {
                "id": pos_id, "symbol": symbol, "sector": sector,
                "signal_date": signal_date, "signal_price": signal_price,
                "entry_date": signal_date if same_day_entry else None,
                "entry_price": signal_price if same_day_entry else None,
                "stop_loss": stop_loss, "target": target,
                "capital": CAPITAL_PER_POSITION, "quantity": quantity,
                "status": status, "current_price": signal_price,
                "entry_zone": row.get("Entry", ""),
                "suggested_stop": row.get("Stop", ""),
                "rr": row.get("R:R", ""),
                "close_date": None, "close_price": None, "close_reason": None,
                "pnl": None, "pnl_percent": None,
            }
            self._upsert_position(pos_id, data)
            created.append(pos_id)
            logger.info(f"{'Immediate entry' if same_day_entry else 'Created pending'}: {pos_id} @ ₹{signal_price}")

        return created

    # ─── Entry Processing ───────────────────────────────────────────

    def process_pending_entries(self) -> list[dict]:
        if not self._is_market_hours(datetime.now(), allow_before_open=False):
            return []
        today_str = datetime.now().strftime("%Y-%m-%d")
        processed = []

        with _lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE status = ? AND signal_date <= ?",
                    (STATUS_PENDING_ENTRY, today_str)
                ).fetchall()
                for row in rows:
                    pos = self._row_to_dict(row)
                    entry_price = self.fetch_price(pos["symbol"], today_str)
                    if entry_price is None or entry_price <= 0:
                        price = self.fetch_price(pos["symbol"])
                        if price:
                            conn.execute("UPDATE positions SET current_price = ? WHERE id = ?", (price, pos["id"]))
                        continue
                    stop_loss = round(entry_price * (1 - STOP_LOSS_PCT), 2)
                    target = round(entry_price * (1 + PROFIT_TARGET_PCT), 2)
                    quantity = max(1, int(CAPITAL_PER_POSITION / entry_price))
                    conn.execute("""
                        UPDATE positions SET entry_date=?, entry_price=?, stop_loss=?, target=?,
                        quantity=?, status=?, current_price=?
                        WHERE id=?
                    """, (today_str, entry_price, stop_loss, target, quantity, STATUS_ACTIVE, entry_price, pos["id"]))
                    processed.append({"id": pos["id"], "symbol": pos["symbol"], "entry_price": entry_price, "quantity": quantity})
                    logger.info(f"Position entered: {pos['id']} @ ₹{entry_price}")
                if processed:
                    conn.commit()
            finally:
                conn.close()
        return processed

    # ─── Position Monitoring ────────────────────────────────────────

    def check_open_positions(self) -> list[dict]:
        if not self._is_market_hours(datetime.now()):
            return []
        closed = []

        with _lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE status = ?", (STATUS_ACTIVE,)
                ).fetchall()
                for row in rows:
                    pos = self._row_to_dict(row)
                    current_price = self.fetch_price(pos["symbol"])
                    if current_price is None or current_price <= 0:
                        continue

                    entry = pos["entry_price"] or pos["signal_price"]
                    sl = pos["stop_loss"]
                    tgt = pos["target"]

                    # Check SL
                    if sl and current_price <= sl:
                        pnl = round((current_price - entry) * (pos["quantity"] or 1), 2)
                        conn.execute("""
                            UPDATE positions SET close_date=?, close_price=?, close_reason=?,
                            pnl=?, pnl_percent=?, status=?, current_price=?
                            WHERE id=?
                        """, (date.today().isoformat(), current_price, "stop_loss",
                              pnl, round(pnl / entry * 100, 2) if entry else 0,
                              STATUS_CLOSED, current_price, pos["id"]))
                        closed.append({"id": pos["id"], "symbol": pos["symbol"], "reason": "stop_loss", "pnl": pnl})
                        continue

                    # Check Target
                    if tgt and current_price >= tgt:
                        pnl = round((current_price - entry) * (pos["quantity"] or 1), 2)
                        conn.execute("""
                            UPDATE positions SET close_date=?, close_price=?, close_reason=?,
                            pnl=?, pnl_percent=?, status=?, current_price=?
                            WHERE id=?
                        """, (date.today().isoformat(), current_price, "target",
                              pnl, round(pnl / entry * 100, 2) if entry else 0,
                              STATUS_CLOSED, current_price, pos["id"]))
                        closed.append({"id": pos["id"], "symbol": pos["symbol"], "reason": "target", "pnl": pnl})
                        continue

                    # Just update price
                    conn.execute("UPDATE positions SET current_price = ? WHERE id = ?", (current_price, pos["id"]))

                if closed:
                    conn.commit()
            finally:
                conn.close()
        return closed

    # ─── Manual Refresh ─────────────────────────────────────────────

    def refresh_all_prices(self) -> dict:
        updated = 0
        failed = 0
        with _lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE status IN (?, ?)",
                    (STATUS_ACTIVE, STATUS_PENDING_ENTRY)
                ).fetchall()
                for row in rows:
                    pos = self._row_to_dict(row)
                    price = self.fetch_price(pos["symbol"])
                    if price and price > 0:
                        conn.execute("UPDATE positions SET current_price = ? WHERE id = ?", (price, pos["id"]))
                        updated += 1
                    else:
                        failed += 1
                if updated:
                    conn.commit()
            finally:
                conn.close()
        return {"updated": updated, "failed": failed}

    # ─── Reporting ──────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        with _lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT * FROM positions").fetchall()
                positions = [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

        total_invested = 0.0
        current_value = 0.0
        total_pnl = 0.0
        wins = 0
        losses = 0
        active_count = 0
        pending_count = 0
        closed_count = 0

        for pos in positions:
            s = pos["status"]
            entry = pos["entry_price"] or 0
            qty = pos.get("quantity") or 1
            if s == STATUS_PENDING_ENTRY:
                pending_count += 1
            elif s == STATUS_ACTIVE:
                active_count += 1
                invested = entry * qty
                val = (pos["current_price"] or entry) * qty
                total_invested += invested
                current_value += val
                total_pnl += val - invested
            elif s == STATUS_CLOSED:
                closed_count += 1
                invested = entry * qty
                val = (pos["close_price"] or 0) * qty
                total_invested += invested
                current_value += val
                pnl_val = pos.get("pnl") or 0
                total_pnl += pnl_val
                if pnl_val > 0:
                    wins += 1
                elif pnl_val < 0:
                    losses += 1

        total_closed = wins + losses
        win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else 0
        return {
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_percent": round(total_pnl / total_invested * 100, 2) if total_invested > 0 else 0,
            "win_rate": win_rate,
            "active_count": active_count,
            "pending_count": pending_count,
            "closed_count": closed_count,
            "total_signals": active_count + pending_count + closed_count,
            "wins": wins,
            "losses": losses,
        }

    def get_positions(self, status_filter: Optional[str] = None) -> list[dict]:
        return self._get_positions(status_filter)

    def get_symbol_stats(self) -> list[dict]:
        positions = self._get_positions()
        symbol_map = {}
        for pos in positions:
            sym = pos["symbol"]
            if sym not in symbol_map:
                symbol_map[sym] = {"symbol": sym, "sector": pos.get("sector", "Unknown"),
                                   "total_signals": 0, "active": 0, "pending": 0,
                                   "closed_wins": 0, "closed_losses": 0, "total_pnl": 0.0}
            stat = symbol_map[sym]
            stat["total_signals"] += 1
            if pos["status"] == STATUS_ACTIVE:
                stat["active"] += 1
            elif pos["status"] == STATUS_PENDING_ENTRY:
                stat["pending"] += 1
            elif pos["status"] == STATUS_CLOSED:
                pnl_val = pos.get("pnl") or 0
                stat["total_pnl"] += pnl_val
                if pnl_val > 0:
                    stat["closed_wins"] += 1
                elif pnl_val < 0:
                    stat["closed_losses"] += 1

        return [{
            "symbol": s["symbol"], "sector": s["sector"],
            "total_signals": s["total_signals"], "active": s["active"],
            "pending": s["pending"],
            "closed_wins": s["closed_wins"], "closed_losses": s["closed_losses"],
            "win_rate": round(s["closed_wins"] / max(1, s["closed_wins"] + s["closed_losses"]) * 100, 1),
            "avg_pnl_percent": 0,
            "total_pnl": round(s["total_pnl"], 2),
        } for s in sorted(symbol_map.values())]

    # ─── Market Hours Detection ─────────────────────────────────────

    @staticmethod
    def _is_market_hours(now: datetime, allow_before_open: bool = False) -> bool:
        hour_ist = (now.hour + 5) % 24
        minute_ist = now.minute + 30
        if minute_ist >= 60:
            hour_ist = (hour_ist + 1) % 24
            minute_ist -= 60
        weekday_ist = now.weekday()
        if weekday_ist >= 5:
            return False
        if allow_before_open:
            return True
        if hour_ist < MARKET_OPEN_HOUR or (hour_ist == MARKET_OPEN_HOUR and minute_ist < MARKET_OPEN_MIN):
            return False
        if hour_ist > MARKET_CLOSE_HOUR or (hour_ist == MARKET_CLOSE_HOUR and minute_ist > MARKET_CLOSE_MIN):
            return False
        return True

    @staticmethod
    def get_entry_time() -> datetime:
        now = datetime.now()
        return now.replace(hour=9, minute=30, second=0, microsecond=0)


# ─── Module-level convenience ──────────────────────────────────────
_default_tracker = None


def get_tracker(db_path: str = None) -> TradeTracker:
    global _default_tracker
    if _default_tracker is None:
        _default_tracker = TradeTracker(db_path)
    return _default_tracker


def reset_tracker():
    global _default_tracker
    _default_tracker = None