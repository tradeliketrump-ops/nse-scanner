# VJs Structural Levels Pro V1 — Complete Documentation

## Overview

**VJs Structural Levels Pro V1** is a Pine Script indicator for TradingView that identifies high-probability intraday trade setups based on structural price levels derived from the previous day's price action. It combines daily pivot/ATR levels with Heikin Ashi smoothing, ADX/DMI trend filtering, and VWAP confirmation to generate actionable BUY and SELL signals across reversal and breakout/breakdown strategies.

The indicator is designed for **NSE cash market trading** and supports both **scalp** (ATR-based targets 1 & 2) and **positional** (fixed ₹ profit target) approaches within a single framework.

---

## Core Philosophy

The indicator operates on a **multi-timeframe confluence model**:

1. **Daily timeframe** establishes the structural framework — pivot point, ATR-based support/resistance levels, and the broader trend context.
2. **Intraday (current timeframe)** executes the entry logic using Heikin Ashi candles for noise reduction and ADX/DMI for trend strength validation.
3. **Signals are generated at the intersection of level-touch events and confirmed trend conditions.**

No single component drives the signal — success comes from the confluence of structural levels, trend filter, and volatility context working together.

---

## Section-by-Section Breakdown

### 1. Heikin Ashi Source (Lines 44-50)

```
haTicker = ticker.heikinashi(syminfo.tickerid)
haClose = request.security(haTicker, timeframe.period, close)
haHigh  = request.security(haTicker, timeframe.period, high)
haLow   = request.security(haTicker, timeframe.period, low)
```

**Purpose:** All level interactions and crossover logic use Heikin Ashi candles rather than raw price.

**Why HA?** Heikin Ashi filters out minor price noise and provides cleaner signals for level tests. A single HA candle closing above a resistance level carries more weight than a regular candle doing the same, because HA candles already account for the open/close relationship of the underlying period.

**Usage:** HA close is used for EMA calculations, SMA calculations, crossover detection, and level-touch checks throughout the indicator.

---

### 2. Previous Day Data & Pivot Calculation (Lines 52-65)

```
pdHigh  = request.security(syminfo.tickerid, "D", high[1], lookahead=barmerge.lookahead_on)
pdLow   = request.security(syminfo.tickerid, "D", low[1], lookahead=barmerge.lookahead_on)
pdClose = request.security(syminfo.tickerid, "D", close[1], lookahead=barmerge.lookahead_on)

pivot = (pdHigh + pdLow + pdClose) / 3

dailyATR = request.security(syminfo.tickerid, "D", ta.atr(14), lookahead=barmerge.lookahead_on)
```

**Why `[1]`?** All daily values use the **previous day's close** (`[1]`). This ensures no intraday lookahead — the levels are fixed for the entire trading day based on data available before the market opened.

**Pivot Formula:** `(Previous Day High + Previous Day Low + Previous Day Close) / 3`

This is the classic floor-trader pivot point. It represents the market's "fair price" from the prior session and acts as a magnetic level intraday.

**Daily ATR:** 14-period ATR computed on daily data, also using `[1]` to avoid any lookahead. This ATR value is the scaling factor for all structural levels.

---

### 3. Structural Levels (Lines 67-82)

```
sellRev  = pivot + dailyATR * sellRevATR      // pivot + ATR * 0.29
buyRev   = pivot - dailyATR * buyRevATR       // pivot - ATR * 0.21

breakout = pivot + dailyATR * breakoutATR     // pivot + ATR * 0.54
breakdown= pivot - dailyATR * breakdownATR    // pivot - ATR * 0.46

targetUp1 = breakout + dailyATR * target1ATR  // breakout + ATR * 0.28
targetUp2 = breakout + dailyATR * target2ATR  // breakout + ATR * 0.41

targetDn1 = breakdown - dailyATR * target1ATR // breakdown - ATR * 0.28
targetDn2 = breakdown - dailyATR * target2ATR // breakdown - ATR * 0.46
```

**Level Hierarchy (Top to Bottom):**

| Level | Multiplier | Purpose |
|-------|-----------|---------|
| Target Up 2 | Pivot + ATR × 0.82 | Scalp profit target (aggressive) |
| Target Up 1 | Pivot + ATR × 0.69 | Scalp profit target (conservative) |
| **Breakout** | **Pivot + ATR × 0.54** | **Bullish breakout trigger** |
| Sell Reversal | Pivot + ATR × 0.29 | Bearish reversal zone |
| **Pivot** | **(H+L+C)/3** | **Central reference / fair value** |
| Buy Reversal | Pivot - ATR × 0.21 | Bullish reversal zone |
| **Breakdown** | **Pivot - ATR × 0.46** | **Bearish breakdown trigger** |
| Target Down 1 | Breakdown - ATR × 0.28 | Scalp profit target (conservative) |
| Target Down 2 | Breakdown - ATR × 0.46 | Scalp profit target (aggressive) |

