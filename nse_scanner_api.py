"""
NSE Swing Scanner — FastAPI Web Service
=========================================
Provides a REST API and web dashboard for the NSE swing trade scanner.
Deployable to Render (free tier).

Endpoints:
  GET  /                        Web dashboard (SPA)
  GET  /api/health              Health check
  POST /api/scan/start          Start background scan
  GET  /api/scan/status/{task_id}  Check scan progress
  GET  /api/scan/result/{task_id}  Get scan results as JSON
  GET  /api/watchlist/latest    Download latest Excel file
  GET  /manifest.json           PWA manifest
  GET  /sw.js                   Service worker
  GET  /api/trades/portfolio    Portfolio summary
  GET  /api/trades/positions    Trade positions list
  GET  /api/trades/symbol-stats Per-symbol performance
  POST /api/trades/refresh      Refresh prices manually
"""

import os, sys, json, uuid, time, threading, csv, io, glob, logging
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
import numpy as np

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi import Query
import pandas as pd

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nse_swing_scanner import run_scanner, NSE_SYMBOLS
from trade_tracker import TradeTracker, get_tracker

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
DASHBOARD_PATH = OUTPUT_DIR / "templates" / "dashboard.html"
STATIC_DIR = OUTPUT_DIR / "static"
MANIFEST_PATH = STATIC_DIR / "manifest.json"
SW_PATH = STATIC_DIR / "sw.js"

# In-memory task store
tasks = {}

# Scheduler reference (started in lifespan)
_scheduler = None

# ─── CSV Fallback Helpers ───────────────────────────────────────────
def find_latest_csv():
    """Find the most recent CSV file matching any known naming pattern."""
    patterns = [
        "watchlist_swing_*.csv",
        "watchlist_early_*.csv",
        "swing_watchlist_*.csv",
        "early_watchlist_*.csv",
    ]
    best = None
    best_mtime = 0
    for pattern in patterns:
        for f in glob.glob(str(OUTPUT_DIR / pattern)):
            try:
                mtime = os.path.getmtime(f)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best = f
            except:
                pass
    return best


OLD_TO_NEW_COLUMNS = {
    "Dist_EMA20": "D_E20",
    "Dist_SMA50": "D_S50",
    "RS_Score": "RS",
    "Low_Wick": "L_Wick",
    "Vol_Spike": "V_Spike",
    "Vol_Ratio": "V_Ratio",
}


def normalize_csv_data(df):
    """Normalize old-format CSV columns to the new format the dashboard expects."""
    df = df.copy()
    # Rename old columns to new
    for old_col, new_col in OLD_TO_NEW_COLUMNS.items():
        if old_col in df.columns and new_col not in df.columns:
            df.rename(columns={old_col: new_col}, inplace=True)

    # Add missing columns with defaults
    if "Stage" not in df.columns and "Trend" in df.columns:
        df["Stage"] = df["Trend"].apply(
            lambda x: "Fresh Breakout" if x == "Bullish" else ("Near Miss" if "Near" in str(x) else "Inactive")
        )
    elif "Stage" not in df.columns:
        df["Stage"] = "Bullish"

    if "Trend" not in df.columns:
        df["Trend"] = df["Stage"].apply(
            lambda x: "Bullish" if x in ("Fresh Breakout", "Strong Momentum", "Already Rallied") 
            else ("Near Miss" if "Near" in str(x) else "Building")
        )

    if "1H_Setup" not in df.columns:
        df["1H_Setup"] = "WATCH"
    if "1H_Detail" not in df.columns:
        df["1H_Detail"] = "Based on daily scan (no 1H analysis)"
    if "1H_Zone" not in df.columns:
        df["1H_Zone"] = "-"
    if "HH_HL" not in df.columns:
        df["HH_HL"] = False
    if "L_Wick" not in df.columns:
        df["L_Wick"] = False
    if "R:R" not in df.columns:
        df["R:R"] = "1:2.50"
    if "Entry" not in df.columns:
        df["Entry"] = "-"
    if "Stop" not in df.columns:
        df["Stop"] = "-"
    if "D_E20" not in df.columns and "Price" in df.columns and "EMA20" in df.columns:
        df["D_E20"] = ((df["Price"] - df["EMA20"]) / df["EMA20"] * 100).round(2)
    if "D_S50" not in df.columns and "Price" in df.columns and "SMA50" in df.columns:
        df["D_S50"] = ((df["Price"] - df["SMA50"]) / df["SMA50"] * 100).round(2)
    if "RS" not in df.columns and "RS_Score" in df.columns:
        df["RS"] = df["RS_Score"]
    if "V_Spike" not in df.columns:
        df["V_Spike"] = "No"
    if "V_Ratio" not in df.columns:
        df["V_Ratio"] = 1.0

    # Ensure Rank column
    if "Rank" not in df.columns:
        df["Rank"] = 50.0

    return df

