"""Generate NSE Swing Trade Strategy document."""
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import datetime

doc = Document()

# ─── Styles ────────────────────────────────────────────────────────
style = doc.styles['Normal']
font = style.font
font.name = 'Calibri'
font.size = Pt(11)

# ─── Title Page ─────────────────────────────────────────────────────
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('\n\n\n\n')
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('NSE Swing Trade Scanner')
run.bold = True
run.font.size = Pt(28)
run.font.color.rgb = RGBColor(0, 0xd4, 0xaa)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('Complete Trading Strategy Document')
run.font.size = Pt(16)
run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run(f'\nVersion 1.1 — {datetime.date.today().strftime("%B %d, %Y")}\n\nNifty500 Universe | Heiken-Ashi Breakout | 1H TV-Style Entry\n₹1.5L/Trade | 5% SL | 10% Target')
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

doc.add_page_break()

# ─── Table of Contents (manual) ─────────────────────────────────────
doc.add_heading('Table of Contents', level=1)
toc_items = [
    '1. Overview',
    '2. Scan Universe — Nifty500',
    '3. Daily Technical Screening',
    '4. 1-Hour TV-Style Entry Analysis',
    '5. Signal Types',
    '6. Position Creation & Entry',
    '7. Risk Management',
    '8. Intraday Scan Schedule',
    '9. Dashboard & Monitoring',
    '10. Performance Reporting',
    'Appendix: Key Code Parameters',
]
for item in toc_items:
    p = doc.add_paragraph(item, style='List Number')
    p.paragraph_format.space_after = Pt(2)

doc.add_page_break()

# ─── Section 1: Overview ───────────────────────────────────────────
doc.add_heading('1. Overview', level=1)
doc.add_paragraph(
    'The NSE Swing Trade Scanner is an automated system that scans the Nifty500 universe '
    'daily to identify swing trading opportunities. It uses a two-pass approach:'
)

passes = [
    ('Pass 1 — Daily Screening', 
     'Downloads 6 months of daily OHLC data. Applies Heiken-Ashi smoothing, EMA20/SMA50 '
     'crossover logic, volume filters, market cap filter, and RSI filter. Only stocks '
     'passing all criteria proceed to Pass 2.'),
    ('Pass 2 — 1H Entry Analysis', 
     'Downloads 10 days of 1-hour data for qualifying stocks. Computes ADX/DMI for trend '
     'strength, pivot/ATR structural levels, and generates entry signals: BUY-R, BUY-B, '
     'SELL-R, SELL-B, or NEUTRAL.'),
    ('Position Creation',
     'BUY-R and BUY-B signals automatically create trade positions with ₹1.5L capital, '
     '5% stop-loss, and 10% profit target. Same-day entry during market hours via '
     'intraday scans; next-day open entry for end-of-day scans.'),
]
for title, desc in passes:
    p = doc.add_paragraph()
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(desc)

doc.add_paragraph(
    '\nAll positions are monitored every 15 minutes for stop-loss and target hits. '
    'A web dashboard and performance report provide real-time visibility into '
    'scan results, active positions, and portfolio P&L.'
)

# ─── Section 2: Scan Universe ───────────────────────────────────────
doc.add_heading('2. Scan Universe — Nifty500', level=1)
doc.add_paragraph(
    'The scanner covers the Nifty500 universe — the top 500 companies listed on the '
    'National Stock Exchange of India by market capitalization. This covers approximately '
    '90% of the total market capitalization of NSE.'
)
doc.add_heading('Symbol Sources', level=2)
doc.add_paragraph(
    'Primary: NSE India API (https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500) '
    '— fetches live Nifty500 constituents with session-based authentication.'
)
doc.add_paragraph(
    'Fallback: A comprehensive static list of ~370 highly liquid stocks covering:'
)
bullets = [
    'Nifty 50 — 50 largest stocks',
    'Nifty Next 50 — 50 next largest',
    'Nifty Midcap 100 — 100 liquid mid-cap stocks',
    'Additional liquid stocks for broad coverage'
]
for b in bullets:
    doc.add_paragraph(b, style='List Bullet')

