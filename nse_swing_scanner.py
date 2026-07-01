#!/usr/bin/env python3
"""
Daily NSE Swing Trade Scanner — with 1H Entry Analysis
-------------------------------------------------------
Uses Daily timeframe for trend identification, then 1-hour data
for entry timing optimization. Parallel processing for speed.

Usage:
  python nse_swing_scanner.py                         # Standard scan
  python nse_swing_scanner.py --no-rsi                # No RSI filter
  python nse_swing_scanner.py --early                 # Early breakout mode
  python nse_swing_scanner.py --no-1h                 # Skip 1H analysis

Dependencies: pip install yfinance pandas numpy openpyxl
"""
import os, sys, warnings, argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── CONFIG ──────────────────────────────────────────────────────────
OUTPUT_DIR          = "."
EMA_PERIOD          = 20
SMA_PERIOD          = 50
RSI_PERIOD          = 14
VOLUME_LOOKBACK     = 20
MIN_MARKET_CAP_CR   = 5000
MIN_AVG_VOLUME      = 500_000
USE_RSI_FILTER      = True
RSI_MIN, RSI_MAX    = 40, 70
PRICE_LOOKBACK      = 20
EARNINGS_EXCLUSION  = 28
BREAKOUT_LOOKBACK   = 30
NEAR_MISS_PCT       = 0.5
PARALLEL_WORKERS    = 10  # for potential parallel operations

# ─── PINE SCRIPT TV-LEVEL CONSTANTS ────────────────────────────────
SELL_REV_MULT   = 0.29   # sellReversal = pivot + dailyATR * 0.29
BUY_REV_MULT    = 0.21   # buyReversal  = pivot - dailyATR * 0.21
BREAKOUT_MULT   = 0.54   # breakout     = pivot + dailyATR * 0.54
BREAKDOWN_MULT  = 0.46   # breakdown    = pivot - dailyATR * 0.46
ADX_THRESHOLD   = 20     # minimum ADX for trend filter
ADX_LEN         = 14     # ADX lookback period
ADX_SMOOTH      = 14     # ADX smoothing period
RSI_EXTREME_LONG  = 80   # avoid buy when RSI > 80
RSI_EXTREME_SHORT = 20   # avoid sell when RSI < 20