**Why these specific multipliers?** The multipliers (0.21, 0.29, 0.46, 0.54, 0.28, 0.41) are calibrated to capture the typical intraday extension ranges observed in NSE stocks. The asymmetry between bullish and bearish multipliers accounts for the natural drift tendency of equities.

---

### 4. Trend Filters (Lines 84-114)

#### EMA Cross (Fast / Slow)
```
ema5  = ta.ema(haClose, emaFastLen)    // Default: 5
ema20 = ta.ema(haClose, emaSlowLen)    // Default: 20
```
**Purpose:** Short-term trend direction. EMA5 above EMA20 = bullish bias in the current timeframe.

#### SMA 50
```
sma50 = ta.sma(haClose, smaLen)        // Default: 50
```
**Purpose:** Medium-term trend filter. Price above SMA50 indicates the broader intraday trend is up.

#### VWAP
```
vwapValue = ta.vwap(hlc3)
```
**Purpose:** Volume-weighted average price. Acts as an institutional fairness filter — institutional buyers tend to support prices above VWAP. The VWAP filter is optional via the `useVWAP` input.

#### ADX/DMI
```
[diplus, diminus, adx] = ta.dmi(adxLen, adxSmooth)
```
**Purpose:** Trend strength and direction.
- **ADX > 20:** Minimum trend strength required
- **DI+ > DI-:** Bullish directional pressure
- **DI- > DI+:** Bearish directional pressure

#### Complete Trend Conditions

**Bullish Trend (all must be true):**
```
bullTrend = ema5 > ema20 AND
            close > sma50 AND
            diplus > diminus AND
            adx > adxThresh AND
            bullVWAP (if enabled)
```

**Bearish Trend (all must be true):**
```
bearTrend = ema5 < ema20 AND
            close < sma50 AND
            diminus > diplus AND
            adx > adxThresh AND
            bearVWAP (if enabled)
```

**Key Design Decision:** All conditions must be true simultaneously. This prevents marginal setups from generating signals and ensures only high-confluence trades are considered.

---

### 5. Reversal Logic (Lines 116-200)

#### Touch Detection
```
buyTouch  = haClose > buyRev     // HA close crossed above buy reversal level
sellTouch = haClose < sellRev    // HA close crossed below sell reversal level
```

#### Signal Confirmation (BUY-R)

```
buyRevSignal = 
    rsi < 80 (RSI filter) AND
    haClose > buyRev (touch) AND
    bullTrend (all trend conditions met)
```

**BUY-R (Buy Reversal):** Triggered when Heikin Ashi close moves above the Buy Reversal level while the overall trend is bullish. This signals that a pullback to the reversal zone has found support, and price is resuming its uptrend. The RSI check (`rsi < 80`) prevents entering when the market is already overextended.

#### Signal Confirmation (SELL-R)

```
sellRevSignal =
    rsi > 20 (RSI filter) AND
    haClose < sellRev (touch) AND
    bearTrend (all trend conditions met)
```

**SELL-R (Sell Reversal):** Triggered when HA close moves below the Sell Reversal level while the trend is bearish. Price has rallied into the resistance zone and reversed back down. The RSI filter (`rsi > 20`) prevents selling when RSI is already deeply oversold.

**Wait confirmation variables** (`waitingBuyConfirm`, `waitingSellConfirm`) are present in the code but reserved for future use — currently signals fire immediately when conditions align.

---

### 6. Breakout / Breakdown Logic (Lines 202-211)

```
buyBreakoutSignal  = crossover(haClose, breakout) AND bullTrend
sellBreakdownSignal = crossunder(haClose, breakdown) AND bearTrend
```

**BUY-B (Buy Breakout):** HA close crosses **above** the Breakout level. This signals that price is breaking out of its expected daily range with strong bullish momentum. The `crossover()` function ensures this is a fresh breakout, not just price already above the level.

**SELL-B (Sell Breakdown):** HA close crosses **below** the Breakdown level. Signals that price is breaking down through support with strong bearish momentum.

**Why Breakout/Breakdown matters:** When a stock breaks beyond 0.54× daily ATR above pivot (or 0.46× below), it indicates the current day's momentum is stronger than average. This often leads to continuation moves.

---

### 7. One-Signal-Per-Trend Mechanism (Lines 213-240)

