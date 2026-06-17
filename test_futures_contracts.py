"""Test futures contract symbols including monthly contracts."""
import yfinance as yf
import pandas as pd
from datetime import datetime

results = []
results.append("=" * 60)
results.append("TESTING FUTURES CONTRACT SYMBOLS")
today = datetime.now()
day = today.day
month = today.month
year = today.year

# Determine month code: Jan=F, Feb=G, Mar=H, Apr=J, May=K, Jun=M, Jul=N, Aug=Q, Sep=U, Oct=V, Nov=X, Dec=Z
month_codes = {1:'F',2:'G',3:'H',4:'J',5:'K',6:'M',7:'N',8:'Q',9:'U',10:'V',11:'X',12:'Z'}

# If day <= 15, use current month; else next month
if day <= 15:
    fut_month = month
    fut_year = year
else:
    fut_month = month + 1 if month < 12 else 1
    fut_year = year + 1 if month == 12 else year

fut_code = month_codes[fut_month]
fut_year_str = str(fut_year)[-1]  # last digit of year
results.append(f"Today: {today.strftime('%Y-%m-%d')} (day={day})")
results.append(f"Futures contract: {fut_code}{fut_year_str} ({fut_month}/{fut_year})")
results.append("=" * 60)

# Test various formats
tests = [
    # Continuous futures
    ("^NSEI", f"Nifty 50 Spot"),
    ("^NSEBANK", f"Bank Nifty Spot"),
    ("NIFTY=F", "Nifty Futures Cont"),
    ("BANKNIFTY=F", "Bank Nifty Futures Cont"),
    # Indian NSE specific with month code
    (f"NIFTY{fut_code}{fut_year_str}.NS", f"Nifty {fut_code}{fut_year_str}"),
    (f"BANKNIFTY{fut_code}{fut_year_str}.NS", f"Bank Nifty {fut_code}{fut_year_str}"),
    (f"NIFTY24{fut_code}.NS", f"Nifty 24{fut_code}"),
    # BSE futures
    ("SENSEX=F", "Sensex Futures Cont"),
]

results.append(f"\n{'Symbol':<25} {'Name':<30} {'Status':<8} {'Close':<12}")
results.append("-" * 75)

for sym, name in tests:
    try:
        df = yf.download(sym, period="5d", interval="1d", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            tickers = df.columns.get_level_values(1).unique()
            if len(tickers) > 0:
                df = df.xs(tickers[0], axis=1, level=1).copy()
            else:
                tickers = df.columns.get_level_values(0).unique()
                if len(tickers) > 0:
                    df = df.xs(tickers[0], axis=1, level=0).copy()
        close_val = "N/A"
        if df is not None and len(df) > 0 and "Close" in df.columns:
            last = df["Close"].iloc[-1]
            if pd.notna(last):
                close_val = f"{float(last):.2f}"
                vol = df["Volume"].iloc[-1] if "Volume" in df.columns else "?"
                results.append(f"{sym:<25} {name:<30} {'OK':<8} {close_val:<12} vol={vol}")
            else:
                results.append(f"{sym:<25} {name:<30} {'NaN':<8}")
        else:
            results.append(f"{sym:<25} {name:<30} {'EMPTY':<8}")
    except Exception as e:
        results.append(f"{sym:<25} {name:<30} {'FAIL':<8} {str(e)[:30]}")

with open("futures_contracts_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(results))
print("Written to futures_contracts_test.txt")