# ─── NSE SYMBOLS (Nifty500 Universe) ─────────────────────────────────
# Static fallback list covering ~500 Nifty500 stocks.
# On first import, the scanner tries to fetch live Nifty500 constituents
# from NSE India API; if that fails, this list is used.
NIFTY500_FALLBACK = [
    # NIFTY 50 (kept in order)
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS",
    "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS","ITC.NS",
    "BAJFINANCE.NS","LT.NS","WIPRO.NS","AXISBANK.NS","TITAN.NS",
    "ASIANPAINT.NS","MARUTI.NS","SUNPHARMA.NS","HCLTECH.NS","NTPC.NS",
    "ONGC.NS","POWERGRID.NS","ULTRACEMCO.NS","BAJAJFINSV.NS","ADANIPORTS.NS",
    "NESTLEIND.NS","M&M.NS","TATAMOTORS.NS","JSWSTEEL.NS","TATASTEEL.NS",
    "TECHM.NS","INDUSINDBK.NS","GRASIM.NS","DIVISLAB.NS","DRREDDY.NS",
    "BPCL.NS","BRITANNIA.NS","HINDALCO.NS","EICHERMOT.NS","SBILIFE.NS",
    "BAJAJ-AUTO.NS","COALINDIA.NS","HDFCLIFE.NS","SHREECEM.NS","UPL.NS",
    "HEROMOTOCO.NS","TATACONSUM.NS","CIPLA.NS","APOLLOHOSP.NS","ADANIGREEN.NS",
    # NIFTY NEXT 50
    "ADANIENT.NS","ADANITRANS.NS","AMBUJACEM.NS","ATGL.NS","AVENUE.NS",
    "BANKBARODA.NS","BERGEPAINT.NS","BHARATFORG.NS","BIOCON.NS","BOSCHLTD.NS",
    "CANBK.NS","CHOLAFIN.NS","COFORGE.NS","COLGATE.NS","CONCOR.NS",
    "COROMANDEL.NS","CROMPTON.NS","CUMMINSIND.NS","DABUR.NS","DALBHARAT.NS",
    "DIXON.NS","DLF.NS","ESCORTS.NS","EXIDEIND.NS","FEDERALBNK.NS",
    "GAIL.NS","GODREJCP.NS","GODREJPROP.NS","GUJGASLTD.NS","HAL.NS",
    "HAVELLS.NS","HDFCAMC.NS","HINDZINC.NS","ICICIGI.NS","ICICIPRULI.NS",
    "IDFCFIRSTB.NS","IEX.NS","IGL.NS","INDIGO.NS","INDUSTOWER.NS",
    "IOC.NS","IRCTC.NS","JINDALSTEL.NS","JUBLFOOD.NS","L&T.NS",
    "LICI.NS","LUPIN.NS","LTIM.NS","MCDOWELL-N.NS","MCX.NS",
    "METROPOLIS.NS","MFSL.NS","MOTHERSON.NS","MPHASIS.NS","MRF.NS",
    "MUTHOOTFIN.NS","NATIONALUM.NS","NAUKRI.NS","NAVINFLUOR.NS","NMDC.NS",
    "OBEROIRLTY.NS","PAGEIND.NS","PEL.NS","PERSISTENT.NS","PETRONET.NS",
    "PFC.NS","PIDILITIND.NS","PIIND.NS","PNB.NS","POLYCAB.NS",
    "PPLPHARMA.NS","RBLBANK.NS","RECLTD.NS","SAIL.NS","SRTRANSFIN.NS",
    "STAR.NS","SUNTV.NS","SYNGENE.NS","TATACOMM.NS","TATAELXSI.NS",
    "TATAPOWER.NS","TIINDIA.NS","TORNTPHARM.NS","TRENT.NS","TVSMOTOR.NS",
    "UBL.NS","UNITDSPR.NS","VBL.NS","VEDL.NS","VOLTAS.NS",
    "WHIRLPOOL.NS","ZEEL.NS","ZOMATO.NS","ZYDUSLIFE.NS",
    # NIFTY MIDCAP 100 (additional liquid stocks)
    "AARTIIND.NS","ABB.NS","ABCAPITAL.NS","ABFRL.NS","ACC.NS",
    "ASTRAL.NS","AUROPHARMA.NS","BALKRISIND.NS","BANDHANBNK.NS","BATAINDIA.NS",
    "BEL.NS","BHEL.NS","BSE.NS","CARBORUNIV.NS","CASTROLIND.NS",
    "CEATLTD.NS","CENTRALBK.NS","CERA.NS","CGPOWER.NS","CHAMBELFERT.NS",
    "CHEMPLASTS.NS","CHOLAHLDNG.NS","COCHINSHIP.NS","CRISIL.NS","CSBBANK.NS",
    "CYIENT.NS","DCMSHRIRAM.NS","DEEPAKNTR.NS","DELTACORP.NS","DEVYANI.NS",
    "DHANUKA.NS","DISHTV.NS","DIVISLAB.NS","DMART.NS","EDELWEISS.NS",
    "EIHOTEL.NS","EMAMILTD.NS","ENDURANCE.NS","ENGINERSIN.NS","EQUITASBNK.NS",
    "ERIS.NS","FACT.NS","FINPIPE.NS","FIVESTAR.NS","FLUOROCHEM.NS",
    "FORTIS.NS","GLENMARK.NS","GMRINFRA.NS","GNFC.NS","GOODYEAR.NS",
    "GPPL.NS","GRANULES.NS","GRAPHITE.NS","GREAVESCOT.NS","GRINDWELL.NS",
    "GSFC.NS","GSPL.NS","HEIDELBERG.NS","HINDCOPPER.NS","HINDMOTORS.NS",
    "HINDWARE.NS","HONAUT.NS","HUDCO.NS","IBULHSGFIN.NS","IDBI.NS",
    "IDEA.NS","INDIAMART.NS","INDHOTEL.NS","INDIGOPNTS.NS","INDOSTAR.NS",
    "INFIBEAM.NS","INGERRAND.NS","INOXLEISUR.NS","INTELLECT.NS","IOLCP.NS",
    "IPCALAB.NS","IRB.NS","ISEC.NS","ITI.NS","JBCHEPHARM.NS",
    "JKCEMENT.NS","JKLAKSHMI.NS","JKPAPER.NS","JKTYRE.NS","JSWENERGY.NS",
    "JSL.NS","JYOTHYLAB.NS","KALPATPOWR.NS","KANSAINER.NS","KEI.NS",
    "KPRMILL.NS","KRBL.NS","KSB.NS","LALPATHLAB.NS","LAURUSLABS.NS",
    "LEMONTREE.NS","LINDEINDIA.NS","MAHSCOOTER.NS","MAHSEAMLES.NS","MAITHANALL.NS",
    "MANAPPURAM.NS","MANGALAM.NS","MARICO.NS","MAXHEALTH.NS","MAZDOCK.NS",
    "MEDANTA.NS","MINDACORP.NS","MINDSPACE.NS","MIRZAINT.NS","MMTC.NS",
    "MOBILIQ.NS","MOLDTKPAC.NS","MOTILALOFS.NS","MSUMI.NS","MUKANDLTD.NS",
    "MUNJALAU.NS","NATCOPHARM.NS","NBCC.NS","NCC.NS","NESCO.NS",
    "NETWORK18.NS","NHPC.NS","NIACL.NS","NIITLTD.NS","NLCINDIA.NS",
    "NUVOCO.NS","OFSS.NS","OIL.NS","ORIENTELEC.NS","P&G.NS",
    "PAGEIND.NS","PARKER.NS","PCJEWELLER.NS","PHILIPCARB.NS","POLYMED.NS",
    "POWERMECH.NS","POX.NS","PRESTIGE.NS","PRINCEPIPE.NS","PRISMJOHNSON.NS",
    "PVRINOX.NS","QUESS.NS","RADICO.NS","RAILTEL.NS","RAIN.NS",
    "RAMCOCEM.NS","RATNAMANI.NS","RAYMOND.NS","RBL.NS","REDINGTON.NS",
    "RELAXO.NS","REPCOHOME.NS","RFLL.NS","RITES.NS","RVNL.NS",
    "SADBHAV.NS","SAFARI.NS","SAGCEM.NS","SANOFI.NS","SCHAEFFLER.NS",
    "SEDIT.NS","SEQUENT.NS","SHARDACROP.NS","SHOPER.NS","SHRIRAMFIN.NS",
    "SIEMENS.NS","SKFINDIA.NS","SOBHA.NS","SOLARINDS.NS","SPICEJET.NS",
    "SRF.NS","STARCEMENT.NS","STERLING.NS","STRTECH.NS","SUDAR.NS",
    "SUNDARMFIN.NS","SUNDRMFAST.NS","SUPRAJIT.NS","SUPREMEIND.NS","SURAJEST.NS",
    "SUVEN.NS","SWANENERGY.NS","SYMPHONY.NS","TAINWALCHM.NS","TANLA.NS",
    "TATACHEM.NS","TATAINVEST.NS","TATAMETALI.NS","TATAPOWER.NS","TBZ.NS",
    "TCI.NS","TCIEXP.NS","TECHNO.NS","TEJASNET.NS","THERMAX.NS",
    "THOMASCOOK.NS","TIMKEN.NS","TITAGARH.NS","TMB.NS","TNPL.NS",
    "TORNTPOWER.NS","TRIDENT.NS","TRITURBINE.NS","TTKPRESTIGE.NS","TV18BRDCST.NS",
    "UCAL.NS","UFLEX.NS","UNIONBANK.NS","UNOMINDA.NS","UTIAMC.NS",
    "VARDHMAN.NS","VARROC.NS","VESUVIUS.NS","VGUARD.NS","VIJAYABANK.NS",
    "VINATIORGA.NS","VIPIND.NS","VISHNU.NS","VSTIND.NS","VSTTILLERS.NS",
    "WABAG.NS","WELCORP.NS","WELENT.NS","WESTLIFE.NS","WOCKPHARMA.NS",
    "YESBANK.NS","ZENSARTECH.NS","ZFCVINDIA.NS","ZODIACLOTH.NS",
    
]