```
var int trendState = 0

finalBuyR = buyRevSignal and trendState != 1    // Only if not already in long
finalSellR = sellRevSignal and trendState != -1  // Only if not already in short

if finalBuyR or finalBuyB
    trendState := 1    // Lock into long mode
    // Calculate fixed ₹ target
    targetPoints = profitTargetRs / tradeQty
    longTargetPrice := close + targetPoints

if finalSellR or finalSellB
    trendState := -1   // Lock into short mode
    targetPoints = profitTargetRs / tradeQty
    shortTargetPrice := close - targetPoints
```

**Purpose:** Prevents multiple signals in the same direction. Once a BUY signal fires, the `trendState` locks to `+1` and no further BUY signals are generated until a SELL signal resets it (and vice versa). This avoids whipsaw entries on the same trend move.

**Fixed ₹ Target:** The positional profit target is calculated as `₹500,000 / (lotSize × lots)`. For example, with 65 lot size and 10 lots: target = 500,000 / 650 ≈ 769 points above entry. This is designed for **positional traders** who have a fixed monetary profit goal per trade.

---

### 8. RSI Extreme Exits (Lines 256-262)

```
longRSIExit  = inLong AND crossover(rsi, 90)
shortRSIExit = inShort AND crossunder(rsi, 10)
```

**Purpose:** Exits positions when RSI reaches statistical extremes (90+ for longs, 10 or below for shorts). These levels occur approximately 1-3% of the time and represent parabolic moves that are likely to reverse.

**Design Note:** These are intentionally aggressive — they're meant to catch only the most extreme moves. For most positions, the fixed ₹ target or scalp targets will close the trade before these levels are reached.

---

### 9. Moving Averages (Lines 278-281)

```
plot(ema5, "EMA 5", color=color.rgb(6, 121, 10), linewidth=2)
plot(ema20, "EMA 20", color=color.red, linewidth=2)
plot(sma50, "SMA 50", color=color.rgb(3, 3, 0))
```

**Visual purpose:** EMA5 (green), EMA20 (red), SMA50 (dark/yellowish). These provide visual context for the trend filters. EMA5 crossing EMA20 is a visible confirmation of trend direction.

---

### 10. Visual-Only Sections (Not Used for Signal Generation)

#### HMA (Hull Moving Average) — Lines 278-340
A visually smoothed moving average with color changes based on momentum. Rendered with a black border for emphasis. **Purely decorative** — does not affect any signal logic.

#### Coral Indicator — Lines 345-410
A trend-following indicator based on cascading IIR filters with an adjustable smoothing constant. Available in two modes:
- **Standard mode:** Plots the Coral line with green/red coloring
- **Ribbon mode:** Colors the background
- **Color bars mode:** Colors individual candles

Includes HTF (1-hour) and LTF (10-minute) Coral states for additional context. **Purely decorative** — does not affect any signal logic.

#### HL/LH (Higher Low / Lower High) — Lines 414-480
Detects swing structure patterns using adaptive pivot detection. Shows "HL" (Higher Low) labels below bars during bullish trends and "LH" (Lower High) labels above bars during bearish trends. Includes separate alert conditions. **Purely decorative** — does not affect any signal logic.

---

### 11. Structural Level Lines (Lines 242-298)

At the start of each new day, the indicator draws:
- **Vertical anchor line** connecting the highest and lowest targets (gray, serves as daily boundary reference)
- **Red dashed lines** for scalp targets (Target 1 & Target 2 above/below)
- **Blue lines** for Breakout (above, width=2) and Breakdown (below, width=2)
- **Red line** for Sell Reversal level
- **Orange line** for Pivot level (width=2)
- **Lime line** for Buy Reversal level

All lines extend to the right, providing forward-looking reference levels for the trading day.

---

### 12. Right-Side Level Labels (Lines 283-324)

When `barstate.islast` is true (on the most recent bar), price labels are drawn offset to the right of the chart. Each label shows the level name and current value (rounded to the nearest integer). Example:

```
Target 2 - 5276
Target 1 - 5241
Breakout - 5204
Sell Reversal - 5168
Pivot - 5159
Buy Reversal - 5152
Break Down - 5140
Target 1 - 5112
Target 2 - 5088
```

---

### 13. Dashboard Table (Lines 327-338)

A compact 4-column table at the top center of the chart showing:
- **ADX** — Current ADX value (yellow text)
- **DI+** — Positive directional index (green text)
- **DI-** — Negative directional index (red text)
- **BULL / BEAR / NEUTRAL** — Current trend state (colored accordingly)

---

### 14. Alert Conditions (Lines 340-358)

