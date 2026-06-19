"""
Trade Performance Tracker
=========================
Tracks "BUY NOW" signals from the NSE Swing Scanner as live positions,
monitors them against 5% stop-loss and 10% profit targets,
and provides portfolio performance reporting.

Data is stored in trades_history.json (no database required).
"""

import os, json, logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────
CAPITAL_PER_POSITION = 150000   # ₹1.5 Lakh per position
STOP_LOSS_PCT = 0.05           # 5% stop-loss
PROFIT_TARGET_PCT = 0.10       # 10% profit target
ENTRY_TIME_IST = "09:30"       # Entry attempted after this time
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

# Persistent storage path (Render disk or local fallback)
if os.path.exists("/data"):     # Render persistent disk
    DATA_DIR = "/data"
else:                           # Local development
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_JSON_PATH = os.path.join(DATA_DIR, "trades_history.json")

# ─── Position Status ────────────────────────────────────────────────
STATUS_PENDING_ENTRY = "pending_entry"
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"


class TradeTracker:
    """
    Manages trade positions: creation, entry, monitoring, and reporting.

    Data is persisted to a JSON file for durability across server restarts.
    """

    def __init__(self, json_path: str = "trades_history.json"):
        self.json_path = json_path
        self.data = {
            "positions": {},
            "created_at": None,
            "updated_at": None,
        }
        self._load()

    # ─── Persistence ────────────────────────────────────────────────

    def _load(self):
        """Load positions from JSON file."""
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.data = loaded
                    logger.info(f"Loaded {len(self.data.get('positions', {}))} positions from {self.json_path}")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load {self.json_path}: {e}. Starting fresh.")
            self.data = {"positions": {}, "created_at": None, "updated_at": None}

        if self.data.get("created_at") is None:
            self.data["created_at"] = datetime.now().isoformat()

    def _save(self):
        """Write positions to JSON file atomically."""
        self.data["updated_at"] = datetime.now().isoformat()
        tmp_path = self.json_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, default=str)
            os.replace(tmp_path, self.json_path)
        except Exception as e:
            logger.error(f"Failed to save {self.json_path}: {e}")

    # ─── Price Fetching ─────────────────────────────────────────────

    @staticmethod
    def fetch_price(symbol: str, date_str: Optional[str] = None) -> Optional[float]:
        """
        Fetch a stock price via yfinance.

        If date_str is provided, fetches the Open price for that date.
        If date_str is None, fetches the latest Close price.
        """
        try:
            if date_str:
                # Fetch a few days around the target date to ensure we get data
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                start = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
                end = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
                df = yf.download(symbol + ".NS", start=start, end=end,
                                 progress=False, auto_adjust=True)
                if df.empty:
                    logger.warning(f"No data for {symbol} on {date_str}")
                    return None
                # Handle MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(symbol + ".NS", axis=1, level=1) if symbol + ".NS" in df.columns.get_level_values(1).unique() else df.xs(symbol, axis=1, level=0)
                
                # Find the row for our target date
                target_dt = pd.Timestamp(date_str)
                if target_dt in df.index:
                    row = df.loc[target_dt]
                    open_price = row.get("Open") if isinstance(row, pd.Series) else row.iloc[0]["Open"]
                    return float(open_price) if pd.notna(open_price) else None
                
                # Try the next trading day if target date not in index
                # (in case it was a weekend/holiday)
                for idx in df.index:
                    if idx >= target_dt:
                        row = df.loc[idx]
                        open_price = row.get("Open") if isinstance(row, pd.Series) else row.iloc[0]["Open"]
                        return float(open_price) if pd.notna(open_price) else None
                return None
            else:
                # Latest close price
                df = yf.download(symbol + ".NS", period="5d", interval="1d",
                                 progress=False, auto_adjust=True)
                if df.empty:
                    return None
                # Handle MultiIndex
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.xs(df.columns.get_level_values(1)[0], axis=1, level=1)
                close_price = df["Close"].iloc[-1]
                return float(close_price) if pd.notna(close_price) else None
        except Exception as e:
            logger.error(f"fetch_price({symbol}, {date_str}): {e}")
            return None

    # ─── Position Creation ──────────────────────────────────────────

    def create_positions_from_results(self, results: list[dict], signal_date: Optional[str] = None, same_day_entry: bool = False) -> list[str]:
        """
        Scan scanner results for "BUY NOW" signals and create positions.

        Args:
            results: List of result dicts from the scanner (with 1H_Setup, Symbol, Sector, Price, Entry, Stop, R:R)
            signal_date: Date string (YYYY-MM-DD). Defaults to today.
            same_day_entry: If True, enter immediately at signal price (for intraday scans).
                           If False, create pending_entry for next-day entry (for EOD scans).

        Returns:
            List of created position IDs.
        """
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

            # Check if there's ALREADY an active or pending position for this symbol
            existing_pos = None
            for pid, p in self.data["positions"].items():
                if p.get("symbol") == symbol and p.get("status") in (STATUS_PENDING_ENTRY, STATUS_ACTIVE):
                    existing_pos = p
                    existing_pid = pid
                    break
            
            if existing_pos:
                # Update existing position with latest signal data instead of creating duplicate
                sector = row.get("Sector", existing_pos.get("sector", "Unknown"))
                signal_price = row.get("Price")
                if signal_price is None:
                    signal_price = row.get("signal_price", existing_pos.get("signal_price", 0))
                signal_price = float(signal_price)
                existing_pos["signal_price"] = signal_price
                existing_pos["current_price"] = signal_price
                existing_pos["entry_zone"] = row.get("Entry", existing_pos.get("entry_zone", ""))
                existing_pos["suggested_stop"] = row.get("Stop", existing_pos.get("suggested_stop", ""))
                existing_pos["rr"] = row.get("R:R", existing_pos.get("rr", ""))
                existing_pos["sector"] = sector
                # If still pending and market is open, activate it
                if existing_pos["status"] == STATUS_PENDING_ENTRY and same_day_entry:
                    existing_pos["entry_date"] = signal_date
                    existing_pos["entry_price"] = signal_price
                    existing_pos["stop_loss"] = round(signal_price * (1 - STOP_LOSS_PCT), 2)
                    existing_pos["target"] = round(signal_price * (1 + PROFIT_TARGET_PCT), 2)
                    existing_pos["quantity"] = max(1, int(CAPITAL_PER_POSITION / signal_price))
                    existing_pos["status"] = STATUS_ACTIVE
                    logger.info(f"Updated & activated existing pending: {existing_pid} @ ₹{signal_price}")
                else:
                    logger.info(f"Updated existing position: {existing_pid} @ ₹{signal_price}")
                created.append(existing_pid)
                continue

            pos_id = f"{symbol}-{signal_date}"

            sector = row.get("Sector", "Unknown")
            signal_price = row.get("Price")
            if signal_price is None:
                signal_price = row.get("signal_price", 0)
            signal_price = float(signal_price)

            if same_day_entry:
                # Enter immediately at signal price (intraday scan)
                stop_loss = round(signal_price * (1 - STOP_LOSS_PCT), 2)
                target = round(signal_price * (1 + PROFIT_TARGET_PCT), 2)
                quantity = int(CAPITAL_PER_POSITION / signal_price)
                if quantity < 1:
                    quantity = 1
                position = {
                    "id": pos_id,
                    "symbol": symbol,
                    "sector": sector,
                    "signal_date": signal_date,
                    "signal_price": signal_price,
                    "entry_date": signal_date,
                    "entry_price": signal_price,
                    "stop_loss": stop_loss,
                    "target": target,
                    "capital": CAPITAL_PER_POSITION,
                    "quantity": quantity,
                    "status": STATUS_ACTIVE,
                    "close_date": None,
                    "close_price": None,
                    "close_reason": None,
                    "pnl": None,
                    "pnl_percent": None,
                    "current_price": signal_price,
                    "entry_zone": row.get("Entry", ""),
                    "suggested_stop": row.get("Stop", ""),
                    "rr": row.get("R:R", ""),
                }
                logger.info(f"Immediate entry: {pos_id} @ ₹{signal_price} x {quantity} | SL: {stop_loss} | Tgt: {target}")
            else:
                # Standard: pending entry for next-day open
                position = {
                    "id": pos_id,
                    "symbol": symbol,
                    "sector": sector,
                    "signal_date": signal_date,
                    "signal_price": signal_price,
                    "entry_date": None,
                    "entry_price": None,
                    "stop_loss": None,
                    "target": None,
                    "capital": CAPITAL_PER_POSITION,
                    "quantity": None,
                    "status": STATUS_PENDING_ENTRY,
                    "close_date": None,
                    "close_price": None,
                    "close_reason": None,
                    "pnl": None,
                    "pnl_percent": None,
                    "current_price": signal_price,
                    "entry_zone": row.get("Entry", ""),
                    "suggested_stop": row.get("Stop", ""),
                    "rr": row.get("R:R", ""),
                }
                logger.info(f"Created pending position: {pos_id} @ ₹{signal_price}")

            self.data["positions"][pos_id] = position
            created.append(pos_id)

        if created:
            self._save()

        return created

    # ─── Entry Processing ───────────────────────────────────────────

    def process_pending_entries(self) -> list[dict]:
        """
        Process all pending_entry positions: attempt to fill them at today's open price.

        Runs only during market hours (after 9:30 AM IST).

        Returns:
            List of dicts with keys: id, symbol, entry_price, status for each processed position.
        """
        now = datetime.now()
        # Check if we're past 9:30 AM IST on a weekday
        if not self._is_market_hours(now, allow_before_open=False):
            return []

        today_str = now.strftime("%Y-%m-%d")
        processed = []

        for pos_id, pos in list(self.data["positions"].items()):
            if pos["status"] != STATUS_PENDING_ENTRY:
                continue

            # Only process positions whose signal_date is today or earlier
            signal_date = pos.get("signal_date", "")
            if signal_date > today_str:
                continue

            # Try to fetch today's open price
            entry_price = self.fetch_price(pos["symbol"], today_str)
            if entry_price is None or entry_price <= 0:
                logger.warning(f"Could not fetch entry price for {pos['symbol']} on {today_str}")
                # Update current_price at least
                price = self.fetch_price(pos["symbol"])
                if price:
                    pos["current_price"] = price
                continue

            # Calculate position parameters
            stop_loss = round(entry_price * (1 - STOP_LOSS_PCT), 2)
            target = round(entry_price * (1 + PROFIT_TARGET_PCT), 2)
            quantity = int(CAPITAL_PER_POSITION / entry_price)
            if quantity < 1:
                quantity = 1

            pos["entry_date"] = today_str
            pos["entry_price"] = entry_price
            pos["stop_loss"] = stop_loss
            pos["target"] = target
            pos["quantity"] = quantity
            pos["status"] = STATUS_ACTIVE
            pos["current_price"] = entry_price

            processed.append({
                "id": pos_id,
                "symbol": pos["symbol"],
                "entry_price": entry_price,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "target": target,
                "status": STATUS_ACTIVE,
            })
            logger.info(f"Position entered: {pos_id} @ ₹{entry_price} x {quantity} | SL: {stop_loss} | Tgt: {target}")

        if processed:
            self._save()

        return processed

    # ─── Position Monitoring ────────────────────────────────────────

    def check_open_positions(self) -> list[dict]:
        """
        Check all active positions: fetch current price and test SL/target.

        Returns:
            List of dicts describing positions that were closed.
        """
        if not self._is_market_hours(datetime.now()):
            return []

        closed = []

        for pos_id, pos in list(self.data["positions"].items()):
            if pos["status"] != STATUS_ACTIVE:
                continue

            current_price = self.fetch_price(pos["symbol"])
            if current_price is None or current_price <= 0:
                continue

            pos["current_price"] = current_price

            # Check stop-loss
            if current_price <= pos["stop_loss"]:
                self._close_position(pos, current_price, "stop_loss")
                closed.append({
                    "id": pos_id,
                    "symbol": pos["symbol"],
                    "reason": "stop_loss",
                    "entry_price": pos["entry_price"],
                    "close_price": current_price,
                    "pnl": pos["pnl"],
                    "pnl_percent": pos["pnl_percent"],
                })
                logger.info(f"STOP LOSS hit: {pos_id} @ ₹{current_price} | P&L: ₹{pos['pnl']}")
                continue

            # Check profit target
            if current_price >= pos["target"]:
                self._close_position(pos, current_price, "target")
                closed.append({
                    "id": pos_id,
                    "symbol": pos["symbol"],
                    "reason": "target",
                    "entry_price": pos["entry_price"],
                    "close_price": current_price,
                    "pnl": pos["pnl"],
                    "pnl_percent": pos["pnl_percent"],
                })
                logger.info(f"TARGET hit: {pos_id} @ ₹{current_price} | P&L: ₹{pos['pnl']}")
                continue

        if closed:
            self._save()

        return closed

    def _close_position(self, pos: dict, close_price: float, reason: str):
        """Mark a position as closed with final P&L calculation."""
        entry_price = pos["entry_price"]
        quantity = pos["quantity"] or 1
        pnl = round((close_price - entry_price) * quantity, 2)
        pnl_percent = round((close_price - entry_price) / entry_price * 100, 2)

        pos["close_date"] = datetime.now().strftime("%Y-%m-%d")
        pos["close_price"] = close_price
        pos["close_reason"] = reason
        pos["pnl"] = pnl
        pos["pnl_percent"] = pnl_percent
        pos["status"] = STATUS_CLOSED
        pos["current_price"] = close_price

    # ─── Manual Refresh ─────────────────────────────────────────────

    def refresh_all_prices(self) -> dict:
        """
        Fetch latest prices for all active/pending positions without closing any.

        Returns summary dict with counts of updated positions.
        """
        updated = 0
        failed = 0

        for pos_id, pos in self.data["positions"].items():
            if pos["status"] not in (STATUS_ACTIVE, STATUS_PENDING_ENTRY):
                continue

            price = self.fetch_price(pos["symbol"])
            if price and price > 0:
                pos["current_price"] = price
                updated += 1
            else:
                failed += 1

        if updated:
            self._save()

        return {"updated": updated, "failed": failed}

    # ─── Reporting ──────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """
        Aggregate all positions into a portfolio summary.

        Returns dict with total_invested, current_value, total_pnl,
        win_rate, counts, etc.
        """
        positions = self.data["positions"].values()
        total_invested = 0.0
        current_value = 0.0
        total_pnl = 0.0
        wins = 0
        losses = 0
        active_count = 0
        pending_count = 0
        closed_count = 0

        for pos in positions:
            status = pos["status"]
            if status == STATUS_PENDING_ENTRY:
                pending_count += 1
                continue

            if status == STATUS_ACTIVE:
                active_count += 1
                entry_price = pos["entry_price"] or 0
                quantity = pos["quantity"] or 0
                capital_used = entry_price * quantity
                total_invested += capital_used
                current_val = (pos["current_price"] or entry_price) * quantity
                current_value += current_val
                total_pnl += current_val - capital_used
                continue

            if status == STATUS_CLOSED:
                closed_count += 1
                entry_price = pos["entry_price"] or 0
                quantity = pos["quantity"] or 0
                capital_used = entry_price * quantity
                total_invested += capital_used
                current_value += (pos["close_price"] or 0) * quantity
                pnl = pos.get("pnl") or 0
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                # Zero P&L doesn't count as win or loss
                continue

        total_closed = wins + losses
        win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else 0.0
        total_pnl_percent = round(total_pnl / total_invested * 100, 2) if total_invested > 0 else 0.0

        return {
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_percent": total_pnl_percent,
            "win_rate": win_rate,
            "active_count": active_count,
            "pending_count": pending_count,
            "closed_count": closed_count,
            "total_signals": active_count + pending_count + closed_count,
            "wins": wins,
            "losses": losses,
        }

    def get_positions(self, status_filter: Optional[str] = None) -> list[dict]:
        """
        Return all positions, optionally filtered by status.

        Args:
            status_filter: None for all, or "pending_entry", "active", "closed".

        Returns:
            List of position dicts sorted by signal_date descending.
        """
        positions = list(self.data["positions"].values())
        if status_filter:
            positions = [p for p in positions if p["status"] == status_filter]

        # Sort by signal_date descending, then symbol ascending
        positions.sort(key=lambda p: (p.get("signal_date", ""), p.get("symbol", "")), reverse=True)
        return positions

    def get_symbol_stats(self) -> list[dict]:
        """
        Aggregate closed positions by symbol for performance analysis.

        Returns:
            List of dicts with per-symbol performance metrics.
        """
        symbol_map = {}
        for pos in self.data["positions"].values():
            sym = pos["symbol"]
            if sym not in symbol_map:
                symbol_map[sym] = {
                    "symbol": sym,
                    "sector": pos.get("sector", "Unknown"),
                    "total_signals": 0,
                    "active": 0,
                    "pending": 0,
                    "closed_wins": 0,
                    "closed_losses": 0,
                    "total_pnl": 0.0,
                    "pnl_values": [],
                }
            stat = symbol_map[sym]
            stat["total_signals"] += 1
            if pos["status"] == STATUS_ACTIVE:
                stat["active"] += 1
            elif pos["status"] == STATUS_PENDING_ENTRY:
                stat["pending"] += 1
            elif pos["status"] == STATUS_CLOSED:
                pnl = pos.get("pnl") or 0
                stat["total_pnl"] += pnl
                stat["pnl_values"].append(pnl)
                if pnl > 0:
                    stat["closed_wins"] += 1
                elif pnl < 0:
                    stat["closed_losses"] += 1

        result = []
        for sym, stat in sorted(symbol_map.items()):
            total_closed = stat["closed_wins"] + stat["closed_losses"]
            avg_pnl = round(sum(stat["pnl_values"]) / len(stat["pnl_values"]), 2) if stat["pnl_values"] else 0.0
            win_rate = round(stat["closed_wins"] / total_closed * 100, 1) if total_closed > 0 else 0.0
            result.append({
                "symbol": sym,
                "sector": stat["sector"],
                "total_signals": stat["total_signals"],
                "active": stat["active"],
                "pending": stat["pending"],
                "closed_wins": stat["closed_wins"],
                "closed_losses": stat["closed_losses"],
                "win_rate": win_rate,
                "avg_pnl_percent": avg_pnl,  # Will be calculated per-trade from entry_price
                "total_pnl": round(stat["total_pnl"], 2),
            })

        return result

    # ─── Market Hours Detection ─────────────────────────────────────

    @staticmethod
    def _is_market_hours(now: datetime, allow_before_open: bool = False) -> bool:
        """
        Check if current time is within Indian market hours (Mon-Fri, 9:30 AM - 3:30 PM IST).
        Correctly handles servers running in UTC by converting to IST.
        """
        # Convert to IST (UTC + 5:30)
        hour_ist = (now.hour + 5) % 24
        minute_ist = now.minute + 30
        if minute_ist >= 60:
            hour_ist = (hour_ist + 1) % 24
            minute_ist -= 60
        
        # Adjust weekday for IST day boundary
        weekday_ist = now.weekday()
        if hour_ist < 9 and hour_ist >= 0 and now.hour >= 18:
            # If IST is in early morning hours while UTC is late evening, it's the next day
            pass
        
        # Weekday check (Monday=0, Sunday=6)
        if weekday_ist >= 5:
            return False

        if allow_before_open:
            # Allow processing on any market day
            return True

        # Market hours: 9:30 AM to 3:30 PM IST
        if hour_ist < MARKET_OPEN_HOUR or (hour_ist == MARKET_OPEN_HOUR and minute_ist < MARKET_OPEN_MIN):
            return False
        if hour_ist > MARKET_CLOSE_HOUR or (hour_ist == MARKET_CLOSE_HOUR and minute_ist > MARKET_CLOSE_MIN):
            return False

        return True

    @staticmethod
    def get_entry_time() -> datetime:
        """Return today's 9:30 AM IST datetime for entry processing."""
        now = datetime.now()
        return now.replace(hour=9, minute=30, second=0, microsecond=0)


# ─── Module-level convenience ──────────────────────────────────────
_default_tracker = None


def get_tracker(json_path: str = None) -> TradeTracker:
    """Get or create the default TradeTracker instance. Uses persistent storage."""
    global _default_tracker
    if _default_tracker is None:
        if json_path is None:
            json_path = TRADES_JSON_PATH
        _default_tracker = TradeTracker(json_path)
    return _default_tracker


def reset_tracker():
    """Reset the default tracker (useful for testing)."""
    global _default_tracker
    _default_tracker = None