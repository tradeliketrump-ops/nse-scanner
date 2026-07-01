# Implementation Plan — Migrate from SQLite to Supabase PostgreSQL

## Overview

Replace SQLite storage with Supabase PostgreSQL to solve the permanent data persistence problem on Render's free tier (ephemeral filesystem wiped on spin-down/deploy).

## Context

Render free tier spins down after 15 minutes of inactivity. On next request, it starts a new container with a fresh filesystem — wiping the SQLite database file. Supabase PostgreSQL stores data externally, surviving any deploy, spin-down, or container restart. The entire `TradeTracker` class needs to be rewritten from `sqlite3` calls to `psycopg2` (PostgreSQL driver), keeping the exact same method signatures so no other code changes are needed.

## Types

No new types. All existing method signatures (`create_positions_from_results`, `process_pending_entries`, `check_open_positions`, `get_positions`, `get_portfolio_summary`, `get_symbol_stats`, `diagnose_health`, etc.) remain identical.

## Files

### Files Modified

1. **`requirements.txt`** — Add `psycopg2-binary`
2. **`trade_tracker.py`** — Complete rewrite of storage layer from SQLite to PostgreSQL
3. **`nse_scanner_api.py`** — Remove backup/restore/activate-pending endpoints, simplify diagnostics
4. **`templates/dashboard.html`** — Remove Backup DB button
5. **`render.yaml`** — Add `SUPABASE_DB_URL` env var

### Files Unchanged

- `nse_swing_scanner.py` — No changes needed

## Functions

### Modified Functions in `trade_tracker.py`

All methods maintain same signatures. Internal SQLite replaced with PostgreSQL:

- `__init__` — Connect to Supabase using `DATABASE_URL` env var or fallback to SQLite locally
- `_connect()` — Return a `psycopg2` connection instead of `sqlite3`
- `_init_db()` — Run CREATE TABLE IF NOT EXISTS for PostgreSQL syntax
- `_row_to_dict()` — Same, adapt for psycopg2 cursor description
- `_get_positions()` — Replace `conn.execute()` with `cur.execute()`, use `cur.fetchall()`
- `_upsert_position()` — Replace `INSERT ... ON CONFLICT(id) DO UPDATE` with PostgreSQL `INSERT ... ON CONFLICT(id) DO UPDATE`
- `create_positions_from_results()` — Same logic, same signature
- `process_pending_entries()` — Same logic
- `check_open_positions()` — Same logic
- `get_portfolio_summary()` — Same logic
- `get_positions()` — Same logic
- `get_symbol_stats()` — Same logic
- `diagnose_health()` — Simplified (no file size, return DB_URL prefix)
- `_is_market_hours()` — Same (static, no DB change)

### Removed Functions in `nse_scanner_api.py`

- `trades_backup()` — removed (no longer needed)
- `trades_restore()` — removed
- `trades_activate_pending()` — keep for manual activation
- `rebuild_positions_from_csv()` — removed (not needed with persistent DB)

### Modified Functions in `nse_scanner_api.py`

- `trades_diagnostics()` — No longer reads DB file size, just returns row counts

## Classes

No new classes. `TradeTracker` keeps all same methods.

## Dependencies

- Add `psycopg2-binary` to `requirements.txt`
- No other new dependencies

## Environment Variables

- `DATABASE_URL` — Supabase PostgreSQL connection string (set on Render as environment variable)
- Fallback: if `DATABASE_URL` not set, use SQLite (for local development)

## Testing

- Verify connection to Supabase from local machine using the connection string
- Run a scan → positions should persist in Supabase
- Verify diagnostics endpoint returns row counts
- Verify dashboard Performance Report shows positions

## Implementation Order

1. Add `psycopg2-binary` to `requirements.txt`
2. Rewrite `trade_tracker.py` — PostgreSQL implementation with SQLite fallback locally
3. Update `nse_scanner_api.py` — remove backup/restore, clean up diagnostics
4. Update `templates/dashboard.html` — remove Backup button
5. Update `render.yaml` — add SUPABASE_DB_URL env var