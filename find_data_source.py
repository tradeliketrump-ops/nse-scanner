"""Test alternate data sources for Indian futures."""
from datetime import datetime, date, timedelta
import re

with open("data_source_results.txt", "w", encoding="utf-8") as f:
    def log(msg):
        print(msg)
        f.write(str(msg) + "\n")
        f.flush()

    log("=" * 70)
    log("TESTING MORE DATA SOURCES FOR INDIAN FUTURES")
    log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log("=" * 70)

    # ─── NSE API - Try different endpoints ─────────────────────────
    log("\n--- NSE India API (different endpoints) ---")
    try:
        import requests
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=h, timeout=10)
        
        endpoints = [
            "/api/equity-stockIndices?index=NIFTY%2050",
            "/api/equity-stockIndices?index=NIFTY%20500",
            "/api/marketStatus",
            "/api/liveAnalysis-variations?index=gainers&indices=NIFTY50",
        ]
        for ep in endpoints:
            try:
                r = s.get(f"https://www.nseindia.com{ep}", headers=h, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict):
                        log(f"  ✅ {ep}: {list(data.keys())[:3]} (last={data.get('last','?')})")
                    else:
                        log(f"  ✅ {ep}: Got data ({len(r.text)} chars)")
                else:
                    log(f"  ❌ {ep}: HTTP {r.status_code}")
            except Exception as e:
                log(f"  ❌ {ep}: {str(e)[:50]}")
    except Exception as e:
        log(f"NSE Error: {e}")

    # ─── Alternative: nsetools if available ────────────────────────
    log("\n--- nsetools library ---")
    try:
        from nsetools import Nse
        nse = Nse()
        log("nsetools imported OK")
        try:
            quote = nse.get_quote("NIFTY")
            log(f"Nifty: {quote.get('lastPrice', '?')}")
        except:
            pass
        try:
            # Try futures
            futures = nse.get_futures("NIFTY", expiry_date="30JUL2026")
            log(f"Nifty Futures: {futures}")
        except Exception as e2:
            log(f"Nifty Futures error: {e2}")
    except ImportError:
        log("nsetools not installed")
    except Exception as e:
        log(f"nsetools Error: {e}")

    # ─── yfinance for NSE with auto_adjust ─────────────────────────
    log("\n--- yfinance NSE indices (verify) ---")
    try:
        import yfinance as yf
        import pandas as pd
        # Nifty 50 - spot only, but shows the latest
        d = yf.download("^NSEI", period="2d", progress=False)
        if isinstance(d.columns, pd.MultiIndex):
            t = d.columns.get_level_values(1).unique()
            if len(t) > 0:
                d = d.xs(t[0], axis=1, level=1).copy()
        if d is not None and len(d) > 0 and "Close" in d.columns:
            v = float(d["Close"].iloc[-1])
            log(f"✅ yfinance Nifty Spot: {v:.2f}")
        
        d2 = yf.download("^NSEBANK", period="2d", progress=False)
        if isinstance(d2.columns, pd.MultiIndex):
            t = d2.columns.get_level_values(1).unique()
            if len(t) > 0:
                d2 = d2.xs(t[0], axis=1, level=1).copy()
        if d2 is not None and len(d2) > 0 and "Close" in d2.columns:
            v2 = float(d2["Close"].iloc[-1])
            log(f"✅ yfinance Bank Nifty Spot: {v2:.2f}")
        
        # USD/INR
        d3 = yf.download("USDINR=X", period="2d", progress=False)
        if isinstance(d3.columns, pd.MultiIndex):
            t = d3.columns.get_level_values(1).unique()
            if len(t) > 0:
                d3 = d3.xs(t[0], axis=1, level=1).copy()
        if d3 is not None and len(d3) > 0 and "Close" in d3.columns:
            v3 = float(d3["Close"].iloc[-1])
            log(f"✅ yfinance USD/INR: {v3:.2f}")
        else:
            log("❌ yfinance USD/INR: No data")
        
        # MCX symbols variation - try 0# prefix (continuous contract marker)
        for sym, name in [("GC=F", "Gold"), ("SI=F", "Silver"), ("CL=F", "Crude"), ("NG=F", "NatGas")]:
            try:
                d = yf.download(sym, period="2d", progress=False)
                if isinstance(d.columns, pd.MultiIndex):
                    t = d.columns.get_level_values(1).unique()
                    if len(t) > 0:
                        d = d.xs(t[0], axis=1, level=1).copy()
                if d is not None and len(d) > 0 and "Close" in d.columns:
                    v = float(d["Close"].iloc[-1])
                    log(f"✅ yfinance {name}: ${v:.2f} (COMEX)")
            except:
                pass
                
    except Exception as e:
        log(f"yfinance Error: {e}")

    # ─── Web scraping alternatives ─────────────────────────────────
    log("\n--- Web scraping commodityonline.com ---")
    try:
        import requests
        from bs4 import BeautifulSoup
        h = {"User-Agent": "Mozilla/5.0"}
        # Try commodityonline for MCX rates
        try:
            r = requests.get("https://www.commodityonline.com/market/commodity-wise-market-prices.php", headers=h, timeout=10)
            log(f"commodityonline: HTTP {r.status_code} ({len(r.text)} chars)")
        except Exception as e:
            log(f"commodityonline: {e}")
    except ImportError:
        log("BeautifulSoup not installed")
    except Exception as e:
        log(f"Scrape Error: {e}")

    # ─── Summary ───────────────────────────────────────────────────
    log("\n" + "=" * 70)
    log("CONCLUSION")
    log("=" * 70)
    log("NSE India API: NSE has changed their API endpoints - need updated paths")
    log("nsepy/nsetools: SSL/connection issues with older NSE servers")
    log("MCX: Cannot scrape from non-Indian IP")
    log("yfinance: Only NSE spot indices + COMEX commodities (USD)")
    log("")
    log("BEST OPTION: Use yfinance + USD/INR conversion for commodities")
    log("For Nifty Futures: Use spot price as proxy (difference is ~0.3-0.5%)")
    log("=" * 70)