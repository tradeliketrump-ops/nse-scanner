# Implementation Plan

Add a trade performance tracking system to the NSE Swing Scanner that automatically logs "BUY NOW" signals as positions, tracks them against 5% stop-loss and 10% profit targets with a capital of ₹1.5L per position, and displays portfolio performance on the dashboard.

The current system scans stocks daily and generates a watchlist with "BUY NOW"/"WATCH"/"WAIT" classifications but has no mechanism to track whether those signals actually performed well. This implementation adds a persistent trade journal stored in `trades_history.json`, a background scheduler that checks position prices during market hours, and a new portfolio dashboard section. The entry price is the next-day open price after 9:30 AM IST (15 min after market opens), and positions remain open indefinitely until either the 5% stop-loss or 10% profit target is hit. The entire system runs within the existing FastAPI server without needing any external database.

[Types]

A set of JSON-serializable data structures stored in `trades_history.json` representing positions, portfolio state, and entry/exit records.

### PositionStatus (enum values stored as strings)
- `"pending_entry"` — Signal received, waiting for next-day open price entry
- `"active"` — Entry price set, position is live and being monitored
- `"closed"` — Position closed by hitting SL or target

### Position (dictionary shape stored in trades_history.json)
```
{
  "id": str,                    // "{symbol}-{signal_date}" e.g. "TRENT-2026-06-15"
  "symbol": str,                // e.g. "TRENT"
  "sector": str,                // e.g. "Consumer"
  "signal_date": str,           // ISO date "2026-06-15"
  "signal_price": float,        // Price when BUY NOW signal was generated
  "entry_date": str | null,     // ISO date when entry was filled
  "entry_price": float | null,  // Open price on entry date
  "stop_loss": float | null,    // entry_price * 0.95
  "target": float | null,       // entry_price * 1.10
  "capital": 150000,            // Fixed capital per position
  "quantity": int | null,       // floor(capital / entry_price)
  "status": PositionStatus,
  "close_date": str | null,     // ISO date when closed
  "close_price": float | null,
  "close_reason": str | null,   // "stop_loss" | "target"
  "pnl": float | null,          // Total profit/loss in rupees
  "pnl_percent": float | null,  // Percentage return
  "current_price": float | null // Latest known price (for active positions)
}
```

### PortfolioSummary (returned by API)
```
{
  "total_invested": float,
  "current_value": float,
  "total_pnl": float,
  "total_pnl_percent": float,
  "win_rate": float,           // % of closed positions profitable
  "active_count": int,
  "pending_count": int,
  "closed_count": int,
  "wins": int,
  "losses": int
}
```

### PerformanceStats (per-symbol stats)
```
{
  "symbol": str,
  "sector": str,
  "total_signals": int,
  "active": int,
  "closed_wins": int,
  "closed_losses": int,
  "avg_pnl_percent": float,
  "total_pnl": float
}
```

[Files]

A new module for trade tracking logic, a JSON file for persistent storage, and modifications to the API server and dashboard template.

### New Files

1. **`trade_tracker.py`** — Core trade tracking module containing:
   - `TradeTracker` class that reads/writes `trades_history.json`
   - `create_positions_from_results(results: list[dict]) → list[Position]` — Scans watchlist results for "BUY NOW" signals and creates pending_entry positions
   - `check_open_positions() → list[str]` — Fetches current prices for all active positions and closes them if SL/target hit
   - `process_pending_entries() → list[str]` — Fetches today's open prices for pending_entry positions during market hours
   - `get_portfolio_summary() → PortfolioSummary`
   - `get_position_history() → dict` — Returns all positions grouped by status
   - `fetch_price(symbol: str, date_str: str) → float | None` — Fetches open/current price via yfinance

2. **`trades_history.json`** (auto-created) — Persistent store with structure:
   ```json
   {
     "positions": {
       "TRENT-2026-06-15": { ... Position ... },
       ...
     },
     "created_at": "2026-06-15T19:00:00",
     "updated_at": "2026-06-16T09:45:00"
   }
   ```

### Modified Files

3. **`nse_scanner_api.py`** — Major additions:
   - Import `TradeTracker` from `trade_tracker.py`
   - Add new API endpoints (see Functions section)
   - Integrate trade creation into `run_scan_task()` — after scan completes, call `tracker.create_positions_from_results()`
   - Add APScheduler integration for the background price-checking task (runs every 15 min during market hours, 9:30 AM–3:30 PM IST Mon-Fri)
   - Add startup initialization of the scheduler

4. **`templates/dashboard.html`** — Add a "Portfolio" tab/section with:
   - Portfolio summary card (total invested, current value, P&L, win rate)
   - Open positions table (entry price, current price, P&L, status)
   - Pending entries table
   - Closed trades history table
   - Per-symbol performance breakdown
   - Navigation tabs to switch between "Watchlist" and "Portfolio" views

