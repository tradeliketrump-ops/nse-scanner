# Implementation Plan — Trade Persistence, Signal Generation & Dashboard Enhancements

## Overview

Fix critical issues where trade positions disappear from the Performance Report on Render deployments, sell signals are never generated, Nifty 50 fails to produce BUY-R/BUY-B signals in the 1H analysis, and add date-range filtering for monthly performance review.

## Context

The NSE Swing Scanner runs on Render with a persistent disk mount (`/data`) for SQLite storage. However, Render disk is tied to the service — redeploying (which auto-deploys on every Git push) wipes the disk, losing all trade history. Beyond that, the scanner has several bugs: (1) `run_scanner()` builds incorrect symbol names for 1H analysis on Nifty 50 (uses "NIFTY50.NS" instead of "^NSEI"), (2) `process_stock()` only passes bullish-filtered stocks into 1H analysis, so sell signals requiring bearish daily context are never produced, (3) Nifty 50 P&L calculations don't apply the ×65 lot multiplier in `check_open_positions()` or dashboard rendering, (4) there's no date-range filtering to evaluate monthly performance. These changes span all five files: `nse_swing_scanner.py`, `trade_tracker.py`, `nse_scanner_api.py`, `templates/dashboard.html`.

## Types

No new data types or classes — all changes are logic modifications to existing functions and API parameters.

| Existing Value | Change |
|----------------|--------|
| `NIFTY50_SYMBOL = "^NSEI"` | Unchanged (already correct) |
| `NIFTY_SPOT = "^NSEI"` | Unchanged (already correct) |
| `CAPITAL_PER_POSITION = 150000` | Unchanged |
| `STOP_LOSS_PCT = 0.05` | Unchanged |
| `PROFIT_TARGET_PCT = 0.10` | Unchanged |

No new enums, interfaces, or type definitions required.

## Files

### Files Modified

1. **`nse_swing_scanner.py`** — Two critical changes:
   - Add a **second bearish scan pass** in `process_stock()` that returns results with the same symbol/price/sector info but skip bullish-only filters (no EMA20/SMA50/Volume/market cap filters) — essentially register all bearish stocks for 1H analysis so sell signals can fire
   - Fix Nifty 50 1H symbol in `run_scanner()`: when building `syms_1h`, map `"NIFTY50"` → `"^NSEI"` before passing to `analyze_1h()`

2. **`trade_tracker.py`** — Three changes:
   - In `check_open_positions()`: when Nifty 50 position is closed (SL or target), multiply P&L by 65 lot multiplier
   - In `get_portfolio_summary()` / `get_symbol_stats()`: add Nifty 65x multiplier handling for P&L display consistency
   - Add a `diagnose_health()` method to report DB path, row count, disk usage

3. **`nse_scanner_api.py`** — Two new endpoints:
   - `GET /api/trades/diagnostics` — returns DB health info (file path, size, position counts by status)
   - `GET /api/trades/positions?status=active&from=2026-06-01&to=2026-06-26` — adds optional `from` and `to` query parameters for date-range filtering on `signal_date`

4. **`templates/dashboard.html`** — Three changes:
   - Add **date range picker** (two `<input type="date">` fields + filter button) in the Performance Report tab
   - Fix Nifty P&L display to apply ×65 lot multiplier when symbol is NIFTY50
   - Show DB health stats at the bottom of Performance Report tab
   - Improve "0 positions" empty state to show meaningful message

No new files, no deleted files, no config changes.

## Functions

### Modified Functions

1. **`nse_swing_scanner.py:run_scanner()`** (line ~753)
   - After building `syms_1h`, map `"NIFTY50"` → `"^NSEI"` for the yfinance call
   - After the bullish scan pass, add a bearish scan pass for stocks that **failed** the bullish filter but have valid daily data, to catch sell signals

2. **`nse_swing_scanner.py:process_stock()`** (~line 630)
   - Add a `bearish_mode=False` parameter
   - When `bearish_mode=True`, skip the bullish-qualification filters (C1/C2/C3, volume, mcap, RSI). Instead check for bearish context (HA < E20, DI- > DI+, basic ADX check). Return a simplified result that includes symbol, sector, price but with Stage="Bearish", Trend="Bearish"

3. **`trade_tracker.py:check_open_positions()`** (~line 377-400)
   - After P&L calculation, check if symbol is "NIFTY50" or "^NSEI"; if so multiply P&L by 65

4. **`trade_tracker.py:get_portfolio_summary()`** (~line 440)
   - Ensure Nifty 50 closed position P&L includes 65x multiplier in summary

5. **`trade_tracker.py:get_symbol_stats()`** (~line 503)
   - Ensure Nifty 50 P&L per-symbol stats include 65x multiplier

6. **`trade_tracker.py`** — New method `diagnose_health()`
   - Returns `{"db_path": str, "db_size_mb": float, "total_rows": int, "active_count": int, "pending_count": int, "closed_count": int}`

7. **`nse_scanner_api.py:trades_positions()`** (~line 449)
   - Add optional `from_date` and `to_date` query parameters
   - Pass to `TradeTracker.get_positions()` filter

8. **`trade_tracker.py:get_positions()`** (~line 500)
   - Accept optional `from_date` and `to_date` kwargs
   - Filter by `signal_date >= from_date AND signal_date <= to_date`

### New Functions

1. **`trade_tracker.py:diagnose_health()`** — static or instance method returning DB diagnostics dict
2. **`nse_scanner_api.py:trades_diagnostics()`** — new FastAPI endpoint handler

## Classes

No new classes. No removed classes. Only modifications to `TradeTracker`:

- Add method `diagnose_health(self) -> dict`
- Modify `get_positions(self, status_filter, from_date, to_date) -> list[dict]`

## Dependencies

No new dependencies. Everything uses existing imports: `os`, `sqlite3`, `yfinance`, `pandas`, `numpy`, `FastAPI`.

## Testing

- Run `python nse_scanner_api.py` locally and verify:
  - `GET /api/trades/diagnostics` returns valid JSON with DB info
  - `GET /api/trades/positions?from=2026-06-01&to=2026-06-26` filters correctly
  - Performance Report loads with date picker visible
- Verify Nifty 50 gets mapped correctly for 1H analysis by checking scan logs
- Verify sell signals appear when bearish stocks are scanned

## Implementation Order

1. Fix Nifty 50 1H symbol mapping in `nse_swing_scanner.py` (line ~755, one-line change)
2. Add bearish scan pass in `nse_swing_scanner.py` (modify `process_stock()` + `run_scanner()`)
3. Add Nifty 65x lot multiplier in `trade_tracker.py` (modify `check_open_positions()`)
4. Add `diagnose_health()` method to `TradeTracker` in `trade_tracker.py`
5. Add date-range filtering to `get_positions()` in `trade_tracker.py`
6. Add `/api/trades/diagnostics` endpoint and update `/api/trades/positions` with date filtering in `nse_scanner_api.py`
7. Update `templates/dashboard.html` with date picker, Nifty P&L fix, DB health display