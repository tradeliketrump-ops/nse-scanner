"""
1-Month Backtest (Jan 2026) ? Full 1H Analysis
=================================================
Simulates the scanner's strategy on Jan 2026 data:
- Daily screening ? 1H analysis for BUY-R/BUY-B signals
- 5% SL, 10% Target, ?1.5L per trade
- Entry at next-day open after signal

Run: python backtest.py
"""
import os, sys, json, csv
from datetime import datetime, date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nse_swing_scanner import (
    process_stock, analyze_1h, NSE_SYMBOLS, NIFTY50_SYMBOL,
    strip_ns, get_nse_symbols, download_data,
)
from trade_tracker import CAPITAL_PER_POSITION, STOP_LOSS_PCT, PROFIT_TARGET_PCT

import pandas as pd
import numpy as np
import yfinance as yf

# ??? Config ?????????????????????????????????????????????????????????
START_DATE = "2026-01-01"
END_DATE = "2026-01-31"
CAPITAL = 150000
SL_PCT = 0.05
TARGET_PCT = 0.10
MAX_HOLDING_DAYS = 60

results = []
open_trades = {}

def log(msg):
    print(msg)

def download_all_daily(symbols):
    """Download 8 months of daily data for all symbols (need 6mo for rolling)."""
    daily_start = "2025-07-01"
    log(f"Downloading daily data for {len(symbols)} symbols from {daily_start} to {END_DATE}...")
    
    # Nifty for RS
    nr = pd.Series(dtype=float)
    try:
        nd = yf.download(NIFTY50_SYMBOL, start=daily_start, end=END_DATE, progress=False, auto_adjust=True)
        if not nd.empty:
            if isinstance(nd.columns, pd.MultiIndex):
                t = nd.columns.get_level_values(1).unique()
                if len(t) > 0:
                    nd = nd.xs(t[0], axis=1, level=1).copy()
            nr = nd["Close"].pct_change().dropna()
    except:
        pass

    stock_data = {}
    batch_size = 30
    total = len(symbols)
    
    for i in range(0, total, batch_size):
        batch = symbols[i:i+batch_size]
        try:
            data = yf.download(batch, start=daily_start, end=END_DATE,
                              progress=False, auto_adjust=True, group_by="ticker")
            for sym in batch:
                try:
                    sd = None
                    if isinstance(data.columns, pd.MultiIndex):
                        for lv in [0, 1]:
                            if sym in data.columns.get_level_values(lv).unique():
                                sd = data.xs(sym, axis=1, level=lv).dropna().copy()
                                break
                    elif not data.empty:
                        sd = data.dropna().copy()
                    if sd is not None and len(sd) > 60:
                        stock_data[sym] = sd
                except:
                    pass
        except Exception as e:
            log(f"Batch error at {i}: {e}")
        
        pct = min(100, round((i + batch_size) / total * 100))
        log(f"  Daily: {min(i+batch_size, total)}/{total} ({pct}%) ? {len(stock_data)} ok")
    
    log(f"Daily download complete: {len(stock_data)}/{total}")
    return stock_data, nr