# Cache for NSE symbols
_NSE_SYMBOLS_CACHE = None

def fetch_nifty500_symbols():
    """Try to fetch live Nifty500 symbols from NSE India API."""
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=headers, timeout=10)
        r = sess.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500",
            headers=headers, timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            symbols = [item["symbol"] + ".NS" for item in data.get("data", [])]
            if len(symbols) >= 400:
                print(f"  ✅ Fetched {len(symbols)} Nifty500 symbols from NSE API")
                return symbols
        print(f"  [!] NSE API returned {len(symbols) if 'symbols' in dir() else 0} symbols, using fallback")
    except Exception as e:
        print(f"  [!] Could not fetch Nifty500 from NSE API: {e}")
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in NIFTY500_FALLBACK:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    print(f"  [i] Using Nifty500 fallback ({len(unique)} unique symbols from {len(NIFTY500_FALLBACK)} total)")
    return unique

def get_nse_symbols(force_refresh=False):
    """Get NSE symbols (cached). First call tries live API, then falls back."""
    global _NSE_SYMBOLS_CACHE
    if _NSE_SYMBOLS_CACHE is None or force_refresh:
        _NSE_SYMBOLS_CACHE = fetch_nifty500_symbols()
    return _NSE_SYMBOLS_CACHE

# For backward compatibility - NSE_SYMBOLS lazy-loads on access
class _LazySymbolList:
    def __init__(self):
        self._resolved = None
    def __iter__(self):
        if self._resolved is None:
            self._resolved = get_nse_symbols()
        return iter(self._resolved)
    def __len__(self):
        if self._resolved is None:
            self._resolved = get_nse_symbols()
        return len(self._resolved)
    def __getitem__(self, i):
        if self._resolved is None:
            self._resolved = get_nse_symbols()
        return self._resolved[i]
    def __contains__(self, x):
        if self._resolved is None:
            self._resolved = get_nse_symbols()
        return x in self._resolved
    def __bool__(self):
        return True
    def __repr__(self):
        if self._resolved is None:
            self._resolved = get_nse_symbols()
        return repr(self._resolved)

NSE_SYMBOLS = _LazySymbolList()
NIFTY50_SYMBOL = "^NSEI"
NIFTY_SPOT = "^NSEI"  # Nifty 50 Spot Index for FUT trading signals

SECTOR_MAP = {
    "RELIANCE":"Oil & Gas","TCS":"IT","HDFCBANK":"Banking","ICICIBANK":"Banking",
    "INFY":"IT","HINDUNILVR":"FMCG","SBIN":"Banking","BHARTIARTL":"Telecom",
    "KOTAKBANK":"Banking","ITC":"FMCG","BAJFINANCE":"Fin Services","LT":"Infra",
    "WIPRO":"IT","AXISBANK":"Banking","TITAN":"Consumer","ASIANPAINT":"Consumer",
    "MARUTI":"Auto","SUNPHARMA":"Pharma","HCLTECH":"IT","NTPC":"Power",
    "ONGC":"Oil & Gas","POWERGRID":"Power","ULTRACEMCO":"Infra","BAJAJFINSV":"Fin Services",
    "ADANIPORTS":"Infra","NESTLEIND":"FMCG","M&M":"Auto","TATAMOTORS":"Auto",
    "JSWSTEEL":"Metals","TATASTEEL":"Metals","TECHM":"IT","INDUSINDBK":"Banking",
    "GRASIM":"Infra","DIVISLAB":"Pharma","DRREDDY":"Pharma","BPCL":"Oil & Gas",
    "BRITANNIA":"FMCG","HINDALCO":"Metals","EICHERMOT":"Auto","SBILIFE":"Insurance",
    "BAJAJ-AUTO":"Auto","COALINDIA":"Metals","HDFCLIFE":"Insurance","SHREECEM":"Infra",
    "UPL":"Chemicals","HEROMOTOCO":"Auto","TATACONSUM":"FMCG","CIPLA":"Pharma",
    "APOLLOHOSP":"Healthcare","ADANIGREEN":"Energy","ADANIENT":"Diversified",
    "ADANITRANS":"Energy","AMBUJACEM":"Infra","ATGL":"Oil & Gas","AVENUE":"Consumer",
    "BANKBARODA":"Banking","BERGEPAINT":"Consumer","BHARATFORG":"Auto","BIOCON":"Pharma",
    "BOSCHLTD":"Auto","CANBK":"Banking","CHOLAFIN":"Fin Services","COFORGE":"IT",
    "COLGATE":"FMCG","CONCOR":"Logistics","COROMANDEL":"Fertilisers","CROMPTON":"Consumer",
    "CUMMINSIND":"Infra","DABUR":"FMCG","DALBHARAT":"Infra","DIXON":"Consumer",
    "DLF":"Real Estate","ESCORTS":"Auto","EXIDEIND":"Auto","FEDERALBNK":"Banking",
    "GAIL":"Oil & Gas","GODREJCP":"FMCG","GODREJPROP":"Real Estate","GUJGASLTD":"Oil & Gas",
    "HAL":"Defence","HAVELLS":"Consumer","HDFCAMC":"Fin Services","HINDZINC":"Metals",
    "ICICIGI":"Insurance","ICICIPRULI":"Insurance","IDFCFIRSTB":"Banking","IEX":"Power",
    "IGL":"Oil & Gas","INDIGO":"Aviation","INDUSTOWER":"Telecom","IOC":"Oil & Gas",
    "IRCTC":"Aviation","JINDALSTEL":"Metals","JUBLFOOD":"FMCG","LICI":"Insurance",
    "LUPIN":"Pharma","LTIM":"IT","MCDOWELL-N":"FMCG","MCX":"Fin Services",
    "METROPOLIS":"Healthcare","MFSL":"Fin Services","MOTHERSON":"Auto","MPHASIS":"IT",
    "MRF":"Auto","MUTHOOTFIN":"Fin Services","NATIONALUM":"Metals","NAUKRI":"IT",
    "NAVINFLUOR":"Chemicals","NMDC":"Metals","OBEROIRLTY":"Real Estate","PAGEIND":"Consumer",
    "PEL":"Consumer","PERSISTENT":"IT","PETRONET":"Oil & Gas","PFC":"Fin Services",
    "PIDILITIND":"Chemicals","PIIND":"Pharma","PNB":"Banking","POLYCAB":"Consumer",
    "PPLPHARMA":"Pharma","RBLBANK":"Banking","RECLTD":"Fin Services","SAIL":"Metals",
    "SRTRANSFIN":"Fin Services","STAR":"Healthcare","SUNTV":"Media","SYNGENE":"Pharma",
    "TATACOMM":"Telecom","TATAELXSI":"IT","TATAPOWER":"Power","TIINDIA":"Infra",
    "TORNTPHARM":"Pharma","TRENT":"Consumer","TVSMOTOR":"Auto","UBL":"FMCG",
    "UNITDSPR":"FMCG","VBL":"FMCG","VEDL":"Metals","VOLTAS":"Consumer",
    "WHIRLPOOL":"Consumer","ZEEL":"Media","ZOMATO":"Consumer Services","ZYDUSLIFE":"Pharma",
}