Six alert conditions are available for automated monitoring:

| Alert | Trigger | Use Case |
|-------|---------|----------|
| BUY REVERSAL | BUY-R signal fires | Enter long on reversal |
| SELL REVERSAL | SELL-R signal fires | Enter short on reversal |
| BUY BREAKOUT | BUY-B signal fires | Enter long on breakout |
| SELL BREAKDOWN | SELL-B signal fires | Enter short on breakdown |
| LONG EXIT RSI | RSI > 90 while in long | Exit long at extreme |
| SHORT EXIT RSI | RSI < 10 while in short | Exit short at extreme |

---

## Signal Matrix Summary

| Signal | Level Touch | Trend Required | RSI Filter | Type |
|--------|-------------|----------------|------------|------|
| **BUY-R** | HA close > Buy Reversal | Bullish | RSI < 80 | Reversal / pullback entry |
| **BUY-B** | HA crossover Breakout | Bullish | None (already checked in trend) | Momentum breakout entry |
| **SELL-R** | HA close < Sell Reversal | Bearish | RSI > 20 | Reversal / pullback entry |
| **SELL-B** | HA crossunder Breakdown | Bearish | None (already checked in trend) | Momentum breakdown entry |

---

## Trading Guidelines

### Recommended Timeframes
- **Primary:** 1-hour or 30-minute charts (for signal reliability with ADX/DMI)
- **Minimum:** 15-minute (requires at least 33 bars for ADX calculation)
- **Ideal setup:** Use on 1H chart with Daily pivot levels

### Entry Rules
1. Wait for a **BUY-R / BUY-B or SELL-R / SELL-B** label to appear
2. Verify the label corresponds with the current trend direction (green label = bullish context, pink label = bearish context)
3. Check the dashboard for ADX > 20 and DI+ > DI- (for buys) or DI- > DI+ (for sells)
4. For manual entry: enter on the next candle open after the signal

### Exit Rules

**Scalp Strategy:**
- Target 1: +0.28× ATR from breakout (conservative)
- Target 2: +0.41× ATR from breakout (aggressive)
- Stop: Breakout level for BUY-B, Breakdown level for SELL-B

**Positional Strategy:**
- Fixed ₹ target (default: ₹5,00,000 / position size)
- 5% trailing or fixed stop-loss
- RSI extreme exits (RSI > 90 for longs, RSI < 10 for shorts)

### Risk Management
- Position size: `lotSize × lots` (default: 65 × 10 = 650 shares)
- Capital per position: ₹1.5L (built into the tracker system)
- Maximum 1 active trade per direction (enforced by trendState)

---

## Parameter Reference

| Input | Default | Range | Effect |
|-------|---------|-------|--------|
| EMA Fast | 5 | 3-20 | Sensitivity of short-term trend |
| EMA Slow | 20 | 10-50 | Medium-term trend direction |
| SMA Length | 50 | 20-200 | Major trend filter |
| ADX Length | 14 | 7-21 | ADX lookback period |
| ADX Smoothing | 14 | 7-21 | ADX smoothing |
| ADX Threshold | 20 | 15-30 | Minimum trend strength |
| Use VWAP | true | On/Off | Optional volume filter |
| Sell Rev ATR Mult | 0.29 | 0.1-0.5 | Distance of sell reversal from pivot |
| Buy Rev ATR Mult | 0.21 | 0.1-0.5 | Distance of buy reversal from pivot |
| Breakout ATR Mult | 0.54 | 0.3-0.8 | Distance of breakout from pivot |
| Breakdown ATR Mult | 0.46 | 0.3-0.8 | Distance of breakdown from pivot |
| Target 1 ATR Mult | 0.28 | 0.1-0.5 | First scalp target distance |
| Target 2 ATR Mult | 0.41 | 0.1-0.6 | Second scalp target distance |
| Lot Size | 65 | 1-500 | Lot/multiplier for position sizing |
| Lots | 10 | 1-100 | Number of lots |
| Target ₹ | 500000 | 10000-1e7 | Fixed profit target in rupees |

---

## Version History

| Version | Changes |
|---------|---------|
| **V1 (Current)** | Initial release. Core pivot+ATR framework with ADX trend filter, reversal and breakout signals, dual target system (scalp + positional), RSI extreme exits, visual indicators (HMA, Coral, HL/LH), dashboard, and alert conditions. |

---

## Disclaimer

This indicator is for **educational and analytical purposes only**. It does not constitute financial advice. Past performance (backtested or live) does not guarantee future results. Always practice proper risk management and consult a qualified financial advisor before making trading decisions.