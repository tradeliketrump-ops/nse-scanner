"""
Futures Trade Tracker
=====================
Tracks futures positions with 1 Qty, no auto SL/Target.
Same-day entry during market hours, next-day entry after close.
"""
import os, json, logging
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending_entry"
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"


class FuturesTracker:
    def __init__(self, json_path: str = "futures_history.json"):
        self.json_path = json_path
        self.data = {"positions": {}, "created_at": None, "updated_at": None}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
        except:
            self.data = {"positions": {}, "created_at": datetime.now().isoformat(), "updated_at": None}

    def _save(self):
        self.data["updated_at"] = datetime.now().isoformat()
        try:
            with open(self.json_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, default=str)
            os.replace(self.json_path + ".tmp", self.json_path)
        except Exception as e:
            logger.error(f"Futures save error: {e}")

    def fetch_price(self, symbol: str) -> Optional[float]:
        """Fetch latest price for a futures symbol via yfinance."""
        try:
            import yfinance as yf
            import pandas as pd
            df = yf.download(symbol, period="5d", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                tickers = df.columns.get_level_values(1).unique()
                if len(tickers) > 0:
                    df = df.xs(tickers[0], axis=1, level=1).copy()
            if df is not None and len(df) > 0 and "Close" in df.columns:
                last = df["Close"].iloc[-1]
                return float(last) if pd.notna(last) else None
        except Exception as e:
            logger.error(f"Futures fetch_price({symbol}): {e}")
        return None

    def create_position(self, symbol: str, name: str, category: str, price: float,
                        signal_date: Optional[str] = None, same_day: bool = False) -> str:
        """Create a FUT position with 1 Qty. same_day=True for intraday entry."""
        if signal_date is None:
            signal_date = date.today().isoformat()
        pos_id = f"{symbol}-{signal_date}"
        if pos_id in self.data["positions"]:
            logger.info(f"FUT position {pos_id} exists, skipping")
            return pos_id

        if same_day:
            entry_price = price
            position = {
                "id": pos_id, "symbol": symbol, "name": name, "category": category,
                "signal_date": signal_date, "signal_price": price,
                "entry_date": signal_date, "entry_price": entry_price,
                "quantity": 1, "status": STATUS_ACTIVE,
                "close_date": None, "close_price": None, "close_reason": None,
                "pnl": None, "pnl_percent": None, "current_price": price,
            }
            logger.info(f"FUT same-day entry: {pos_id} @ {price}")
        else:
            position = {
                "id": pos_id, "symbol": symbol, "name": name, "category": category,
                "signal_date": signal_date, "signal_price": price,
                "entry_date": None, "entry_price": None,
                "quantity": 1, "status": STATUS_PENDING,
                "close_date": None, "close_price": None, "close_reason": None,
                "pnl": None, "pnl_percent": None, "current_price": price,
            }
            logger.info(f"FUT pending: {pos_id} @ {price}")

        self.data["positions"][pos_id] = position
        self._save()
        return pos_id

    def process_pending_entries(self) -> list:
        """Activate pending entries at today's open price."""
        now = datetime.now()
        # Only process on weekdays
        if now.weekday() >= 5:
            return []
        today_str = now.strftime("%Y-%m-%d")
        processed = []
        for pos_id, pos in list(self.data["positions"].items()):
            if pos["status"] != STATUS_PENDING:
                continue
            if pos.get("signal_date", "") > today_str:
                continue
            price = self.fetch_price(pos["symbol"])
            if price and price > 0:
                pos["entry_date"] = today_str
                pos["entry_price"] = price
                pos["status"] = STATUS_ACTIVE
                pos["current_price"] = price
                processed.append(pos_id)
                logger.info(f"FUT entry activated: {pos_id} @ {price}")
        if processed:
            self._save()
        return processed

    def refresh_all_prices(self) -> dict:
        """Update current prices for all active/pending positions."""
        updated = 0
        failed = 0
        for pos_id, pos in self.data["positions"].items():
            if pos["status"] not in (STATUS_ACTIVE, STATUS_PENDING):
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

    def close_position(self, pos_id: str, reason: str = "manual") -> Optional[dict]:
        """Manually close a position at current price."""
        pos = self.data["positions"].get(pos_id)
        if not pos or pos["status"] != STATUS_ACTIVE:
            return None
        price = self.fetch_price(pos["symbol"]) or pos["current_price"]
        entry = pos["entry_price"] or pos["signal_price"]
        pnl = round((price - entry) * pos["quantity"], 2)
        pnl_pct = round((price - entry) / entry * 100, 2) if entry else 0
        pos["close_date"] = date.today().isoformat()
        pos["close_price"] = price
        pos["close_reason"] = reason
        pos["pnl"] = pnl
        pos["pnl_percent"] = pnl_pct
        pos["status"] = STATUS_CLOSED
        pos["current_price"] = price
        self._save()
        return pos

    def get_positions(self, status_filter: Optional[str] = None) -> list:
        positions = list(self.data["positions"].values())
        if status_filter:
            positions = [p for p in positions if p["status"] == status_filter]
        positions.sort(key=lambda p: p.get("signal_date", ""), reverse=True)
        return positions

    def get_portfolio_summary(self) -> dict:
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
            s = pos["status"]
            entry = pos["entry_price"] or 0
            if s == STATUS_PENDING:
                pending_count += 1
                continue
            if s == STATUS_ACTIVE:
                active_count += 1
                invested = entry * pos["quantity"]
                val = (pos["current_price"] or entry) * pos["quantity"]
                total_invested += invested
                current_value += val
                total_pnl += val - invested
            elif s == STATUS_CLOSED:
                closed_count += 1
                invested = entry * pos["quantity"]
                val = (pos["close_price"] or 0) * pos["quantity"]
                total_invested += invested
                current_value += val
                pnl = pos.get("pnl") or 0
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
        total_closed = wins + losses
        win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else 0
        return {
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "total_pnl": round(total_pnl, 2),
            "win_rate": win_rate,
            "active_count": active_count,
            "pending_count": pending_count,
            "closed_count": closed_count,
            "total_signals": active_count + pending_count + closed_count,
            "wins": wins,
            "losses": losses,
        }


_default_futures_tracker = None


def get_futures_tracker(json_path: str = "futures_history.json") -> FuturesTracker:
    global _default_futures_tracker
    if _default_futures_tracker is None:
        _default_futures_tracker = FuturesTracker(json_path)
    return _default_futures_tracker


def reset_futures_tracker():
    global _default_futures_tracker
    _default_futures_tracker = None