"""Test MCX Indian futures data sources."""
import yfinance as yf
import pandas as pd

tests = [
    # NSE Index Futures
    ("^NSEI", "Nifty 50 Spot"),
    ("^NSEBANK", "Bank Nifty Spot"),
    ("NIFTY=F", "Nifty Futures"),
    ("BANKNIFTY=F", "BankNifty Futures"),
    
    # MCX Commodities - Indian rupee denominated
    ("GOLD.NS", "Gold NS"),
    ("SILVER.NS", "Silver NS"),
    ("CRUDEOIL.NS", "Crude Oil NS"),
    ("NATGAS.NS", "Natural Gas NS"),
    ("COPPER.NS", "Copper NS"),
    ("ZINC.NS", "Zinc NS"),
    ("LEAD.NS", "Lead NS"),
    ("ALUMINIUM.NS", "Aluminum NS"),
    ("NICKEL.NS", "Nickel NS"),
    
    # MCX without .NS
    ("GOLD", "Gold (no NS)"),
    ("SILVER", "Silver (no NS)"),
    
    # MCX with MCX suffix
    ("GOLD.MCX", "Gold MCX"),
    ("SILVER.MCX", "Silver MCX"),
    ("CRUDEOIL.MCX", "Crude MCX"),
    
    # Yahoo specific commodity patterns
    ("0#GOLD=", "Gold Cont"),
    ("0#SILVER=", "Silver Cont"),
]

for sym, name in tests:
    try:
        d = yf.download(sym, period="2d", progress=False)
        if isinstance(d.columns, pd.MultiIndex):
            t = d.columns.get_level_values(1).unique()
            if len(t) > 0:
                d = d.xs(t[0], axis=1, level=1).copy()
        if d is not None and len(d) > 0 and "Close" in d.columns:
            v = d["Close"].iloc[-1]
            if pd.notna(v):
                print(f"OK {sym:<20} {name:<20} = {float(v):.2f}")
            else:
                print(f"-- {sym:<20} {name:<20} = NaN")
        else:
            print(f"XX {sym:<20} {name:<20} = No data")
    except Exception as e:
        print(f"ER {sym:<20} {name:<20} = {str(e)[:40]}")