def run_backtest():
    symbols = list(NSE_SYMBOLS)
    log(f"\nBACKTEST: {len(symbols)} stocks, {START_DATE} to {END_DATE}")
    log("=" * 70)
    
    # Download daily data
    stock_data, nr = download_all_daily(symbols)
    if len(stock_data) == 0:
        log("ERROR: No daily data!")
        return
    
    # Get all trading dates in January 2026
    jan_dates = set()
    for df in stock_data.values():
        for d in df.index:
            if str(d)[:7] == "2026-01":
                jan_dates.add(d)
    jan_dates = sorted(jan_dates)
    log(f"January 2026 trading days: {len(jan_dates)}")
    
    total_signals = 0
    total_closed = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    
    # Process each day
    for day_idx, current_date in enumerate(jan_dates):
        dt = current_date.to_pydatetime() if hasattr(current_date, 'to_pydatetime') else current_date
        date_str = current_date.strftime("%Y-%m-%d") if hasattr(current_date, 'strftime') else str(current_date)[:10]
        
        if dt.weekday() >= 5:
            continue
        
        log(f"\n{'='*60}")
        log(f"Day {day_idx+1}/{len(jan_dates)}: {date_str}")
        log(f"{'='*60}")
        
        # Step 1: Close any SL/Target hits for today
        to_close = []
        for base, trade in list(open_trades.items()):
            sym = base + ".NS"
            df = stock_data.get(sym)
            if df is None:
                continue
            if current_date not in df.index:
                continue
            
            current_price = float(df.loc[current_date, "Close"])
            entry_price = trade["entry_price"]
            sl = trade["stop_loss"]
            tgt = trade["target"]
            days_held = (dt - trade["entry_dt"]).days
            
            if current_price <= sl:
                pnl = round((current_price - entry_price) * trade["quantity"], 2)
                results.append({"symbol": base, "sector": trade["sector"],
                    "entry_date": trade["entry_date"], "exit_date": date_str,
                    "entry_price": entry_price, "exit_price": current_price,
                    "quantity": trade["quantity"], "pnl": pnl,
                    "pnl_percent": round(pnl / (entry_price * trade["quantity"]) * 100, 2),
                    "reason": "stop_loss", "days_held": days_held})
                total_pnl += pnl; total_closed += 1
                if pnl > 0: total_wins += 1
                else: total_losses += 1
                to_close.append(base)
                log(f"  ? SL: {base} @ ?{current_price} | P&L: ?{pnl}")
            elif current_price >= tgt:
                pnl = round((current_price - entry_price) * trade["quantity"], 2)
                results.append({"symbol": base, "sector": trade["sector"],
                    "entry_date": trade["entry_date"], "exit_date": date_str,
                    "entry_price": entry_price, "exit_price": current_price,
                    "quantity": trade["quantity"], "pnl": pnl,
                    "pnl_percent": round(pnl / (entry_price * trade["quantity"]) * 100, 2),
                    "reason": "target", "days_held": days_held})
                total_pnl += pnl; total_closed += 1
                if pnl > 0: total_wins += 1
                else: total_losses += 1
                to_close.append(base)
                log(f"  ? TGT: {base} @ ?{current_price} | P&L: ?{pnl}")
            elif days_held > MAX_HOLDING_DAYS:
                pnl = round((current_price - entry_price) * trade["quantity"], 2)
                results.append({"symbol": base, "sector": trade["sector"],
                    "entry_date": trade["entry_date"], "exit_date": date_str,
                    "entry_price": entry_price, "exit_price": current_price,
                    "quantity": trade["quantity"], "pnl": pnl,
                    "pnl_percent": round(pnl / (entry_price * trade["quantity"]) * 100, 2),
                    "reason": "time_exit", "days_held": days_held})
                total_pnl += pnl; total_closed += 1
                if pnl > 0: total_wins += 1
                else: total_losses += 1
                to_close.append(base)
                log(f"  ? TIME: {base} @ ?{current_price} | P&L: ?{pnl}")
        
        for base in to_close:
            if base in open_trades:
                del open_trades[base]
        
        # Step 2: Run daily screening for this date
        window_start_str = "2025-07-01"
        qualifying = []
        
        for sym, df in stock_data.items():
            base = strip_ns(sym)
            if base in open_trades:
                continue
            
            # Get window up to current date
            mask = df.index <= current_date
            window_df = df[mask]
            if len(window_df) < 60:
                continue
            
            try:
                r = process_stock(sym, window_df, nr, False, 40, 70, 5000, 500000, False)
                if r:
                    qualifying.append((base, sym, r))
            except:
                pass
        
        if not qualifying:
            log(f"  No daily qualifiers for {date_str}")
            continue
        
        log(f"  Daily qualifiers: {len(qualifying)} stocks")
        
        # Step 3: Run 1H analysis on qualifying stocks
        qualifying_symbols = [s for _, s, _ in qualifying]
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=10) as ex:
            fut = {ex.submit(analyze_1h, s): s for s in qualifying_symbols}
            
            for f in as_completed(fut):
                sym, signal, detail, zone = f.result()
                base = strip_ns(sym)
                r_dict = None
                for b, s, r in qualifying:
                    if b == base:
                        r_dict = r
                        break
                
                if signal in ("BUY-R", "BUY-B") and r_dict:
                    # Find next trading day's data
                    df = stock_data.get(sym)
                    if df is None:
                        continue
                    future_dates = df[df.index > current_date].index
                    if len(future_dates) == 0:
                        continue
                    next_date = future_dates[0]
                    next_dt = next_date.to_pydatetime() if hasattr(next_date, 'to_pydatetime') else next_date
                    
                    entry_price = None
                    try:
                        entry_price = float(df.loc[next_date, "Open"])
                    except:
                        continue
                    
                    if entry_price is None or entry_price <= 0:
                        continue
                    
                    quantity = max(1, int(CAPITAL / entry_price))
                    stop_loss = round(entry_price * (1 - SL_PCT), 2)
                    target = round(entry_price * (1 + TARGET_PCT), 2)
                    
                    open_trades[base] = {
                        "symbol": base, "sector": r_dict.get("Sector", "Unknown"),
                        "entry_date": next_date.strftime("%Y-%m-%d"),
                        "entry_dt": next_dt,
                        "entry_price": entry_price,
                        "stop_loss": stop_loss,
                        "target": target,
                        "quantity": quantity,
                        "signal": signal,
                    }
                    total_signals += 1
                    log(f"  ? {signal}: {base} @ ?{entry_price} | SL: {stop_loss} | TGT: {target}")
    
    # Close remaining open trades at end of period
    for base, trade in list(open_trades.items()):
        sym = base + ".NS"
        df = stock_data.get(sym)
        if df is not None:
            last_price = float(df["Close"].iloc[-1])
            entry_price = trade["entry_price"]
            pnl = round((last_price - entry_price) * trade["quantity"], 2)
            results.append({"symbol": base, "sector": trade["sector"],
                "entry_date": trade["entry_date"], "exit_date": END_DATE,
                "entry_price": entry_price, "exit_price": last_price,
                "quantity": trade["quantity"], "pnl": pnl,
                "pnl_percent": round(pnl / (entry_price * trade["quantity"]) * 100, 2),
                "reason": "end_of_period",
                "days_held": (datetime.strptime(END_DATE, "%Y-%m-%d") - trade["entry_dt"]).days})
            total_pnl += pnl; total_closed += 1
            if pnl > 0: total_wins += 1
            else: total_losses += 1
    
    # ??? Results ????????????????????????????????????????????????????
    generate_output(results, total_signals, total_closed, total_wins, total_losses, total_pnl)