5. **`requirements.txt`** — Add `apscheduler` (already present but let's confirm version compatibility)

[Functions]

### New Functions in `trade_tracker.py`

1. **`TradeTracker.__init__(self, json_path: str = "trades_history.json")`**
   - Loads existing JSON file or creates empty structure

2. **`TradeTracker._save(self) -> None`**
   - Writes in-memory state to JSON file with atomic write

3. **`TradeTracker._load(self) -> None`**
   - Reads JSON file into memory, handles missing/corrupt files

4. **`TradeTracker.create_positions_from_results(self, results: list[dict], signal_date: str | None = None) -> list[str]`**
   - Input: List of scan result dicts (from `/api/watchlist/latest-data` format)
   - Logic: For each result where `1H_Setup == "BUY NOW"`, check if a position already exists for that symbol+date. If not, create a `pending_entry` position.
   - Returns: List of created position IDs

5. **`TradeTracker.process_pending_entries(self) -> list[str]`**
   - Logic: For all `pending_entry` positions, check if current time >= entry_date 9:30 AM IST. If yes, fetch today's open price via yfinance. Set `entry_price`, `stop_loss`, `target`, `quantity`. If price fetch succeeds, set status to `active`. If price fetch fails, keep as `pending_entry` (retry later).
   - Returns: List of position IDs that were activated

6. **`TradeTracker.check_open_positions(self) -> list[dict]`**
   - Logic: For all `active` positions, fetch current price via yfinance.
   - If `current_price <= stop_loss`: Close position with reason `stop_loss`, calculate P&L
   - If `current_price >= target`: Close position with reason `target`, calculate P&L
   - Otherwise: Update `current_price`
   - Returns: List of dicts with `{id, reason, pnl, pnl_percent}` for closed positions

7. **`TradeTracker.fetch_price(self, symbol: str, date_str: str | None = None, interval: str = "1d") -> float | None`**
   - Wraps yfinance.download to get price data
   - If `date_str` is provided, fetches open price for that specific date
   - If `date_str` is None, fetches the latest close price
   - Returns: Price or None on failure

8. **`TradeTracker.get_portfolio_summary(self) -> dict`**
   - Aggregates all positions into PortfolioSummary
   - Calculates win rate, total P&L, active/pending/closed counts

9. **`TradeTracker.get_positions(self, status_filter: str | None = None) -> list[dict]`**
   - Returns all positions, optionally filtered by status

10. **`TradeTracker.get_symbol_stats(self) -> list[dict]`**
    - Groups closed positions by symbol, calculates per-symbol win rate and avg P&L

### New Functions in `nse_scanner_api.py`

11. **`start_scheduler() -> BackgroundScheduler`**
    - Creates an APScheduler BackgroundScheduler
    - Adds a job: `check_trades()` every 15 minutes
    - Adds market hours detection (9:30 AM–3:30 PM IST, Mon-Fri)
    - Returns the scheduler instance

12. **`check_trades() -> None`**
    - Called by scheduler
    - Instantiates TradeTracker
    - Calls `process_pending_entries()` and `check_open_positions()`
    - Logs results for dashboard polling

13. **`activate_pending_entries() -> dict`**
    - Called by scheduler, specifically processes pending → active transitions
    - Separate from check_trades for clarity

### New API Endpoints in `nse_scanner_api.py`

14. **`GET /api/trades/portfolio`**
    - Returns portfolio summary (total invested, current value, P&L, win rate, counts)

15. **`GET /api/trades/positions?status=all|active|pending|closed`**
    - Returns list of positions filtered by status

16. **`GET /api/trades/symbol-stats`**
    - Returns per-symbol performance breakdown

17. **`POST /api/trades/refresh-prices`**
    - Manually triggers price check for all open positions (for manual refresh from dashboard)

### Modified Function in `nse_scanner_api.py`

18. **`run_scan_task(task_id, early_mode)`** (modified)
    - After scan completes successfully and has results, instantiate TradeTracker
    - Call `tracker.create_positions_from_results(result_json)`

### New Dashboard Functions in `templates/dashboard.html`

19. **`loadPortfolio() -> void`**
    - Fetches `/api/trades/portfolio` and renders summary cards

20. **`loadPositions(status) -> void`**
    - Fetches `/api/trades/positions?status=X` and renders positions table

21. **`renderPortfolioTab() -> void`**
    - Main entry point for switching to portfolio view
    - Calls `loadPortfolio()`, `loadPositions('active')`, etc.

22. **`renderPositionsTable(positions, containerId) -> void`**
    - Renders positions data into an HTML table with appropriate coloring

[Classes]

No new Python classes beyond the `TradeTracker` class described in the Functions section. No existing classes are modified.

### TradeTracker
- **File**: `trade_tracker.py`
- **Key Methods**: `__init__`, `_save`, `_load`, `create_positions_from_results`, `process_pending_entries`, `check_open_positions`, `fetch_price`, `get_portfolio_summary`, `get_positions`, `get_symbol_stats`
- **State**: In-memory dict from `trades_history.json`, persisted on every mutation

[Dependencies]

No new packages required. The existing `apscheduler==3.10.4` in `requirements.txt` is sufficient for the scheduled background task. `yfinance` (already used) is used for price fetching.

[Testing]

No automated test framework exists; testing will be manual via the dashboard and API.

1. Run scanner → generate watchlist with at least one "BUY NOW" signal
2. Start API server → confirm scheduler initializes
3. Check `trades_history.json` → confirm pending_entry positions created
4. Wait for scheduler to run → confirm entry prices fetched and positions become active
5. Manually verify portfolio dashboard displays correct numbers
6. Test manual refresh button `/api/trades/refresh-prices`

[Implementation Order]

Construction in topological dependency order, ensuring each step can be verified before the next begins.

1. **Create `trade_tracker.py`** with full `TradeTracker` class and all position/portfolio methods (this is the core module, no dependencies on other changes)
2. **Add trade-creation hook in `nse_scanner_api.py`** — modify `run_scan_task()` to call `TradeTracker.create_positions_from_results()` after scan completes
3. **Add API endpoints in `nse_scanner_api.py`** — `/api/trades/portfolio`, `/api/trades/positions`, `/api/trades/symbol-stats`, `/api/trades/refresh-prices`
4. **Add scheduler in `nse_scanner_api.py`** — APScheduler integration with `check_trades()` job, market hours detection, startup initialization in `lifespan()`
5. **Update `dashboard.html`** — Add portfolio tab with position tables, summary cards, and JavaScript functions for fetching/rendering trade data
6. **Integration test** — Run full pipeline: scan → trade creation → price check → dashboard display