# ─── Background Scan Runner ─────────────────────────────────────────
def run_scan_task(task_id: str, early_mode: bool):
    """Run scan in a background thread and store results."""
    try:
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = "Starting scan..."
        tasks[task_id]["started_at"] = datetime.now().isoformat()

        # Redirect stdout to capture progress
        old_stdout = sys.stdout
        log_lines = []

        class LogCapture:
            def write(self, text):
                log_lines.append(text)
                if text.strip():
                    tasks[task_id]["progress"] = text.strip()[:200]
            def flush(self): pass

        sys.stdout = LogCapture()

        # Run the scanner
        result_df = run_scanner(
            symbols=NSE_SYMBOLS,
            output_dir=str(OUTPUT_DIR),
            use_rsi=False,
            min_mcap=5000,
            min_vol=500000,
            early_mode=early_mode,
            analyze_1h_mode=True,
        )

        sys.stdout = old_stdout

        # Convert results to JSON
        if result_df is not None and not result_df.empty:
            # Clean column names for JSON
            result_json = json.loads(result_df.to_json(orient="records", date_format="iso"))
            # Convert numpy values
            for row in result_json:
                for k, v in row.items():
                    if isinstance(v, (np.integer,)): row[k] = int(v)
                    elif isinstance(v, (np.floating,)): row[k] = round(float(v), 2)
                    elif pd.isna(v): row[k] = None
        else:
            result_json = []

        # Find generated files
        date_str = datetime.now().strftime("%Y-%m-%d")
        tag = "early" if early_mode else "swing"
        csv_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.csv"
        xlsx_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.xlsx"

        # Create trade positions from BUY NOW signals
        if result_json:
            try:
                tracker = TradeTracker()
                created = tracker.create_positions_from_results(result_json)
                if created:
                    logger.info(f"Created {len(created)} trade positions from BUY NOW signals: {created}")
                    tasks[task_id]["progress"] = f"Scan complete. {len(result_json)} stocks found. {len(created)} trades created."
            except Exception as trade_e:
                logger.error(f"Error creating trade positions: {trade_e}")

        tasks[task_id].update({
            "status": "completed",
            "progress": f"Scan complete. {len(result_json)} stocks found.",
            "completed_at": datetime.now().isoformat(),
            "results": result_json,
            "count": len(result_json),
            "csv_file": str(csv_path) if csv_path.exists() else None,
            "xlsx_file": str(xlsx_path) if xlsx_path.exists() else None,
            "mode": "early" if early_mode else "standard",
        })

    except Exception as e:
        tasks[task_id].update({
            "status": "error",
            "progress": f"Error: {str(e)[:200]}",
            "error": str(e),
        })
        sys.stdout = old_stdout

# ─── Scheduler ──────────────────────────────────────────────────────
def check_trades():
    """Background job: process pending entries and check open positions."""
    try:
        tracker = get_tracker()
        
        # Process pending entries (set entry price at market open)
        activated = tracker.process_pending_entries()
        if activated:
            logger.info(f"Activated {len(activated)} pending entries: {[a['symbol'] for a in activated]}")
        
        # Check open positions for SL/target hits
        closed = tracker.check_open_positions()
        if closed:
            for c in closed:
                logger.info(f"Position closed: {c['symbol']} - {c['reason']} - P&L: ₹{c['pnl']}")
    except Exception as e:
        logger.error(f"Trade check error: {e}")