doc.add_paragraph(
    'The total scanned count is displayed on the dashboard as "📡 Scanned" so you always '
    'know how many stocks were analyzed vs how many passed filters.'
)

# ─── Section 3: Daily Technical Screening ──────────────────────────
doc.add_heading('3. Daily Technical Screening', level=1)
doc.add_paragraph(
    'Each stock in the universe is evaluated using daily timeframe data (6 months). '
    'The screening process follows multiple technical filters:'
)

doc.add_heading('3.1 Heiken-Ashi Smoothing', level=2)
doc.add_paragraph(
    'Raw OHLC data is converted to Heiken-Ashi (HA) candles, which filter out market noise '
    'by using the formula:\n'
    '• HA_Close = (Open + High + Low + Close) / 4\n'
    '• HA_Open = (Previous HA_Open + Previous HA_Close) / 2\n'
    '• HA_High = max(High, HA_Open, HA_Close)\n'
    '• HA_Low = min(Low, HA_Open, HA_Close)'
)

doc.add_heading('3.2 Breakout Detection', level=2)
doc.add_paragraph(
    'Three conditions must be met (the "3C" rule):\n'
    '• C1: HA_Close > EMA20 (Heiken-Ashi Close above 20-period Exponential Moving Average)\n'
    '• C2: HA_Close > SMA50 (Heiken-Ashi Close above 50-period Simple Moving Average)\n'
    '• C3: EMA20 > SMA50 (Golden Crossover — short-term above long-term)\n\n'
    'If all three are true and persist for 1+ days, the stock is classified as a "Fresh Breakout" '
    '(1-3 days), "Strong Momentum" (4-10 days), or "Already Rallied" (10+ days).'
)

doc.add_heading('3.3 Volume Filter', level=2)
doc.add_paragraph(
    '• Minimum average volume: 500,000 shares over 20-day lookback\n'
    '• Volume spike detection: compares latest volume to 20-day average\n'
    '• Volume spike confirmation added as a positive factor'
)

doc.add_heading('3.4 Market Cap Filter', level=2)
doc.add_paragraph(
    '• Minimum market cap: ₹5,000 Crores\n'
    '• Estimated from: (Price × Average Volume × 20) / 10,000,000\n'
    '• Ensures only liquid, institutional-grade stocks are traded'
)

doc.add_heading('3.5 RSI Filter', level=2)
doc.add_paragraph(
    '• RSI period: 14\n'
    '• Range: 40-70 (disabled for manual scans via dashboard, enabled for CLI)\n'
    '• Prevents buying overbought stocks (RSI > 70) or weak stocks (RSI < 40)'
)

doc.add_heading('3.6 Relative Strength', level=2)
doc.add_paragraph(
    '• Compares stock performance to Nifty 50 over 63 trading days\n'
    '• Scored 0-100; higher is better\n'
    '• Used in priority ranking for final sorting'
)

doc.add_heading('3.7 Structure Confirmation', level=2)
doc.add_paragraph(
    '• Higher-High / Higher-Low (HH/HL): Confirms uptrend structure over 20 days\n'
    '• Low Wick: Identifies buying pressure (lower wick < 30% of candle range)\n'
    '• Both add bonus points to the priority score'
)

# ─── Section 4: 1-Hour TV-Style Analysis ──────────────────────────
doc.add_heading('4. 1-Hour TV-Style Entry Analysis', level=1)
doc.add_paragraph(
    'Stocks that pass the daily screening proceed to 1-hour analysis. This uses '
    'TradingView-inspired logic with pivot-based structural levels and ADX/DMI trend detection.'
)

