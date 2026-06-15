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
"""

import os, sys, json, uuid, time, threading, csv, io
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
import numpy as np

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
import pandas as pd

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nse_swing_scanner import run_scanner, NSE_SYMBOLS

# ─── Config ─────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent
DASHBOARD_PATH = OUTPUT_DIR / "templates" / "dashboard.html"
STATIC_DIR = OUTPUT_DIR / "static"
MANIFEST_PATH = STATIC_DIR / "manifest.json"
SW_PATH = STATIC_DIR / "sw.js"

# In-memory task store
tasks = {}

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

# ─── FastAPI App ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    # Create static directory
    STATIC_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "templates").mkdir(exist_ok=True)
    yield

app = FastAPI(
    title="NSE Swing Trade Scanner",
    description="Daily scan for NSE swing trading opportunities with 1-hour entry analysis",
    version="1.0.0",
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
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = OUTPUT_DIR / f"watchlist_swing_{date_str}.csv"

    if not csv_path.exists():
        return {"total": 0, "message": "No watchlist found"}

    try:
        df = pd.read_csv(csv_path)
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
    print("  NSE Swing Scanner API")
    print(f"  Dashboard: http://localhost:8000")
    print(f"  API Docs:  http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run("nse_scanner_api:app", host="0.0.0.0", port=8000, reload=True)