# Implementation Plan — Remove 1-Hour Analysis, Generate Signals from Daily Data

## Overview

Replace the 1-hour timeframe TV-style signal generation with daily timeframe signal generation inside `process_stock()`, eliminating the need for separate 1H data downloads and the `analyze_1h()` function.

## Context

Currently, the scanner does two passes: (1) daily screening via `process_stock()` which computes HA/E20/S50/RSI and qualifies stocks based on breakout conditions, then (2) a parallel 1-hour analysis via `analyze_1h()` which downloads 10 days of 1-hour data per stock and computes ADX/DMI + pivot/ATR levels to produce BUY-R/BUY-B/SELL-R/SELL-B signals. This is slow (~30-40s for 500 stocks) and adds complexity. Since the user wants signals based on daily data only, all signal logic can be moved into `process_stock()` using the same daily OHLC data already downloaded.

## Types

No new data types.

All changes are logical: existing signal constants (`BUY-R`, `BUY-B`, `SELL-R`, `SELL-B`, `NEUTRAL`) and helper functions (`adx_dmi`, `compute_daily_levels`, `heiken_ashi`, `ema`, `rsi`) remain unchanged.

## Files

### Files Modified

1. **`nse_swing_scanner.py`** — Major refactor:
   - Remove `HOURS_LOOKBACK` constant (no longer needed for 1H data)
   - Remove `analyze_1h()` function entirely (~115 lines)
   - Modify `process_stock()` to compute daily ADX/DMI + daily pivot/ATR levels and produce signals
   - Modify `run_scanner()` to remove Step 3 (parallel 1H analysis) and the bearish pass
   - Update CLI help text

2. **`nse_scanner_api.py`** — Minor cleanup:
   - Remove `run_intraday_scan()` function from scheduler
   - Remove the intraday CronTrigger jobs from `start_scheduler()`
   - Change `analyze_1h_mode=True` to `analyze_1h_mode=False` in `run_scan_task()`
   - Update docstring

3. **`templates/dashboard.html`** — Optional:
   - Column header "1H Setup" / "1H Detail" can stay as-is (UI unchanged)

## Functions

### Modified Functions

1. **`nse_swing_scanner.py:process_stock(sym, df, nr, use_rsi, rsi_min, rsi_max, mm, mv, early, bearish_mode=False)`**
   - Remove `bearish_mode` parameter
   - After computing HA/E20/S50/RSI and breakout detection, compute daily ADX/DMI using `adx_dmi(df["High"], df["Low"], df["Close"])`
   - Compute daily structural levels using `compute_daily_levels(sym)` (note: this function downloads its own data — can be optimized but not necessary)
   - Apply the same TV-style signal logic from `analyze_1h()` but using daily HA values instead of 1H HA values:
     - `bull_trend`: HA_C > E20 && DI+ > DI- && ADX > 20 && RSI < 80
     - `bear_trend`: HA_C < E20 && DI- > DI+ && ADX > 20 && RSI > 20
     - Level checks: `ha_close <= buy_rev` for BUY-R, `ha_close > brkout and ha_prev <= brkout` for BUY-B, `ha_close >= sell_rev` for SELL-R, `ha_close < brkdown and ha_prev >= brkdown` for SELL-B
   - Set `1H_Setup`, `1H_Detail`, `1H_Zone` fields directly
   - Nifty 50: same logic but skip volume/mcap/RSI filters
   - Return result dict with all fields populated

2. **`nse_swing_scanner.py:run_scanner()`**
   - Remove Step 2a/2b split — one single screening pass
   - Remove Step 3 (1H analysis) entirely
   - Update step count to 3 steps: Download → Screen → Rank & Export

### Removed Functions

1. **`nse_swing_scanner.py:analyze_1h(symbol)`** — Entire function removed
2. **`nse_swing_scanner.py`** — `HOURS_LOOKBACK` constant removed
3. **`nse_scanner_api.py:run_intraday_scan()`** — Entire function removed

### New Functions

None.

## Classes

No class modifications.

## Dependencies

No changes. `adx_dmi()` and `compute_daily_levels()` are already imported at the top of `nse_swing_scanner.py`.

## Testing

- Verify `process_stock()` runs without errors on typical stock data
- Verify CSV output includes `1H_Setup` column with values BUY-R, BUY-B, SELL-R, SELL-B, NEUTRAL
- Verify Nifty 50 appears with signals
- Verify no "1-hour" or "1H data" mentions in scan output
- Verify scan completes in ~10-15s (was ~30-40s with 1H analysis)

## Implementation Order

1. Remove `HOURS_LOOKBACK` constant and `analyze_1h()` function from `nse_swing_scanner.py`
2. Rewrite `process_stock()` — add ADX/DMI + signal logic inside, remove bearish_mode
3. Rewrite `run_scanner()` — single pass, no 1H step, no bearish pass
4. Update CLI help text in main()
5. Clean up `nse_scanner_api.py` — remove intraday scan, set analyze_1h_mode=False
6. Remove `run_intraday_scan()` from scheduler