# ─── CORE INDICATORS ─────────────────────────────────────────────────
def strip_ns(s): return s.replace(".NS","")
def get_sector(s): return SECTOR_MAP.get(strip_ns(s),"Other")

def heiken_ashi(df):
    ha = df.copy()
    ha["HA_C"] = (ha.Open + ha.High + ha.Low + ha.Close) / 4.0
    o = [ha.Open.iloc[0]]
    for i in range(1,len(ha)): o.append((o[i-1]+ha["HA_C"].iloc[i-1])/2.0)
    ha["HA_O"] = o
    ha["HA_H"] = ha[["High","HA_O","HA_C"]].max(1)
    ha["HA_L"] = ha[["Low","HA_O","HA_C"]].min(1)
    return ha

def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def sma(s,p): return s.rolling(p).mean()

def rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0.); l=-d.where(d<0,0.)
    ag=g.rolling(p,min_periods=p).mean(); al=l.rolling(p,min_periods=p).mean()
    for i in range(p,len(ag)):
        ag.iloc[i]=(ag.iloc[i-1]*(p-1)+g.iloc[i])/p
        al.iloc[i]=(al.iloc[i-1]*(p-1)+l.iloc[i])/p
    rs=ag/al.replace(0,np.nan)
    return 100-(100/(1+rs))

def hh_hl(df,lb=20):
    if len(df)<lb: return False
    r=df.tail(lb); h=lb//2
    return r.tail(h)["HA_H"].max()>r.head(h)["HA_H"].max() and r.tail(h)["HA_L"].min()>r.head(h)["HA_L"].min()

def low_wick(df):
    if len(df)<1: return False
    l=df.iloc[-1]; tr=l["HA_H"]-l["HA_L"]
    if tr==0: return False
    return (l["HA_H"]-max(l["HA_O"],l["HA_C"]))/tr<0.3

def dist(p,r): return ((p-r)/r*100.) if r else 0.

def rel_strength(sr,nr,lb=63):
    ml=min(len(sr),len(nr),lb)
    if ml<20: return 50.
    sr,nr=sr.tail(ml),nr.tail(ml)
    return max(0,min(100,50+(((1+sr).prod()-1)-((1+nr).prod()-1))*100))

def vol_spike(v,lb=20):
    if len(v)<lb+1: return False,0.
    av=v.tail(lb+1).iloc[:-1].mean(); cv=v.iloc[-1]
    if av==0: return False,0.
    r=cv/av; return r>1.,r

def est_entry(df,e20):
    if len(df)<5: return f"{e20:.2f}-{e20*1.02:.2f}"
    lc,rl=df.Close.iloc[-1],df.Low.tail(10).min()
    return f"{max(e20,rl):.2f}-{lc*1.01:.2f}"

def est_stop(df,s50,e20):
    if len(df)<5: return round(e20*.98,2)
    return round(min(df.Low.tail(5).min(),e20*.98),2)

def est_rr(ez,sl,tm=2.5):
    try:
        p=ez.split("-"); em=(float(p[0])+float(p[1]))/2.
    except: return "N/A",0.
    r=em-sl
    if r<=0: return "N/A",0.
    rr=(em+r*tm-em)/r
    return f"1:{rr:.2f}",rr

