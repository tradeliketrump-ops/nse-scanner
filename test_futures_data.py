"""Test what futures data is available via yfinance - export to clean text file."""
import yfinance as yf
import pandas as pd
import sys

results = []
results.append("=" * 60)
results.append("TESTING FUTURES DATA SOURCES")
results.append("=" * 60)

tests = [
    # NSE Index Futures
    ("^NSEI", "Nifty 50 Index"),
    ("^NSEBANK", "Bank Nifty Index"),
    ("^CNXIT", "Nifty IT Index"),
    ("^BSESN", "Sensex"),
    # Commodity Futures (global)
    ("GC=F", "Gold Futures"),
    ("SI=F", "Silver Futures"),
    ("MGC=F", "Gold Micro Futures"),
    ("SIL=F", "Silver Micro Futures"),
    ("CL=F", "Crude Oil WTI"),
    ("NG=F", "Natural Gas"),
    ("HG=F", "Copper Futures"),
    ("PL=F", "Platinum Futures"),
    ("PA=F", "Palladium Futures"),
    ("ALI=F", "Aluminum Futures"),
    ("ZNC=F", "Zinc Futures"),
    # Indian specific (known working patterns)
    ("GOLD=F", "Gold (MCX attempt)"),
    ("CRUDEOIL.F", "Crude Oil (MCX attempt)"),
    # NCDEX Agri
    ("SOYBEAN.F", "Soybean (NCDEX attempt)"),
]

results.append(f"\n{'Symbol':<20} {'Name':<30} {'Status':<8} {'Close':<12}")
results.append("-" * 70)

count_ok = 0
count_fail = 0
for sym, name in tests:
    try:
        df = yf.download(sym, period="5d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            tickers = df.columns.get_level_values(1).unique()
            if len(tickers) > 0:
                df = df.xs(tickers[0], axis=1, level=1).copy()
        close_val = "N/A"
        if df is not None and len(df) > 0 and "Close" in df.columns:
            last = df["Close"].iloc[-1]
            if pd.notna(last):
                close_val = f"{float(last):.2f}"
                results.append(f"{sym:<20} {name:<30} {'OK':<8} {close_val:<12}")
                count_ok += 1
            else:
                results.append(f"{sym:<20} {name:<30} {'NaN':<8}")
                count_fail += 1
        else:
            results.append(f"{sym:<20} {name:<30} {'EMPTY':<8}")
            count_fail += 1
    except Exception as e:
        results.append(f"{sym:<20} {name:<30} {'FAIL':<8}")
        count_fail += 1

results.append(f"\n{'='*60}")
results.append(f"OK: {count_ok}, Failed: {count_fail}")
results.append(f"{'='*60}")

with open("futures_data_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(results))

print("Written to futures_data_test.txt")
print(f"OK: {count_ok}, Failed: {count_fail}")