doc.add_heading('4.1 Data & Indicators', level=2)
doc.add_paragraph(
    '• 10 days of 1-hour data downloaded for each qualifying stock\n'
    '• Heiken-Ashi applied to 1H data for smoothing\n'
    '• EMA20 on 1H HA Close\n'
    '• RSI(14) on 1H HA Close\n'
    '• ADX(14) and DMI(14) with Wilder smoothing'
)

doc.add_heading('4.2 Daily Structural Levels', level=2)
doc.add_paragraph(
    'Using the previous day\'s OHLC data, the following levels are computed:\n'
    '• Pivot = (High + Low + Close) / 3\n'
    '• Daily ATR = Average True Range (14-period Wilder smoothed)\n'
    '• Buy Reversal = Pivot - (ATR × 0.21)\n'
    '• Sell Reversal = Pivot + (ATR × 0.29)\n'
    '• Breakout = Pivot + (ATR × 0.54)\n'
    '• Breakdown = Pivot - (ATR × 0.46)'
)

doc.add_heading('4.3 Signal Logic', level=2)
p = doc.add_paragraph()
run = p.add_run('Bullish Trend Condition: ')
run.bold = True
p.add_run('1H HA_Close > 1H EMA20 AND DI+ > DI- AND ADX > 20 AND RSI < 80')

p = doc.add_paragraph()
run = p.add_run('Bearish Trend Condition: ')
run.bold = True
p.add_run('1H HA_Close < 1H EMA20 AND DI- > DI+ AND ADX > 20 AND RSI > 20')

signals = [
    ('BUY-R (Buy Reversal)', 'HA_Close touches/breaks below Buy Reversal level + Bullish Trend'),
    ('BUY-B (Buy Breakout)', 'HA_Close crosses above Breakout level + Bullish Trend'),
    ('SELL-R (Sell Reversal)', 'HA_Close touches/breaks above Sell Reversal level + Bearish Trend'),
    ('SELL-B (Sell Breakdown)', 'HA_Close crosses below Breakdown level + Bearish Trend'),
    ('NEUTRAL', 'No signal conditions met; may still note ADX/DMI state for reference'),
]
for sig, desc in signals:
    p = doc.add_paragraph()
    run = p.add_run(f'{sig}: ')
    run.bold = True
    p.add_run(desc)

# ─── Section 5: Signal Types ───────────────────────────────────────
doc.add_heading('5. Signal Types & Action', level=1)

table = doc.add_table(rows=5, cols=4)
table.style = 'Light Grid Accent 1'
table.alignment = WD_TABLE_ALIGNMENT.CENTER

headers = ['Signal', 'Full Name', 'Auto-Trade', 'Action']
for i, h in enumerate(headers):
    cell = table.rows[0].cells[i]
    cell.text = h
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

data = [
    ['BUY-R', 'Buy Reversal', '✅ Yes', 'Buy at signal price (or next open) with 5% SL, 10% Target'],
    ['BUY-B', 'Buy Breakout', '✅ Yes', 'Buy at signal price (or next open) with 5% SL, 10% Target'],
    ['SELL-R', 'Sell Reversal', '❌ No', 'Listed on dashboard for manual FUT short reference'],
    ['SELL-B', 'Sell Breakdown', '❌ No', 'Listed on dashboard for manual FUT short reference'],
]
for row_idx, row_data in enumerate(data):
    for col_idx, val in enumerate(row_data):
        table.rows[row_idx + 1].cells[col_idx].text = val

# ─── Section 6: Position Creation ──────────────────────────────────
doc.add_heading('6. Position Creation & Entry', level=1)

doc.add_heading('6.1 Same-Day Entry (Intraday Scan)', level=2)
doc.add_paragraph(
    'When a BUY signal is detected during an intraday scan (9:45 AM, 11:00 AM, 1:00 PM, 2:30 PM):\n'
    '• Position is created immediately at the current market price\n'
    '• Status is set to "Active" (no pending wait)\n'
    '• Stop-loss (5%) and Target (10%) are calculated from entry price\n'
    '• Quantity = ₹1,50,000 / entry price\n'
    '• Position enters monitoring immediately'
)