def generate_output(trades, total_signals, total_closed, total_wins, total_losses, total_pnl):
    csv_file = "backtest_results.csv"
    if trades:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        log(f"Saved {len(trades)} trades to {csv_file}")
    
    closed_trades = [t for t in trades if t["reason"] != "end_of_period"]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    win_rate = round(len(wins) / max(1, len(wins) + len(losses)) * 100, 1)
    avg_win = round(sum(t["pnl"] for t in wins) / max(1, len(wins)), 2) if wins else 0
    avg_loss = round(sum(t["pnl"] for t in losses) / max(1, len(losses)), 2) if losses else 0
    
    sym_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0})
    for t in trades:
        s = t["symbol"]
        sym_stats[s]["trades"] += 1
        sym_stats[s]["total_pnl"] += t["pnl"]
        if t["pnl"] > 0: sym_stats[s]["wins"] += 1
        elif t["pnl"] < 0: sym_stats[s]["losses"] += 1
    
    sorted_syms = sorted(sym_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
    top5 = sorted_syms[:5]
    bottom5 = sorted_syms[-5:] if len(sorted_syms) >= 5 else sorted_syms
    
    lines = []
    lines.append("=" * 70)
    lines.append("NSE SWING SCANNER ? 1-MONTH BACKTEST (FULL 1H ANALYSIS)")
    lines.append(f"Period: {START_DATE} to {END_DATE}")
    lines.append("=" * 70)
    lines.append(f"Total Stocks: {len(NSE_SYMBOLS)}")
    lines.append(f"Trading Days: ~22")
    lines.append(f"")
    lines.append(f"{'METRIC':<30} {'VALUE':<15}")
    lines.append("-" * 45)
    lines.append(f"{'Total Signals':<30} {total_signals:<15}")
    lines.append(f"{'Closed Trades':<30} {len(closed_trades):<15}")
    lines.append(f"{'Wins':<30} {len(wins):<15}")
    lines.append(f"{'Losses':<30} {len(losses):<15}")
    lines.append(f"{'Win Rate':<30} {win_rate:<15}%")
    lines.append(f"{'Net P&L (?)':<30} {total_pnl:<15,.2f}")
    lines.append(f"{'Avg Win (?)':<30} {avg_win:<15,.2f}")
    lines.append(f"{'Avg Loss (?)':<30} {avg_loss:<15,.2f}")
    lines.append(f"{'Avg Holding Days':<30} {round(sum(t['days_held'] for t in trades)/max(1,len(trades)), 1):<15}")
    lines.append(f"")
    lines.append("TOP 5 SYMBOLS BY P&L:")
    for sym, st in top5:
        lines.append(f"  {sym:<15} {st['trades']} trades, {st['wins']}W/{st['losses']}L, ?{st['total_pnl']:,.2f}")
    lines.append("")
    lines.append("BOTTOM 5 SYMBOLS BY P&L:")
    for sym, st in bottom5:
        lines.append(f"  {sym:<15} {st['trades']} trades, {st['wins']}W/{st['losses']}L, ?{st['total_pnl']:,.2f}")
    lines.append("=" * 70)
    
    summary = "\n".join(lines)
    with open("backtest_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)
    print(summary)


if __name__ == "__main__":
    print("=" * 70)
    print("  1-MONTH BACKTEST ? FULL 1H ANALYSIS")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  {len(NSE_SYMBOLS)} stocks, 5% SL, 10% Target, ?{CAPITAL}/trade")
    print("=" * 70)
    run_backtest()