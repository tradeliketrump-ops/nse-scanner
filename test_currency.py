"""Test currency conversion for futures data."""
import yfinance as yf
import pandas as pd

# USD/INR rate
print("Testing USD/INR...")
try:
    df = yf.download("USDINR=X", period="5d", interval="1d", progress=False)
    if not df.empty and "Close" in df.columns:
        usdinr = float(df["Close"].iloc[-1])
        print(f"USD/INR = {usdinr:.2f}")
    else:
        print("USDINR=X: No data, trying USDINR.NS...")
        df = yf.download("USDINR.NS", period="5d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            tickers = df.columns.get_level_values(1).unique()
            if len(tickers) > 0:
                df = df.xs(tickers[0], axis=1, level=1).copy()
        if not df.empty and "Close" in df.columns:
            usdinr = float(df["Close"].iloc[-1])
            print(f"USD/INR = {usdinr:.2f}")
        else:
            print("No USD/INR available, using 87.0 as default")
            usdinr = 87.0
except Exception as e:
    print(f"Error: {e}")
    usdinr = 87.0

# Test prices with conversion
symbols = [
    ("^NSEI", "Nifty 50", False),
    ("^NSEBANK", "Bank Nifty", False),
    ("GC=F", "Gold", True),
    ("SI=F", "Silver", True),
    ("MGC=F", "Gold Micro", True),
    ("SIL=F", "Silver Micro", True),
    ("CL=F", "Crude Oil WTI", True),
    ("NG=F", "Natural Gas", True),
    ("HG=F", "Copper", True),
    ("ALI=F", "Aluminum", True),
    ("ZNC=F", "Zinc", True),
    ("PL=F", "Platinum", True),
    ("PA=F", "Palladium", True),
]

print(f"\n{'Symbol':<15} {'Name':<20} {'Status':<8} {'USD Price':<12} {'INR Price':<14}")
print("-" * 70)

for sym, name, is_commodity in symbols:
    try:
        df = yf.download(sym, period="5d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            tickers = df.columns.get_level_values(1).unique()
            if len(tickers) > 0:
                df = df.xs(tickers[0], axis=1, level=1).copy()
        if df is not None and len(df) > 0 and "Close" in df.columns:
            last = df["Close"].iloc[-1]
            if pd.notna(last):
                usd = float(last)
                inr = usd * usdinr if is_commodity else usd
                print(f"{sym:<15} {name:<20} {'OK':<8} {usd:<12.2f} ₹{inr:<12.2f}")
            else:
                print(f"{sym:<15} {name:<20} {'NaN':<8}")
        else:
            print(f"{sym:<15} {name:<20} {'EMPTY':<8}")
    except Exception as e:
        print(f"{sym:<15} {name:<20} {'FAIL':<8}")