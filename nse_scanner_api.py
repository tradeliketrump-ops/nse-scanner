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
from nse_swing_scanner import run_scanner, NSE_SYMBOLS, get_nse_symbols
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
    for old_col, new_col in OLD_TO_NEW_COLUMNS.items():
        if old_col in df.columns and new_col not in df.columns:
            df.rename(columns={old_col: new_col}, inplace=True)
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

        old_stdout = sys.stdout
        log_lines = []

        class LogCapture:
            def write(self, text):
                log_lines.append(text)
                if text.strip():
                    tasks[task_id]["progress"] = text.strip()[:200]
            def flush(self): pass

        sys.stdout = LogCapture()

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

        if result_df is not None and not result_df.empty:
            result_json = json.loads(result_df.to_json(orient="records", date_format="iso"))
            for row in result_json:
                for k, v in row.items():
                    if isinstance(v, (np.integer,)): row[k] = int(v)
                    elif isinstance(v, (np.floating,)): row[k] = round(float(v), 2)
                    elif pd.isna(v): row[k] = None
        else:
            result_json = []

        date_str = datetime.now().strftime("%Y-%m-%d")
        tag = "early" if early_mode else "swing"
        csv_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.csv"
        xlsx_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.xlsx"

        # Create trade positions from BUY signals
        # Same-day entry during market hours, pending_entry after hours
        # Convert to IST for market hours check
        now = datetime.now()
        hour_ist = (now.hour + 5) % 24
        minute_ist = now.minute + 30
        if minute_ist >= 60:
            hour_ist = (hour_ist + 1) % 24
            minute_ist -= 60
        is_market_hours = (now.weekday() < 5 and 
                           ((hour_ist == 9 and 15 <= minute_ist) or 
                            (10 <= hour_ist <= 14) or
                            (hour_ist == 15 and minute_ist <= 30)))
        if result_json:
            try:
                tracker = get_tracker()
                created = tracker.create_positions_from_results(result_json, same_day_entry=is_market_hours)
                if created:
                    logger.info(f"Created {len(created)} trade positions from BUY signals: {created}")
                    tasks[task_id]["progress"] = f"Scan complete. {len(result_json)} stocks found. {len(created)} trades created."
            except Exception as trade_e:
                logger.error(f"Error creating trade positions: {trade_e}")

        total_scanned = len(get_nse_symbols())
        tasks[task_id].update({
            "status": "completed",
            "progress": f"Scan complete. {len(result_json)} stocks found.",
            "completed_at": datetime.now().isoformat(),
            "results": result_json,
            "count": len(result_json),
            "total_scanned": total_scanned,
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
        activated = tracker.process_pending_entries()
        if activated:
            logger.info(f"Activated {len(activated)} pending entries: {[a['symbol'] for a in activated]}")
        closed = tracker.check_open_positions()
        if closed:
            for c in closed:
                logger.info(f"Position closed: {c['symbol']} - {c['reason']} - P&L: ₹{c['pnl']}")
    except Exception as e:
        logger.error(f"Trade check error: {e}")


def run_intraday_scan():
    """Intraday scan: re-run 1H analysis on existing qualifying stocks."""
    from nse_swing_scanner import analyze_1h, strip_ns
    from concurrent.futures import ThreadPoolExecutor, as_completed
    try:
        csv_path = find_latest_csv()
        if not csv_path:
            logger.info("Intraday scan: no CSV found, skipping")
            return
        df = pd.read_csv(csv_path)
        if df.empty:
            return
        symbols = [row["Symbol"] + ".NS" for _, row in df.iterrows()]
        logger.info(f"Intraday scan: re-analyzing {len(symbols)} stocks (1H only)...")
        results_map = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            fut = {ex.submit(analyze_1h, s): s for s in symbols}
            for f in as_completed(fut):
                sym, signal, detail, zone = f.result()
                base = strip_ns(sym)
                results_map[base] = {"1H_Setup": signal, "1H_Detail": detail, "1H_Zone": zone}
        buy_signals = []
        for _, row in df.iterrows():
            base = row["Symbol"]
            if base in results_map:
                sig = results_map[base]
                if sig["1H_Setup"] in ("BUY-R", "BUY-B"):
                    buy_signals.append({
                        "Symbol": base,
                        "Sector": row.get("Sector", "Unknown"),
                        "Price": row.get("Price", 0),
                        "1H_Setup": sig["1H_Setup"],
                        "1H_Detail": sig["1H_Detail"],
                        "Entry": row.get("Entry", "-"),
                        "Stop": row.get("Stop", "-"),
                        "R:R": row.get("R:R", "-"),
                    })
        if buy_signals:
            logger.info(f"Intraday scan: {len(buy_signals)} new BUY signals found")
            tracker = get_tracker()
            created = tracker.create_positions_from_results(buy_signals, same_day_entry=True)
            if created:
                logger.info(f"Intraday scan: created {len(created)} positions same-day: {created}")
        else:
            logger.info("Intraday scan: no new BUY signals")
    except Exception as e:
        logger.error(f"Intraday scan error: {e}")


def start_scheduler():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(check_trades, IntervalTrigger(minutes=15), id="trade_check", name="Check pending entries and open positions", replace_existing=True)
        _scheduler.add_job(run_intraday_scan, CronTrigger(hour=9, minute=45, timezone="Asia/Kolkata"), id="intraday_0945", name="Intraday 1H scan 9:45 AM", replace_existing=True)
        _scheduler.add_job(run_intraday_scan, CronTrigger(hour=11, minute=0, timezone="Asia/Kolkata"), id="intraday_1100", name="Intraday 1H scan 11:00 AM", replace_existing=True)
        _scheduler.add_job(run_intraday_scan, CronTrigger(hour=13, minute=0, timezone="Asia/Kolkata"), id="intraday_1300", name="Intraday 1H scan 1:00 PM", replace_existing=True)
        _scheduler.add_job(run_intraday_scan, CronTrigger(hour=14, minute=30, timezone="Asia/Kolkata"), id="intraday_1430", name="Intraday 1H scan 2:30 PM", replace_existing=True)
        _scheduler.start()
        logger.info("Scheduler started")
    except ImportError:
        logger.warning("APScheduler not installed.")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except:
            pass
        _scheduler = None

# ─── FastAPI App ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "templates").mkdir(exist_ok=True)
    start_scheduler()
    yield
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
    return {"status": "ok", "time": datetime.now().isoformat(), "active_tasks": len([t for t in tasks.values() if t["status"] == "running"])}


@app.post("/api/scan/start")
def start_scan(early: bool = False):
    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = {"status": "queued", "progress": "Queued...", "early_mode": early, "started_at": None, "completed_at": None, "results": [], "count": 0, "csv_file": None, "xlsx_file": None, "error": None}
    thread = threading.Thread(target=run_scan_task, args=(task_id, early), daemon=True)
    thread.start()
    return {"task_id": task_id, "status": "queued", "message": "Scan started. Poll /api/scan/status/{task_id} for progress."}

@app.get("/api/scan/status/{task_id}")
def scan_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    t = tasks[task_id]
    return {"task_id": task_id, "status": t["status"], "progress": t["progress"], "started_at": t["started_at"], "completed_at": t["completed_at"], "count": t["count"], "early_mode": t.get("early_mode", False), "has_results": len(t.get("results", [])) > 0}

@app.get("/api/scan/result/{task_id}")
def scan_result(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "Task not found")
    t = tasks[task_id]
    if t["status"] != "completed":
        raise HTTPException(400, f"Scan not completed yet. Status: {t['status']}")
    return {"task_id": task_id, "status": t["status"], "count": t["count"], "total_scanned": t.get("total_scanned", len(get_nse_symbols())), "mode": t.get("mode"), "completed_at": t["completed_at"], "results": t["results"], "csv_file": t["csv_file"], "xlsx_file": t["xlsx_file"]}

@app.get("/api/watchlist/latest")
def download_latest(early: bool = False):
    date_str = datetime.now().strftime("%Y-%m-%d")
    tag = "early" if early else "swing"
    xlsx_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.xlsx"
    csv_path = OUTPUT_DIR / f"watchlist_{tag}_{date_str}.csv"
    if xlsx_path.exists():
        return FileResponse(str(xlsx_path), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=f"NSE_Watchlist_{date_str}.xlsx")
    elif csv_path.exists():
        return FileResponse(str(csv_path), media_type="text/csv", filename=f"NSE_Watchlist_{date_str}.csv")
    raise HTTPException(404, "No watchlist file found. Run a scan first.")

@app.get("/api/watchlist/summary")
def watchlist_summary():
    csv_path = find_latest_csv()
    if not csv_path:
        return {"total": 0, "message": "No watchlist found"}
    try:
        df = pd.read_csv(csv_path)
        df = normalize_csv_data(df)
        date_str = Path(csv_path).stem.split("_")[-1] if Path(csv_path).stem.count("_") >= 2 else datetime.now().strftime("%Y-%m-%d")
        setup_col = df.get("1H_Setup", pd.Series(dtype=str))
        total_scanned = len(get_nse_symbols())
        summary = {"total": len(df), "total_scanned": total_scanned, "date": date_str, "fresh_breakouts": int((df.get("Stage") == "Fresh Breakout").sum()) if "Stage" in df else 0, "strong_momentum": int((df.get("Stage") == "Strong Momentum").sum()) if "Stage" in df else 0, "buy_now": int((setup_col == "BUY-R").sum()) + int((setup_col == "BUY-B").sum()), "buy_r": int((setup_col == "BUY-R").sum()), "buy_b": int((setup_col == "BUY-B").sum()), "sell_r": int((setup_col == "SELL-R").sum()), "sell_b": int((setup_col == "SELL-B").sum()), "neutral": int((setup_col == "NEUTRAL").sum()), "watch": 0, "wait": 0, "sectors": df["Sector"].value_counts().head(5).to_dict() if "Sector" in df else {}}
        return summary
    except Exception as e:
        return {"total": 0, "error": str(e)}

@app.get("/api/watchlist/latest-data")
def watchlist_latest_data(sync_trades: bool = Query(True, description="Auto-create trade positions from BUY NOW signals")):
    csv_path = find_latest_csv()
    if not csv_path:
        return {"count": 0, "results": [], "mode": "standard", "message": "No watchlist CSV found. Run a scan first."}
    try:
        df = pd.read_csv(csv_path)
        df = normalize_csv_data(df)
        if "Rank" in df.columns:
            df = df.sort_values("Rank", ascending=False).reset_index(drop=True)
        result_json = json.loads(df.to_json(orient="records", date_format="iso"))
        for row in result_json:
            for k, v in row.items():
                if isinstance(v, (np.integer,)): row[k] = int(v)
                elif isinstance(v, (np.floating,)): row[k] = round(float(v), 2)
                elif pd.isna(v): row[k] = None
        filename = Path(csv_path).name
        mode = "early" if "early" in filename else "standard"
        # Auto-create trade positions from BUY signals (same-day during hours, IST-aware)
        now = datetime.now()
        hour_ist = (now.hour + 5) % 24
        minute_ist = now.minute + 30
        if minute_ist >= 60:
            hour_ist = (hour_ist + 1) % 24
            minute_ist -= 60
        is_market_hours = (now.weekday() < 5 and 
                           ((hour_ist == 9 and 15 <= minute_ist) or 
                            (10 <= hour_ist <= 14) or
                            (hour_ist == 15 and minute_ist <= 30)))
        if sync_trades and result_json:
            try:
                tracker = get_tracker()
                created = tracker.create_positions_from_results(result_json, same_day_entry=is_market_hours)
                if created:
                    logger.info(f"Auto-created {len(created)} positions from CSV: {created}")
            except Exception as trade_e:
                logger.error(f"Error auto-creating positions from CSV: {trade_e}")
        total_scanned = len(get_nse_symbols())
        return {"count": len(result_json), "total_scanned": total_scanned, "results": result_json, "mode": mode, "csv_file": str(csv_path), "completed_at": datetime.fromtimestamp(os.path.getmtime(csv_path)).isoformat()}
    except Exception as e:
        return {"count": 0, "results": [], "total_scanned": 0, "mode": "standard", "error": str(e)}

# ─── Trade/Portfolio API Endpoints ─────────────────────────────────

@app.get("/api/trades/portfolio")
def trades_portfolio():
    try:
        tracker = get_tracker()
        summary = tracker.get_portfolio_summary()
        return summary
    except Exception as e:
        logger.error(f"Portfolio summary error: {e}")
        return {"total_invested": 0, "current_value": 0, "total_pnl": 0, "total_pnl_percent": 0, "win_rate": 0, "active_count": 0, "pending_count": 0, "closed_count": 0, "total_signals": 0, "wins": 0, "losses": 0, "error": str(e)}

@app.get("/api/trades/positions")
def trades_positions(status: str = Query("all"), from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to")):
    try:
        tracker = get_tracker()
        status_filter = status if status != "all" else None
        positions = tracker.get_positions(status_filter, from_date=from_date, to_date=to_date)
        return {"count": len(positions), "positions": positions}
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return {"count": 0, "positions": [], "error": str(e)}

@app.get("/api/trades/symbol-stats")
def trades_symbol_stats():
    try:
        tracker = get_tracker()
        stats = tracker.get_symbol_stats()
        return {"count": len(stats), "stats": stats}
    except Exception as e:
        logger.error(f"Symbol stats error: {e}")
        return {"count": 0, "stats": [], "error": str(e)}

@app.post("/api/trades/refresh")
def trades_refresh():
    try:
        tracker = get_tracker()
        result = tracker.refresh_all_prices()
        activated = tracker.process_pending_entries()
        closed = tracker.check_open_positions()
        return {"updated": result["updated"], "failed": result["failed"], "activated": len(activated), "closed": len(closed), "details": {"activated_symbols": [a["symbol"] for a in activated], "closed_positions": closed}}
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        return {"updated": 0, "failed": 0, "activated": 0, "closed": 0, "error": str(e)}

@app.get("/api/trades/diagnostics")
def trades_diagnostics():
    try:
        tracker = get_tracker()
        health = tracker.diagnose_health()
        return health
    except Exception as e:
        logger.error(f"Diagnostics error: {e}")
        return {"error": str(e)}

# ─── Serve Dashboard ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    if DASHBOARD_PATH.exists():
        return HTMLResponse(DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>")

@app.get("/manifest.json")
def manifest():
    if MANIFEST_PATH.exists():
        return JSONResponse(json.loads(MANIFEST_PATH.read_text()))
    return JSONResponse({})

@app.get("/sw.js")
def service_worker():
    if SW_PATH.exists():
        return Response(SW_PATH.read_text(), media_type="application/javascript")
    return Response("", media_type="application/javascript")

# ─── Debug endpoint ─────────────────────────────────────────────────
@app.get("/api/debug/1h/{symbol}")
def debug_1h(symbol: str):
    from nse_swing_scanner import analyze_1h, adx_dmi, heiken_ashi, ema, rsi, compute_daily_levels
    import yfinance as yf
    import pandas as pd
    sym = symbol.upper().strip()
    if not sym.endswith(".NS"):
        sym += ".NS"
    info = {"symbol": sym}
    df = yf.download(sym, period="10d", interval="1h", progress=False, auto_adjust=True)
    info["download_shape"] = str(df.shape)
    info["is_multiindex"] = isinstance(df.columns, pd.MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        if sym in df.columns.get_level_values(1).unique():
            df = df.xs(sym, axis=1, level=1).copy()
        elif sym in df.columns.get_level_values(0).unique():
            df = df.xs(sym, axis=1, level=0).copy()
    if not df.empty and "High" in df.columns:
        adx, dp, dm = adx_dmi(df["High"], df["Low"], df["Close"])
        info["adx"] = round(adx, 2)
        info["di_plus"] = round(dp, 2)
        info["di_minus"] = round(dm, 2)
    result = list(analyze_1h(sym))
    info["analyze_result"] = {"signal": result[1], "detail": result[2], "zone": result[3]}
    return info

# ─── Debug: filesystem info ─────────────────────────────────────────
@app.get("/api/debug/disk")
def debug_disk():
    """Debug endpoint to check disk mounts and permissions."""
    import os, subprocess
    info = {}
    # Check /data
    info["data_exists"] = os.path.exists("/data")
    info["data_is_dir"] = os.path.isdir("/data") if info["data_exists"] else False
    if info["data_is_dir"]:
        info["data_writable"] = os.access("/data", os.W_OK)
        try:
            info["data_contents"] = os.listdir("/data")
        except:
            info["data_contents"] = "N/A"
        try:
            st = os.stat("/data")
            info["data_uid"] = st.st_uid
            info["data_gid"] = st.st_gid
            info["data_mode"] = oct(st.st_mode)
        except:
            pass
    # Check /opt/render/project/src
    info["src_exists"] = os.path.exists("/opt/render/project/src")
    info["src_writable"] = os.access("/opt/render/project/src", os.W_OK) if info["src_exists"] else False
    # Current user
    info["cwd"] = os.getcwd()
    try:
        info["whoami"] = os.popen("whoami").read().strip()
    except: pass
    # Try mkdir
    try:
        os.makedirs("/data", exist_ok=True)
        test_path = "/data/test_write.txt"
        with open(test_path, "w") as f: f.write("ok")
        os.remove(test_path)
        info["mkdir_test"] = "PASS"
    except Exception as e:
        info["mkdir_test"] = f"FAIL: {e}"
    return info

# ─── Run (for local development) ────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  NSE Swing Scanner API v1.1")
    print(f"  Dashboard: http://localhost:8000")
    print(f"  API Docs:  http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run("nse_scanner_api:app", host="0.0.0.0", port=8000, reload=True)