doc.add_heading('6.2 Next-Day Entry (EOD Scan)', level=2)
doc.add_paragraph(
    'When a BUY signal is detected in the end-of-day scan (after 3:30 PM):\n'
    '• Position is created as "Pending Entry"\n'
    '• At next market open (9:30 AM), entry price is fetched as the open price\n'
    '• SL, Target, and Quantity are calculated at that time\n'
    '• Position becomes "Active" and enters monitoring'
)

doc.add_heading('6.3 Position Parameters', level=2)

params = [
    ('Capital per trade', '₹1,50,000'),
    ('Stop-Loss', '5% below entry price'),
    ('Profit Target', '10% above entry price'),
    ('Risk:Reward', '1:2'),
    ('Position Sizing', 'Capital ÷ Entry Price = Quantity (rounded down)'),
]
p = doc.add_paragraph()
for param, val in params:
    doc.add_paragraph(f'{param}: {val}', style='List Bullet')

# ─── Section 7: Risk Management ─────────────────────────────────────
doc.add_heading('7. Risk Management', level=1)
doc.add_paragraph(
    'The risk management framework is designed for consistent, disciplined swing trading:'
)
doc.add_paragraph('Capital Allocation: ₹1.5 Lakh per position, ensuring no single trade overwhelms the portfolio.', style='List Bullet')
doc.add_paragraph('Stop-Loss: 5% fixed stop-loss. When current price <= stop-loss level, position is automatically closed.', style='List Bullet')
doc.add_paragraph('Profit Target: 10% fixed profit target. When current price >= target, position is automatically closed.', style='List Bullet')
doc.add_paragraph('Position Monitoring: Every 15 minutes during market hours via APScheduler.', style='List Bullet')
doc.add_paragraph('Manual Refresh: "Refresh Prices" button on dashboard forces immediate price update.', style='List Bullet')
doc.add_paragraph('No Overnight Gap Risk: Entry happens at market open for EOD signals, so gap risk is minimized.', style='List Bullet')

# ─── Section 8: Intraday Scan Schedule ─────────────────────────────
doc.add_heading('8. Intraday Scan Schedule', level=1)
doc.add_paragraph(
    'To ensure BUY signals are captured and acted upon the same day they occur, '
    'the scheduler runs 1H analysis at four intervals during market hours:'
)

table2 = doc.add_table(rows=5, cols=3)
table2.style = 'Light Grid Accent 1'
table2.alignment = WD_TABLE_ALIGNMENT.CENTER

headers2 = ['Time (IST)', 'Scan Type', 'Purpose']
for i, h in enumerate(headers2):
    cell = table2.rows[0].cells[i]
    cell.text = h
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

schedule = [
    ['9:45 AM', '1H Re-Analysis', 'Catches early morning breakouts (9:15-9:45 AM)'],
    ['11:00 AM', '1H Re-Analysis', 'Catches late morning signals'],
    ['1:00 PM', '1H Re-Analysis', 'Catches early afternoon signals'],
    ['2:30 PM', '1H Re-Analysis', 'Last chance before end-of-day'],
]
for row_idx, row_data in enumerate(schedule):
    for col_idx, val in enumerate(row_data):
        table2.rows[row_idx + 1].cells[col_idx].text = val

doc.add_paragraph(
    '\nIn addition, a full EOD scan (370 stocks, daily + 1H) runs when:\n'
    '• You manually click "Run Scan" on the dashboard\n'
    '• The daily scheduled scan at 3:30 PM (if implemented)\n\n'
    'Trade position monitoring (SL/Target checks) runs every 15 minutes during market hours.'
)

# ─── Section 9: Dashboard ──────────────────────────────────────────
doc.add_heading('9. Dashboard & Monitoring', level=1)
doc.add_paragraph(
    'The web dashboard provides real-time visibility into scan results and trade performance. '
    'It is built as a FastAPI backend with an HTML/CSS/JS frontend, deployable on Render.'
)