def calc_priority(row):
    w={"trend":.25,"vol":.20,"rs":.20,"liq":.20,"struct":.15}
    s=0.
    s+=w["trend"]*min(100,abs(row.get("D_E20",0))*5)
    s+=w["vol"]*min(100,(row.get("V_Ratio",1.)-1.)*100)
    s+=w["rs"]*row.get("RS",50)
    s+=w["liq"]*min(100,(row.get("Avg_Vol",0)/10_000_000)*100)
    s+=w["struct"]*(int(row.get("HH_HL",False))*50+int(row.get("L_Wick",False))*50)
    return round(s,2)

# ─── BREAKOUT DETECTION ─────────────────────────────────────────────
def detect_breakout(ha_df, lb=BREAKOUT_LOOKBACK):
    n = min(lb, len(ha_df)-1)
    if n < 5: return -1, False, False, False, "Insufficient Data"
    lat = ha_df.iloc[-1]
    c1 = lat["HA_C"] > lat["E20"]
    c2 = lat["HA_C"] > lat["S50"]
    c3 = lat["E20"]  > lat["S50"]
    ds = 0
    for i in range(n):
        r = ha_df.iloc[-1-i]
        if r["HA_C"] > r["E20"] and r["HA_C"] > r["S50"] and r["E20"] > r["S50"]:
            ds += 1
        else: break
    if c1 and c2 and c3 and ds >= 1:
        st = "Fresh Breakout" if ds <= 3 else ("Strong Momentum" if ds <= 10 else "Already Rallied")
    else: st = "Inactive"
    return ds, bool(c1), bool(c2), bool(c3), st

def get_nm_info(ha_df, e20, s50, th=NEAR_MISS_PCT):
    lat = ha_df.iloc[-1]; hc = lat["HA_C"]
    c1 = hc > e20; c2 = hc > s50; c3 = e20 > s50
    cm = sum([c1,c2,c3])
    if cm == 3: return "Full Qualify", 0.
    miss = []; pa = 999.
    if not c1: p=dist(e20,hc); miss.append(f"HA<E20({abs(p):.1f}%)"); pa=min(pa,abs(p))
    if not c2: p=dist(s50,hc); miss.append(f"HA<S50({abs(p):.1f}%)"); pa=min(pa,abs(p))
    if not c3: p=dist(s50,e20); miss.append(f"E20<S50({abs(p):.1f}%)"); pa=min(pa,abs(p))
    if cm==2 and pa<=th: return f"Near Miss ({', '.join(miss)})", pa
    elif cm>=1 and pa<=th*2: return f"About to Cross ({', '.join(miss)})", pa
    else: return f"Not Ready ({', '.join(miss)})", pa

# ─── TV-STYLE HELPER FUNCTIONS ─────────────────────────────────────