def start_scheduler():
    """Initialize and start the APScheduler for trade monitoring."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        
        _scheduler = BackgroundScheduler()
        
        # Run trade checks every 15 minutes during market hours
        _scheduler.add_job(
            check_trades,
            IntervalTrigger(minutes=15),
            id="trade_check",
            name="Check pending entries and open positions",
            replace_existing=True,
        )
        
        _scheduler.start()
        logger.info("Trade monitoring scheduler started (every 15 min)")
    except ImportError:
        logger.warning("APScheduler not installed. Trade monitoring disabled.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def stop_scheduler():
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
        except:
            pass
        _scheduler = None

# ─── FastAPI App ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    STATIC_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "templates").mkdir(exist_ok=True)
    # Start background scheduler
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()

app = FastAPI(
    title="NSE Swing Trade Scanner",
    description="Daily scan for NSE swing trading opportunities with 1-hour entry analysis",
    version="1.1.0",
    lifespan=lifespan,
)

# ─── API Endpoints ──────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "active_tasks": len([t for t in tasks.values() if t["status"] == "running"]),
    }


@app.post("/api/scan/start")
def start_scan(early: bool = False):
    """Start a background scan task. Returns task_id to poll for status."""
    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = {
        "status": "queued",
        "progress": "Queued...",
        "early_mode": early,
        "started_at": None,
        "completed_at": None,
        "results": [],
        "count": 0,
        "csv_file": None,
        "xlsx_file": None,
        "error": None,
    }

    # Start scan in background thread
    thread = threading.Thread(target=run_scan_task, args=(task_id, early), daemon=True)
    thread.start()

    return {
        "task_id": task_id,
        "status": "queued",
        "message": "Scan started. Poll /api/scan/status/{task_id} for progress.",
    }


@app.get("/api/scan/status/{task_id}")
def scan_status(task_id: str):
    """Get current status of a scan task."""
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    t = tasks[task_id]
    return {
        "task_id": task_id,
        "status": t["status"],
        "progress": t["progress"],
        "started_at": t["started_at"],
        "completed_at": t["completed_at"],
        "count": t["count"],
        "early_mode": t.get("early_mode", False),
        "has_results": len(t.get("results", [])) > 0,
    }


@app.get("/api/scan/result/{task_id}")
def scan_result(task_id: str):
    """Get scan results as JSON."""
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    t = tasks[task_id]
    if t["status"] != "completed":
        raise HTTPException(400, f"Scan not completed yet. Status: {t['status']}")
    return {
        "task_id": task_id,
        "status": t["status"],
        "count": t["count"],
        "mode": t.get("mode"),
        "completed_at": t["completed_at"],
        "results": t["results"],
        "csv_file": t["csv_file"],
        "xlsx_file": t["xlsx_file"],
    }


@app.get("/api/watchlist/latest")
def download_latest(early: bool = False):
    """Download the latest generated Excel watchlist."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    tag = "early" if early else "swing"
    xlsx_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.xlsx"
    csv_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.csv"

    # Try Excel first, fallback to CSV
    if xlsx_path.exists():
        return FileResponse(
            str(xlsx_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=f"NSE_Watchlist_{date_str}.xlsx",
        )
    elif csv_path.exists():
        return FileResponse(
            str(csv_path),
            media_type="text/csv",
            filename=f"NSE_Watchlist_{date_str}.csv",
        )
    else:
        raise HTTPException(404, "No watchlist file found. Run a scan first.")


@app.get("/api/watchlist/summary")
def watchlist_summary():
    """Get a quick summary of the latest watchlist data."""
    csv_path = find_latest_csv()
    if not csv_path:
        return {"total": 0, "message": "No watchlist found"}

    try:
        df = pd.read_csv(csv_path)
        df = normalize_csv_data(df)
        date_str = Path(csv_path).stem.split("_")[-1] if Path(csv_path).stem.count("_") >= 2 else datetime.now().strftime("%Y-%m-%d")
        summary = {
            "total": len(df),
            "date": date_str,
            "fresh_breakouts": int((df.get("Stage") == "Fresh Breakout").sum()) if "Stage" in df else 0,
            "strong_momentum": int((df.get("Stage") == "Strong Momentum").sum()) if "Stage" in df else 0,
            "buy_now": int((df.get("1H_Setup") == "BUY NOW").sum()) if "1H_Setup" in df else 0,
            "watch": int((df.get("1H_Setup") == "WATCH").sum()) if "1H_Setup" in df else 0,
            "wait": int((df.get("1H_Setup") == "WAIT").sum()) if "1H_Setup" in df else 0,
            "sectors": df["Sector"].value_counts().head(5).to_dict() if "Sector" in df else {},
        }
        return summary
    except Exception as e:
        return {"total": 0, "error": str(e)}


@app.get("/api/watchlist/latest-data")
def watchlist_latest_data(sync_trades: bool = Query(True, description="Auto-create trade positions from BUY NOW signals")):
    """Get the latest watchlist results as JSON (with column normalization)."""
    csv_path = find_latest_csv()
    if not csv_path:
        return {"count": 0, "results": [], "mode": "standard", "message": "No watchlist CSV found. Run a scan first."}

    try:
        df = pd.read_csv(csv_path)
        df = normalize_csv_data(df)

        # Sort by Rank descending
        if "Rank" in df.columns:
            df = df.sort_values("Rank", ascending=False).reset_index(drop=True)

        # Convert to JSON with proper types
        result_json = json.loads(df.to_json(orient="records", date_format="iso"))
        for row in result_json:
            for k, v in row.items():
                if isinstance(v, (np.integer,)): row[k] = int(v)
                elif isinstance(v, (np.floating,)): row[k] = round(float(v), 2)
                elif pd.isna(v): row[k] = None

        # Determine mode from filename
        filename = Path(csv_path).name
        mode = "early" if "early" in filename else "standard"

        # Auto-create trade positions from BUY NOW signals in CSV data
        if sync_trades and result_json:
            try:
                tracker = TradeTracker()
                created = tracker.create_positions_from_results(result_json)
                if created:
                    logger.info(f"Auto-created {len(created)} positions from CSV: {created}")
            except Exception as trade_e:
                logger.error(f"Error auto-creating positions from CSV: {trade_e}")

        return {
            "count": len(result_json),
            "results": result_json,
            "mode": mode,
            "csv_file": str(csv_path),
            "completed_at": datetime.fromtimestamp(os.path.getmtime(csv_path)).isoformat(),
        }
    except Exception as e:
        return {"count": 0, "results": [], "mode": "standard", "error": str(e)}


# ─── Trade/Portfolio API Endpoints ─────────────────────────────────

@app.get("/api/trades/portfolio")
def trades_portfolio():
    """Get portfolio summary with P&L, win rate, and counts."""
    try:
        tracker = get_tracker()
        summary = tracker.get_portfolio_summary()
        return summary
    except Exception as e:
        logger.error(f"Portfolio summary error: {e}")
        return {
            "total_invested": 0, "current_value": 0, "total_pnl": 0,
            "total_pnl_percent": 0, "win_rate": 0, "active_count": 0,
            "pending_count": 0, "closed_count": 0, "total_signals": 0,
            "wins": 0, "losses": 0, "error": str(e),
        }


@app.get("/api/trades/positions")
def trades_positions(status: str = Query("all", description="Filter: all, pending_entry, active, closed")):
    """Get list of trade positions, optionally filtered by status."""
    try:
        tracker = get_tracker()
        status_filter = status if status != "all" else None
        positions = tracker.get_positions(status_filter)
        return {"count": len(positions), "positions": positions}
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return {"count": 0, "positions": [], "error": str(e)}


@app.get("/api/trades/symbol-stats")
def trades_symbol_stats():
    """Get per-symbol trade performance breakdown."""
    try:
        tracker = get_tracker()
        stats = tracker.get_symbol_stats()
        return {"count": len(stats), "stats": stats}
    except Exception as e:
        logger.error(f"Symbol stats error: {e}")
        return {"count": 0, "stats": [], "error": str(e)}


@app.post("/api/trades/refresh")
def trades_refresh():
    """Manually trigger price refresh for all open/pending positions."""
    try:
        tracker = get_tracker()
        result = tracker.refresh_all_prices()
        # Also run entry processing and position checks
        activated = tracker.process_pending_entries()
        closed = tracker.check_open_positions()
        return {
            "updated": result["updated"],
            "failed": result["failed"],
            "activated": len(activated),
            "closed": len(closed),
            "details": {
                "activated_symbols": [a["symbol"] for a in activated],
                "closed_positions": closed,
            },
        }
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        return {"updated": 0, "failed": 0, "activated": 0, "closed": 0, "error": str(e)}


@app.get("/api/trades/history")
def trades_history():
    """Get the raw trades_history.json content."""
    try:
        tracker = get_tracker()
        return {
            "position_count": len(tracker.data.get("positions", {})),
            "created_at": tracker.data.get("created_at"),
            "updated_at": tracker.data.get("updated_at"),
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Serve Dashboard ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the main web dashboard."""
    if DASHBOARD_PATH.exists():
        return HTMLResponse(DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1><p>Run the app from the project directory.</p>")


@app.get("/manifest.json")
def manifest():
    """Serve PWA manifest."""
    if MANIFEST_PATH.exists():
        return JSONResponse(json.loads(MANIFEST_PATH.read_text()))
    return JSONResponse({})


@app.get("/sw.js")
def service_worker():
    """Serve service worker for PWA."""
    if SW_PATH.exists():
        return Response(SW_PATH.read_text(), media_type="application/javascript")
    return Response("", media_type="application/javascript")


# ─── Run (for local development) ────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  NSE Swing Scanner API v1.1")
    print(f"  Dashboard: http://localhost:8000")
    print(f"  API Docs:  http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run("nse_scanner_api:app", host="0.0.0.0", port=8000, reload=True)