doc.add_heading('9.1 Dashboard Sections', level=2)
doc.add_paragraph('Watchlist Tab:', style='List Bullet')
sections = [
    'Summary Card: Shows 📡 Scanned (universe size), 🎯 Qualified (passed filters), 🔍 Filtered Out, plus Fresh Breakout, BUY NOW, and WAIT counts',
    'Watchlist Table: Symbol, Sector, Price, Stage, 1H Setup, 1H Detail, D_E20 (distance from EMA20), R:R ratio',
    'Filters: All, BUY-R, BUY-B, SELL-R, SELL-B, Fresh Breakout',
    'Scan Progress Bar: Shows real-time progress during a full scan',
    'Download Excel: Export latest results as XLSX',
]
doc.add_paragraph('Performance Report Tab:', style='List Bullet')
sections2 = [
    'Portfolio Summary: Total Signals, Active, Pending, Closed, Win Rate',
    'P&L Details: Total Invested, Current Value, Net P&L (₹), Return %',
    'Open Positions Table: Symbol, Sector, Signal Date, Entry, Current, P&L, Status, SL/Target',
    'Per-Symbol Performance: Signal count, wins, losses, win rate per stock',
    'Refresh Button: Force-update all prices manually',
]
for s in sections + sections2:
    doc.add_paragraph(s, style='List Bullet 2')

# ─── Section 10: Performance Reporting ─────────────────────────────
doc.add_heading('10. Performance Reporting', level=1)
doc.add_paragraph(
    'The system maintains a complete trade history in trades_history.json with:'
)
doc.add_paragraph('Portfolio-level aggregation: total invested, current value, net P&L, return percentage, win rate', style='List Bullet')
doc.add_paragraph('Per-position tracking: entry price, quantity, SL, target, current price, P&L', style='List Bullet')
doc.add_paragraph('Per-symbol statistics: total signals, active, closed wins/losses, win rate, total P&L', style='List Bullet')
doc.add_paragraph('Automatic position closure when SL or Target is hit', style='List Bullet')
doc.add_paragraph('Data persists across server restarts via JSON file storage', style='List Bullet')

# ─── Appendix ───────────────────────────────────────────────────────
doc.add_heading('Appendix: Key Code Parameters', level=1)
doc.add_paragraph('Configuration values used in the scanner:')

table3 = doc.add_table(rows=18, cols=2)
table3.style = 'Light Grid Accent 1'
table3.alignment = WD_TABLE_ALIGNMENT.CENTER

for i, h in enumerate(['Parameter', 'Value']):
    cell = table3.rows[0].cells[i]
    cell.text = h
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

params_list = [
    ('Universe Size', '~370 Nifty500 stocks'),
    ('Daily Data Period', '6 months'),
    ('1H Data Period', '10 days'),
    ('EMA Period', '20'),
    ('SMA Period', '50'),
    ('RSI Period', '14'),
    ('Volume Lookback', '20 days'),
    ('Min Market Cap', '₹5,000 Cr'),
    ('Min Avg Volume', '500,000 shares'),
    ('ADX Period', '14'),
    ('ADX Threshold', '20'),
    ('Breakout Lookback', '30 days'),
    ('Capital per Trade', '₹1,50,000'),
    ('Stop-Loss %', '5%'),
    ('Profit Target %', '10%'),
    ('Parallel Workers (1H)', '10'),
    ('Intraday Scan Times', '9:45, 11:00, 13:00, 14:30 IST'),
]
for row_idx, (param, val) in enumerate(params_list):
    table3.rows[row_idx + 1].cells[0].text = param
    table3.rows[row_idx + 1].cells[1].text = val

# ─── Save ───────────────────────────────────────────────────────────
filename = 'NSE_Swing_Trade_Strategy.docx'
doc.save(filename)
print(f'✅ Document saved: {filename}')
print(f'Location: {__file__}')