def daily_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR from daily OHLC DataFrame. Returns last ATR value."""
    if len(df) < period + 1:
        return 0.0
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close),
                               np.abs(low - prev_close)))
    # Wilder smoothing
    atr_vals = np.zeros_like(tr)
    atr_vals[period] = np.mean(tr[1:period+1])
    for i in range(period + 1, len(tr)):
        atr_vals[i] = (atr_vals[i-1] * (period - 1) + tr[i]) / period
    return float(atr_vals[-1]) if atr_vals[-1] > 0 else float(np.mean(tr[-period:]))


def adx_dmi(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14, smoothing: int = 14) -> tuple:
    """Compute ADX, DI+, DI- from high/low/close series."""
    if len(high) < period + smoothing + 5:
        return 0.0, 0.0, 0.0

    high_a = high.values
    low_a = low.values
    close_a = close.values

    up_move = np.diff(high_a, prepend=high_a[0])
    down_move = np.diff(low_a, prepend=low_a[0]) * -1

    # +DM and -DM
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # True Range
    prev_close = np.roll(close_a, 1)
    prev_close[0] = close_a[0]
    tr = np.maximum(high_a - low_a,
                    np.maximum(np.abs(high_a - prev_close),
                               np.abs(low_a - prev_close)))

    # Wilder smooth
    def wilder_smooth(arr, p):
        out = np.zeros_like(arr)
        out[p] = np.mean(arr[1:p+1])
        for i in range(p + 1, len(arr)):
            out[i] = (out[i-1] * (p - 1) + arr[i]) / p
        return out

    s_plus_dm = wilder_smooth(plus_dm, period)
    s_minus_dm = wilder_smooth(minus_dm, period)
    s_tr = wilder_smooth(tr, period)

    di_plus = 100.0 * s_plus_dm / np.where(s_tr > 0, s_tr, 1.0)
    di_minus = 100.0 * s_minus_dm / np.where(s_tr > 0, s_tr, 1.0)

    dx = 100.0 * np.abs(di_plus - di_minus) / np.where((di_plus + di_minus) > 0, di_plus + di_minus, 1.0)
    adx_vals = wilder_smooth(dx, smoothing)

    return float(adx_vals[-1]), float(di_plus[-1]), float(di_minus[-1])


def compute_daily_levels(symbol: str) -> dict | None:
    """Fetch yesterday's daily OHLC and compute pivot/ATR structural levels."""
    try:
        end = datetime.now()
        start = end - timedelta(days=45)
        df = yf.download(symbol, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"),
                         interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 16:
            return None

        # Handle MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            cols = df.columns.get_level_values(0).unique()
            if len(cols) >= 4:
                # Flatten: take first ticker
                ticker = df.columns.get_level_values(1).unique()[0] if len(df.columns.get_level_values(1).unique()) > 0 else cols[0]
                if ticker in df.columns.get_level_values(1).unique():
                    df = df.xs(ticker, axis=1, level=1).copy()
                else:
                    df = df.xs(cols[0], axis=1, level=0).copy()

        # Get yesterday's data (day before last)
        if len(df) >= 2:
            prev = df.iloc[-2]
        else:
            prev = df.iloc[-1]

        prev_high = float(prev["High"]) if "High" in prev else float(prev["High"])
        prev_low = float(prev["Low"]) if "Low" in prev else float(prev["Low"])
        prev_close = float(prev["Close"]) if "Close" in prev else float(prev[3])

        pivot = (prev_high + prev_low + prev_close) / 3.0
        atr_val = daily_atr(df)

        return {
            "pivot": pivot,
            "daily_atr": atr_val,
            "sell_reversal": pivot + atr_val * SELL_REV_MULT,
            "buy_reversal": pivot - atr_val * BUY_REV_MULT,
            "breakout": pivot + atr_val * BREAKOUT_MULT,
            "breakdown": pivot - atr_val * BREAKDOWN_MULT,
        }
    except Exception as e:
        return None


# ─── DATA DOWNLOAD ───────────────────────────────────────────────────
def download_data(symbols):
    stock_data = {}
    failed = []
    bs = 50
    nr = pd.Series(dtype=float)
    try:
        nd = yf.download(NIFTY50_SYMBOL, period="6mo", interval="1d",
                         progress=False, auto_adjust=True)
        if not nd.empty:
            cs = nd.xs("Close",axis=1,level=0).iloc[:,0] if isinstance(nd.columns,pd.MultiIndex) else nd["Close"]
            nr = cs.pct_change().dropna()
    except: pass
    for i in range(0,len(symbols),bs):
        batch = symbols[i:i+bs]
        try:
            data = yf.download(batch, period="6mo", interval="1d",
                              progress=False, auto_adjust=True, group_by="ticker")
            for sym in batch:
                try:
                    sd = None
                    if isinstance(data.columns, pd.MultiIndex):
                        for lv in [0,1]:
                            if sym in data.columns.get_level_values(lv).unique():
                                sd = data.xs(sym,axis=1,level=lv).dropna().copy(); break
                    elif not data.empty: sd = data.dropna().copy()
                    if sd is not None and len(sd) > SMA_PERIOD + 10:
                        stock_data[sym] = sd
                    else: failed.append((sym, "Insufficient data" if sd is not None else "No data"))
                except Exception as e: failed.append((sym, str(e)))
        except Exception as e:
            for sym in batch: failed.append((sym, str(e)))
    return stock_data, failed, nr

# ─── PROCESS STOCK (Daily) ──────────────────────────────────────────
def process_stock(sym, df, nr, use_rsi, rsi_min, rsi_max, mm, mv, early):
    """Screen a single stock on daily data and compute BUY/SELL signals."""
    base = strip_ns(sym)
    sector = get_sector(sym)
    is_nifty = (sym == NIFTY_SPOT)
    
    try:
        ha = heiken_ashi(df)
        ha["E20"] = ema(ha["HA_C"], EMA_PERIOD)
        ha["S50"] = sma(ha["HA_C"], SMA_PERIOD)
        ha["RSI"] = rsi(ha["HA_C"], RSI_PERIOD)
        lat = ha.iloc[-1]
        prev = ha.iloc[-2] if len(ha) >= 2 else lat
        lc, hc, e20, s50, rv = lat["Close"], lat["HA_C"], lat["E20"], lat["S50"], lat["RSI"]
        ha_close = hc
        ha_prev = prev["HA_C"]
        if pd.isna(e20) or pd.isna(s50) or pd.isna(rv): return None
        
        # Stage / Trend (from breakout detection)
        ds, c1, c2, c3, stage = detect_breakout(ha)
        nmi, pa = get_nm_info(ha, e20, s50)
        qualifies = c1 and c2 and c3
        
        if not is_nifty:
            if early:
                cm = sum([c1, c2, c3])
                if not qualifies and cm < 2: return None
                if not qualifies and pa > NEAR_MISS_PCT: return None
            else:
                if not qualifies: return None
                if use_rsi and (rv < rsi_min or rv > rsi_max): return None
            # Stock-specific filters (skip for Nifty)
            av = df["Volume"].tail(VOLUME_LOOKBACK).mean()
            if av < mv: return None
            emc = (lc * av * VOLUME_LOOKBACK) / 1e7
            if mm > 0 and emc < mm: return None
        # Nifty: no volume/mcap filters, only structural
            
        trend = "Bullish" if qualifies else ("Near Miss" if sum([c1,c2,c3])>=2 else "Building")
        
        # ─── TV-Style Signal Generation (Daily) ────────────────────
        # ADX/DMI on daily data
        adx_val, di_plus, di_minus = adx_dmi(df["High"], df["Low"], df["Close"])
        
        # Daily structural levels
        levels = compute_daily_levels(sym)
        
        signal = "NEUTRAL"
        detail_parts = []
        
        if levels:
            buy_rev = levels["buy_reversal"]
            sell_rev = levels["sell_reversal"]
            brkout = levels["breakout"]
            brkdown = levels["breakdown"]
            pivot = levels["pivot"]
            daily_atr_val = levels["daily_atr"]
            
            # Trend conditions
            bull_trend = (
                ha_close > e20 and
                di_plus > di_minus and
                adx_val > ADX_THRESHOLD and
                rv < RSI_EXTREME_LONG
            )
            bear_trend = (
                ha_close < e20 and
                di_minus > di_plus and
                adx_val > ADX_THRESHOLD and
                rv > RSI_EXTREME_SHORT
            )
            
            # Buy Reversal
            if ha_close <= buy_rev and bull_trend:
                signal = "BUY-R"
                detail_parts.append(f"Daily Reversal touch {buy_rev:.2f}")
                detail_parts.append(f"ADX {adx_val:.1f} DI+ {di_plus:.1f}")
            
            # Buy Breakout
            if ha_close > brkout and ha_prev <= brkout and bull_trend and signal == "NEUTRAL":
                signal = "BUY-B"
                detail_parts.append(f"Daily Breakout above {brkout:.2f}")
                detail_parts.append(f"ADX {adx_val:.1f} DI+ {di_plus:.1f}")
            
            # Sell Reversal
            if ha_close >= sell_rev and bear_trend and signal == "NEUTRAL":
                signal = "SELL-R"
                detail_parts.append(f"Daily Reversal touch {sell_rev:.2f}")
                detail_parts.append(f"ADX {adx_val:.1f} DI- {di_minus:.1f}")
            
            # Sell Breakdown
            if ha_close < brkdown and ha_prev >= brkdown and bear_trend and signal == "NEUTRAL":
                signal = "SELL-B"
                detail_parts.append(f"Daily Breakdown below {brkdown:.2f}")
                detail_parts.append(f"ADX {adx_val:.1f} DI- {di_minus:.1f}")
            
            if not detail_parts:
                if bull_trend:
                    detail_parts.append(f"Bullish ADX {adx_val:.1f} no level touch")
                elif bear_trend:
                    detail_parts.append(f"Bearish ADX {adx_val:.1f} no level touch")
                else:
                    detail_parts.append(f"ADX {adx_val:.1f} no clear trend")
            
            level_str = (f"P:{pivot:.0f} BR:{buy_rev:.0f} SR:{sell_rev:.0f} "
                         f"BO:{brkout:.0f} BD:{brkdown:.0f} ATR:{daily_atr_val:.1f}")
        else:
            detail_parts.append("No daily levels")
            level_str = "-"
        
        # Build entry/stop/rr for bullish stocks
        if qualifies:
            hh = hh_hl(ha, PRICE_LOOKBACK)
            lw = low_wick(ha)
            vs, vr = vol_spike(df["Volume"], VOLUME_LOOKBACK)
            sr = df["Close"].pct_change().dropna()
            rs = rel_strength(sr, nr)
            ez = est_entry(df, e20) if not is_nifty else "-"
            sl = est_stop(df, s50, e20) if not is_nifty else "-"
            rr_text, _ = est_rr(ez, sl) if not is_nifty else ("1:3", 0)
        else:
            hh, lw, vs, vr, rs = False, False, "No", 1.0, 0
            ez, sl, rr_text = "-", "-", "N/A"
        
        return {
            "Rank": 0, "Symbol": base, "Sector": sector,
            "Price": round(lc, 2),
            "Mcap_Cr": round(emc, 2) if not is_nifty else 0,
            "Avg_Vol": int(av) if not is_nifty else 0,
            "EMA20": round(e20, 2), "SMA50": round(s50, 2),
            "D_E20": round(dist(lc, e20), 2), "D_S50": round(dist(lc, s50), 2),
            "RS": round(rs, 2), "RSI": round(rv, 2),
            "V_Spike": "Yes" if vs else "No", "V_Ratio": round(vr, 2),
            "HH_HL": hh, "L_Wick": lw,
            "C1": "Yes" if c1 else "No", "C2": "Yes" if c2 else "No", "C3": "Yes" if c3 else "No",
            "Days_Since": ds, "Stage": stage, "Near_Miss": nmi,
            "Trend": trend,
            "Entry": ez, "Stop": sl, "R:R": rr_text,
            "1H_Setup": signal, "1H_Detail": " | ".join(detail_parts), "1H_Zone": level_str,
        }
    except Exception:
        return None

# ─── MAIN SCANNER ────────────────────────────────────────────────────
def run_scanner(symbols=None, output_dir=".", use_rsi=USE_RSI_FILTER,
                rsi_min=RSI_MIN, rsi_max=RSI_MAX,
                min_mcap=MIN_MARKET_CAP_CR, min_vol=MIN_AVG_VOLUME,
                early_mode=False):
    if symbols is None: symbols = NSE_SYMBOLS
    dt = datetime.now()
    mode = "EARLY BREAKOUT" if early_mode else "STANDARD"
    print("="*70)
    print(f"  NSE SWING SCANNER — {mode} — {dt.strftime('%Y-%m-%d %H:%M')} IST")
    print(f"  Signal type: Daily TV-Style (BUY-R/BUY-B/SELL-R/SELL-B)")
    print("="*70)

    # Step 1: Download daily data (include Nifty 50 index)
    if symbols is not None:
        symbols_list = list(symbols) if hasattr(symbols, '__iter__') else list(symbols)
    else:
        symbols_list = list(NSE_SYMBOLS)
    if NIFTY_SPOT not in symbols_list:
        symbols_list.append(NIFTY_SPOT)
    print(f"\n[1/3] Downloading {len(symbols_list)} stocks + Nifty50 (Daily)...")
    stock_data, failed, nr = download_data(symbols_list)
    print(f"  Loaded: {len(stock_data)}, Failed: {len(failed)}")

    # Step 2: Screen with Daily TV-style signals
    print(f"\n[2/3] Screening with Daily TV-style signals...")
    results = []
    for sym, df in stock_data.items():
        r = process_stock(sym, df, nr, use_rsi, rsi_min, rsi_max,
                          min_mcap, min_vol, early_mode)
        if r:
            results.append(r)
    print(f"  Stocks with signals: {len(results)}")

    # Step 3: Rank & Export
    print(f"\n[3/3] Ranking & Exporting...")
    if not results:
        print("  No stocks passed filters.")
        return pd.DataFrame()

    df_out = pd.DataFrame(results)
    df_out["Rank"] = df_out.apply(calc_priority, axis=1)
    df_out = df_out.sort_values("Rank", ascending=False).reset_index(drop=True)
    df_out.insert(0, "#", range(1, len(df_out)+1))

    # Build column list
    cols = ["#","Rank","Symbol","Sector","Price","Mcap_Cr","Avg_Vol",
            "EMA20","SMA50","D_E20","D_S50","RS","RSI",
            "V_Spike","V_Ratio","HH_HL","L_Wick",
            "C1","C2","C3","Days_Since","Stage","Near_Miss","Trend",
            "1H_Setup","1H_Detail","1H_Zone",
            "Entry","Stop","R:R"]
    df_out = df_out[[c for c in cols if c in df_out.columns]]

    # Export
    ds = dt.strftime("%Y-%m-%d")
    tag = "early" if early_mode else "swing"
    csv_path = os.path.join(output_dir, f"watchlist_{tag}_{ds}.csv")
    xlsx_path = os.path.join(output_dir, f"watchlist_{tag}_{ds}.xlsx")

    # Also save with old naming for backward compatibility
    old_csv_path = os.path.join(output_dir, f"swing_watchlist_{ds}.csv")
    try:
        df_out.to_csv(old_csv_path, index=False)
    except Exception:
        pass

    df_out.to_csv(csv_path, index=False)
    print(f"  ✅ CSV: {csv_path}")

    # Excel with 4 sheets
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
            df_out.to_excel(w, sheet_name="Watchlist", index=False)
            df_out.head(20).to_excel(w, sheet_name="Top_20", index=False)

            # Sheet 3: Pivot by Entry Quality
            if "1H_Setup" in df_out.columns:
                quality_order = ["BUY-R", "BUY-B", "SELL-R", "SELL-B", "NEUTRAL", "NO DATA"]
                df_pivot = df_out.copy()
                df_pivot["Quality"] = pd.Categorical(
                    df_pivot["1H_Setup"], categories=quality_order, ordered=True)
                pivot_cols = ["#","Quality","1H_Detail","1H_Zone","Symbol","Sector",
                              "Price","D_E20","Stage","Trend","Entry","Stop","R:R"]
                pivot_cols = [c for c in pivot_cols if c in df_pivot.columns]
                df_pivot = df_pivot.sort_values(["Quality","Rank"]).reset_index(drop=True)
                df_pivot.insert(0, "Q#", range(1, len(df_pivot)+1))
                df_pivot.to_excel(w, sheet_name="By_Entry_Quality", index=False)

            # Sheet 4: Fresh Breakouts & Near Misses
            if "Stage" in df_out.columns:
                fresh = df_out[df_out["Stage"].isin(["Fresh Breakout","Strong Momentum"])]
                if "Trend" in df_out.columns:
                    near = df_out[df_out["Trend"] == "Near Miss"]
                    combined = pd.concat([fresh, near]).drop_duplicates()
                else:
                    combined = fresh
                if not combined.empty:
                    combined.to_excel(w, sheet_name="Fresh_Actionable", index=False)

        print(f"  ✅ XLSX: {xlsx_path} (4 sheets)")
    except Exception as e:
        print(f"  [!] Excel: {e}")

    # Summary
    total = len(df_out)
    buy_r = len(df_out[df_out["1H_Setup"]=="BUY-R"]) if "1H_Setup" in df_out.columns else 0
    buy_b = len(df_out[df_out["1H_Setup"]=="BUY-B"]) if "1H_Setup" in df_out.columns else 0
    sell_r = len(df_out[df_out["1H_Setup"]=="SELL-R"]) if "1H_Setup" in df_out.columns else 0
    sell_b = len(df_out[df_out["1H_Setup"]=="SELL-B"]) if "1H_Setup" in df_out.columns else 0
    neutral = len(df_out[df_out["1H_Setup"]=="NEUTRAL"]) if "1H_Setup" in df_out.columns else 0
    fresh = len(df_out[df_out["Stage"]=="Fresh Breakout"]) if "Stage" in df_out.columns else 0
    near = len(df_out[df_out["Trend"]=="Near Miss"]) if "Trend" in df_out.columns else 0

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total: {total}  |  Fresh Breakouts: {fresh}  |  Near Miss: {near}")
    print(f"  BUY-R: {buy_r} | BUY-B: {buy_b} | SELL-R: {sell_r} | SELL-B: {sell_b} | Neutral: {neutral}")
    print(f"{'='*70}")

    if not df_out.empty:
        print(f"\n  TOP 5:")
        print(f"  {'#':<4} {'Symbol':<14} {'Stage':<18} {'Price':<9} {'1H_Signal':<12} {'R:R':<10}")
        print(f"  {'-'*68}")
        for _, r in df_out.head(5).iterrows():
            s = r.get("Stage","-")
            h = r.get("1H_Setup","-")
            p = r.get("Price",0)
            rr = r.get("R:R","-")
            print(f"  {r.get('#',0):<4} {r['Symbol']:<14} {s:<18} ₹{p:<6.2f} {h:<12} {rr:<10}")

    print(f"\n  Files: {csv_path}")
    print()
    return df_out

# ─── CLI ─────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="NSE Swing Scanner — Daily TV-Style Signals")
    p.add_argument("-o","--output-dir",default=OUTPUT_DIR)
    p.add_argument("--no-rsi",action="store_true",help="Disable RSI filter")
    p.add_argument("--rsi-min",type=float,default=RSI_MIN)
    p.add_argument("--rsi-max",type=float,default=RSI_MAX)
    p.add_argument("--min-mcap",type=float,default=MIN_MARKET_CAP_CR)
    p.add_argument("--min-volume",type=int,default=MIN_AVG_VOLUME)
    p.add_argument("--symbols-file",type=str,help="File with NSE symbols")
    p.add_argument("--early",action="store_true",help="Early breakout mode")
    args = p.parse_args()

    syms = NSE_SYMBOLS
    if args.symbols_file and os.path.exists(args.symbols_file):
        with open(args.symbols_file) as f:
            syms = [s.strip().upper()+(".NS" if not s.strip().endswith(".NS") else "")
                    for s in f if s.strip() and not s.startswith("#")]

    run_scanner(syms, args.output_dir, not args.no_rsi,
                args.rsi_min, args.rsi_max, args.min_mcap,
                args.min_volume, args.early)

if __name__ == "__main__":
    main()