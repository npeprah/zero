# Strategy Design - Complete Specification

**Version:** 4.0 (Directional-Only)  
**Date:** March 2026  
**Status:** Production Ready

---

## Strategy Overview

**ZERO** is a **mechanical, gate-based 0DTE SPX credit spread strategy** that deploys the right bot (bullish/bearish) based on market regime detection.

### Key Principles

1. **Mechanical** — No discretion. All rules are explicit, coded, and logged.
2. **Gate-First** — Every condition must pass before entry. Skip if any gate fails.
3. **Theta Farming** — All positions are credit spreads. Time decay works in your favor.
4. **Defined Risk** — You know max loss upfront. No surprises.
5. **Intraday Only** — Close by 4:00 PM ET. No overnight gap risk.

---

## Gate System (All 5 Must Pass)

### Gate 1: GEX Filter

**What:** Gamma Exposure (dealer positioning)

**Why:** Positive GEX compresses ranges (good for credit sellers). Negative GEX amplifies moves (we want to avoid these days).

**Rule:**
```
IF GEX < 0 → SKIP (negative gamma amplifies moves, kill our edge)
IF GEX ≥ 0 → PASS
```

**Current Implementation:** Estimated based on IV rank percentile
```python
gex_positive = (iv_rank > 50)  # Simple proxy
```

**Future:** Integrate SpotGamma API for real GEX data.

**Example:**
```
Monday: GEX = +0.45 → PASS ✓ (can trade)
Tuesday: GEX = -0.25 → SKIP ✗ (too risky)
```

### Gate 2: VIX1D Filter

**What:** Intraday volatility (VIX Futures, 1-day expiration)

**Why:**
- VIX1D > 25 = elevated intraday vol → SPX moves fast → strike placement becomes risky
- VIX1D < 20-day avg = premiums too rich (unlikely to fill at credit)

**Rule:**
```
IF VIX1D > 25 → SKIP (too volatile)
IF VIX1D < 20-day moving average → SKIP (premiums weak)
IF (20-day avg ≤ VIX1D ≤ 25) → PASS
```

**Example:**
```
Monday: VIX1D = 12, 20-day avg = 13 → SKIP (premiums weak)
Tuesday: VIX1D = 15, 20-day avg = 13 → PASS ✓ (can trade)
Wednesday: VIX1D = 28 → SKIP (too volatile)
```

### Gate 3: Economic Calendar

**What:** Major economic releases that move markets

**Why:** We want calm, rangebound trading. Skip 2 hours around major events.

**Skip Events:**
- FOMC meetings
- CPI release
- Non-Farm Payroll (NFP)
- Fed speakers (speech time + 1 hour after)
- Other major surprises (earnings of mega-cap index components, rate decisions)

**Rule:**
```
IF (current_time - event_time) < 2 hours → SKIP
ELSE → PASS
```

**Example:**
```
9:30 AM: CPI released → Skip all trades until 11:30 AM
10:30 AM: No major events in next 2 hours → PASS ✓
```

### Gate 4: Trading Time

**What:** Entry and exit time windows

**Why:**
- Enter only after opening range forms (9:30-10:30 AM)
- Exit all positions before close (3:30 PM mandatory)

**Rules:**
```
Entry Window: 10:30 AM - 1:00 PM ET ONLY
  IF (current_time < 10:30 AM) → SKIP (OR not formed yet)
  IF (current_time > 1:00 PM) → SKIP (too late to enter)
  ELSE → CAN ENTER

Exit Time: 3:30 PM ET MANDATORY
  ALL POSITIONS MUST BE CLOSED BY 3:30 PM
  No exceptions, no "let it ride"
```

**Why These Times?**
- 10:30 AM allows opening range (9:30-10:30) to form, confirming regime
- 1:00 PM cutoff ensures time for management + 2.5h before forced exit
- 3:30 PM closes all positions before 4:00 PM market close (no gap risk overnight)

### Gate 5: Premium Check

**What:** Verify the trade makes mathematical sense

**Why:** If strike width < expected move, high chance of max loss. If spread is too tight, bid-ask eats our edge.

**Rules:**
```
Expected Move = (VIX1D / 100) * Current SPX Price
Strike Width = Long Strike - Short Strike

IF (Expected Move ≤ Strike Width) → SKIP (overlaps our strikes)
IF (bid_ask_spread > 0.5% of credit) → SKIP (not enough edge)
ELSE → PASS
```

**Example:**
```
SPX = 5500, VIX1D = 20
Expected Move = (20/100) * 5500 = $110

Bullish setup: Sell 5475 put, buy 5470 put
Strike Width = 5 → Much smaller than $110 → PASS ✓

Bearish setup: Sell 5525 call, buy 5530 call
Strike Width = 5 → Much smaller than $110 → PASS ✓
```

---

## Three-Layer Indicator Stack

### Layer 1: Daily Trend Filter (20-SMA)

**What:** Trend direction on daily chart

**Why:** Establishes macro context. No point selling puts in a downtrend (puts lose money in downtrends).

**Calculation:**
```python
sma_20 = SPX daily closes over last 20 days, simple average
current_price = Current SPX price

IF current_price > sma_20 * 1.003 (above by 0.3%+):
    trend = BULLISH
ELIF current_price < sma_20 * 0.997 (below by 0.3%-):
    trend = BEARISH
ELSE:
    trend = NEUTRAL (within 0.3%)
```

**Interpretation:**
- **BULLISH** → Sell puts (benefit from continued strength)
- **BEARISH** → Sell calls (benefit from further weakness)
- **NEUTRAL** → Can be either, or skip if unclear

### Layer 2: Intraday Momentum (VWAP + EMA Crossover)

**What:** Intraday momentum direction

**Why:** Confirms that short-term price action agrees with daily trend.

#### Part A: VWAP (Volume-Weighted Average Price)

**Calculation:**
```python
VWAP = Cumulative(price * volume) / Cumulative(volume)  [intraday, resets daily]

# On 5-minute candles, look at slope over last 4 candles (20 minutes)
VWAP_slope = (VWAP_now - VWAP_20min_ago) / VWAP_20min_ago

IF VWAP_slope > 0.1%:
    VWAP_signal = RISING
ELIF VWAP_slope < -0.1%:
    VWAP_signal = FALLING
ELSE:
    VWAP_signal = FLAT
```

**Interpretation:**
- **RISING** → Intraday buying (bullish momentum)
- **FALLING** → Intraday selling (bearish momentum)
- **FLAT** → Balanced (neither direction winning)

#### Part B: EMA Crossover (5/40 on 1-minute chart)

**Calculation:**
```python
EMA_5 = Exponential Moving Average, 5 periods, 1-minute closes
EMA_40 = Exponential Moving Average, 40 periods, 1-minute closes

IF EMA_5 > EMA_40:
    EMA_signal = BULLISH
ELIF EMA_5 < EMA_40:
    EMA_signal = BEARISH
ELSE:
    EMA_signal = FLAT
```

**Interpretation:**
- **BULLISH** → Short-term momentum above long-term → buying interest
- **BEARISH** → Short-term momentum below long-term → selling pressure
- **FLAT** → Both at same level (rare, usually briefly)

**Why 5/40?** Industry standard for 0DTE entry confirmation (used in Option Alpha, Alpha Crunching systems).

### Layer 3: Range Context (60-Minute Opening Range)

**What:** Actual price confirmation of directional regime

**Why:** Indicators can be aligned on paper, but if price hasn't actually broken out, we're not in a regime yet.

**Calculation:**
```python
OR_HIGH = Highest price during 9:30-10:30 AM ET (first 60 minutes)
OR_LOW = Lowest price during 9:30-10:30 AM ET

IF (current_price > OR_HIGH):
    regime = BREAKOUT_UP (bullish confirmed)
ELIF (current_price < OR_LOW):
    regime = BREAKOUT_DOWN (bearish confirmed)
ELSE:
    regime = INSIDE_RANGE (sideways/no confirmation)
```

**Why 60 minutes?** Backtesting from Option Alpha showed this window provided best signal clarity vs. false breakouts. Shorter ranges (15-30 min) had too many fakeouts; longer (120+ min) missed early entry.

**Interpretation:**
- **BREAKOUT UP** → Price has confirmed buyers in control
- **BREAKOUT DOWN** → Price has confirmed sellers in control
- **INSIDE RANGE** → No clear direction yet (skip trade)

---

## Decision Tree: Bot Selection

```
START
  │
  └─→ Check ALL 5 GATES (GEX, VIX1D, Calendar, Time, Premium)
        │
        ├─ IF ANY gate FAILS
        │   └─→ NO_TRADE (skip entire day or wait for next signal)
        │
        └─ IF ALL gates PASS
            │
            ├─→ Calculate LAYER 1: Daily Trend (20-SMA)
            │     ├─ BULLISH?
            │     ├─ BEARISH?
            │     └─ NEUTRAL?
            │
            ├─→ Calculate LAYER 2: Intraday Momentum (VWAP + EMA)
            │     ├─ VWAP rising?
            │     ├─ VWAP falling?
            │     ├─ EMA 5 > 40?
            │     └─ EMA 5 < 40?
            │
            ├─→ Calculate LAYER 3: Opening Range Breakout
            │     ├─ Price > OR_HIGH? (BULLISH)
            │     ├─ Price < OR_LOW? (BEARISH)
            │     └─ Price inside? (SIDEWAYS)
            │
            └─→ DECISION LOGIC:
                  │
                  IF (ALL 4 signals BULLISH):
                    - Daily trend BULLISH (above 20-SMA)
                    - VWAP rising
                    - EMA 5 > EMA 40
                    - Price > OR_HIGH
                    └─→ BOT = BULLISH ✓ (Sell Put Spread)
                  │
                  ELSE IF (ALL 4 signals BEARISH):
                    - Daily trend BEARISH (below 20-SMA)
                    - VWAP falling
                    - EMA 5 < EMA 40
                    - Price < OR_LOW
                    └─→ BOT = BEARISH ✓ (Sell Call Spread)
                  │
                  ELSE:
                    - Signals don't all align
                    └─→ NO_TRADE (not enough confluence)
```

### Confluence Rule

**Current Config C-Strict:** All 4 signals must align.

```python
signals = [
    (daily_trend == BULLISH),
    (vwap_slope == RISING),
    (ema_5 > ema_40),
    (or_breakout == UP)
]

confluence = sum(signals)  # 0-4

IF confluence == 4:
    return BotType.BULLISH  # All agree

ELSE IF confluence == 4 (all bearish):
    return BotType.BEARISH

ELSE:
    return BotType.NO_TRADE  # Not enough confluence
```

**Why this strict rule?** Reduces false signals. Backtesting showed:
- Fewer trades but much higher win rate
- Less emotional stress (fewer small losses)
- Better Sharpe ratio (smoother equity curve)

---

## Bullish Bot: Bull Put Spread

### What Is It?

You sell a put (collect premium) and buy a cheaper put further down (define max loss).

```
SPX = 5500

SELL 5475 Put (strike below current)  ← Collect premium, e.g., $1.50/contract = $150
BUY  5470 Put (strike below that)     ← Pay premium, e.g., $0.80/contract = $80

NET CREDIT = $1.50 - $0.80 = $0.70 per share = $70/contract

Max Risk = Width - Credit = $5 - $0.70 = $4.30 per share = $430/contract
```

### When to Use

- Daily trend is BULLISH (SPX > 20-SMA)
- VWAP rising (intraday buyers in control)
- EMA 5 > 40 (momentum is up)
- Price breaking above opening range high (confirmed breakout)
- All gates pass (GEX, VIX1D, calendar, time, premium)

### Mechanics

**Entry:**
1. Sell 5475 put
2. Buy 5470 put (protective)
3. Collect credit (e.g., $70 per contract)
4. Set max loss = width - credit (e.g., $430 per contract)

**Exit Targets:**
- **Profit Target:** 60% of credit collected ($42/contract) → Close for profit
- **Stop Loss:** Short delta rises 50%+ (usually $2-3 loss per contract) → Close for loss
- **Time Stop:** 3:30 PM ET mandatory → Close regardless of P&L

**Why This Works:**
- Theta decay helps us (premium shrinks over hours)
- If SPX stays above short strike, puts expire worthless, we keep all credit
- Defined risk (we know max loss upfront)

### Example Trade

```
9:30-10:30 AM: Opening range forms (OR high = 5510, OR low = 5490)

10:45 AM: SPX breaks above 5510, all gates pass
  → BULLISH signal confirmed
  → Enter Bull Put Spread:
    - Sell 5475 put @ $1.50 = $150 credit
    - Buy 5470 put @ $0.80 = $80 cost
    - Net credit: $70 (max profit)
    - Max loss: $430 (width - credit)

11:30 AM: SPX continues rallying to 5525
  → Premium shrinks, now can close for $42 profit (60% of credit)
  → Exit with profit ✓

OR

2:00 PM: SPX sells off to 5480, approaching 5475 short strike
  → Delta of short put rises 50%, now showing $200 loss
  → Stop triggered → Exit with loss ✗

OR

3:30 PM: Mandatory exit regardless
  → Close position, record P&L
```

---

## Bearish Bot: Bear Call Spread

### What Is It?

You sell a call (collect premium) and buy a more expensive call further up (define max loss).

```
SPX = 5500

SELL 5525 Call (strike above current)  ← Collect premium, e.g., $1.50 = $150
BUY  5530 Call (strike above that)     ← Pay premium, e.g., $0.80 = $80

NET CREDIT = $1.50 - $0.80 = $0.70 = $70/contract

Max Risk = Width - Credit = $5 - $0.70 = $4.30 = $430/contract
```

### When to Use

- Daily trend is BEARISH (SPX < 20-SMA)
- VWAP falling (intraday sellers in control)
- EMA 5 < 40 (momentum is down)
- Price breaking below opening range low (confirmed breakout)
- All gates pass

### Mechanics

**Entry:**
1. Sell 5525 call
2. Buy 5530 call (protective)
3. Collect credit (e.g., $70 per contract)

**Exit Targets:**
- **Profit Target:** 60% of credit → Close for profit
- **Stop Loss:** Short delta rises 50%+ → Close for loss
- **Time Stop:** 3:30 PM ET mandatory → Close

### Example Trade

```
10:45 AM: SPX breaks below 5490, all gates pass
  → BEARISH signal confirmed
  → Enter Bear Call Spread:
    - Sell 5525 call @ $1.50 = $150
    - Buy 5530 call @ $0.80 = $80
    - Net credit: $70
    - Max loss: $430

2:00 PM: SPX continues falling to 5480
  → Calls shrink in value, can close for $42 profit
  → Exit with profit ✓

OR

SPX rallies back to 5520 approaching 5525 short strike
  → Delta rises 50%, showing $200 loss
  → Stop triggered → Exit with loss ✗
```

---

## Strike Placement Strategy

### VIX1D-Based Dynamic Strikes

Instead of fixed dollar widths, use VIX1D to adjust strike distance.

**Formula:**
```python
expected_move = (VIX1D / 100) * current_spx_price

# For bull put spreads: Strike distance from ATM
short_strike = current_spx - (0.8 * expected_move)
long_strike = short_strike - 5  # $5 width

# For bear call spreads: Strike distance from ATM
short_strike = current_spx + (0.8 * expected_move)
long_strike = short_strike + 5
```

**Intuition:**
- High VIX1D (20+) → Larger expected move → Place strikes further away
- Low VIX1D (10-15) → Smaller expected move → Place strikes closer in
- Always aim for 65-75% probability of profit (strike should be ~1 std dev away)

**Example:**
```
SPX = 5500, VIX1D = 20
Expected Move = (20/100) * 5500 = $110
Short strike = 5500 - 0.8*110 = 5412
Long strike = 5412 - 5 = 5407

SPX = 5500, VIX1D = 10
Expected Move = (10/100) * 5500 = $55
Short strike = 5500 - 0.8*55 = 5456
Long strike = 5456 - 5 = 5451
```

**Why This Works:**
- Adjusts for market volatility automatically
- High vol days get wider strikes (better risk/reward)
- Low vol days get tighter strikes (easier to fill)
- No discretion needed

---

## Stop Loss & Profit Taking

### Stop Loss: Delta-Based

**Rule:**
```
IF (short_delta >= short_delta_entry + 0.50):
    EXIT_LOSS = True
```

**Example:**
```
Entry: Sold 5475 put, delta = -0.25 (25 deltas short)
Stop: If delta rises to -0.75 (75 deltas short)
  → This is 50 deltas of deterioration
  → Typically = $200-300 loss
  → Exit immediately
```

**Why Delta?** More sensitive to actual losing condition than fixed dollars. As SPX approaches short strike, delta rises rapidly, warning us early.

### Profit Taking: 60% of Credit

**Rule:**
```
IF (credit_collected * 0.60) >= current_P&L:
    TAKE_PROFIT = True
```

**Example:**
```
Collected $70 credit
60% of credit = $42 profit
Once position is worth $42 profit, close it
  → Realize the gain
  → Avoid greedy holding until expiry
```

**Why 60%?** Industry standard. Backtesting shows:
- Holding to 100% profit loses edge (commission costs add up)
- Taking 60% locks in solid gains
- Leaves room for slippage
- Improves win rate without sacrificing returns

### Time Stop: 3:30 PM ET Mandatory Exit

**Rule:**
```
IF (current_time >= 3:30 PM ET):
    CLOSE_ALL_POSITIONS = True
    (No matter what the P&L is)
```

**Why?** Avoid overnight gap risk. SPX can gap 100+ points on news. Better to close a small loss than risk large overnight gap.

---

## Risk Management Rules

### Position Sizing

```
Max Risk Per Trade = 1% of Account
Max Risk Per Day = 2% of Account → STOP TRADING

Example (on $25,000 account):
  Max risk per trade = $250
  Max daily loss = $500 → If you lose $500, stop trading for the day
  
Trade Sizing:
  If spread width = $430 (from earlier example)
  Max contracts = $250 / $430 = 0.58 → Trade 1 contract
  
  Actual risk = $430 per contract (knowing max loss in advance)
```

### Daily Loss Limit

```
IF cumulative_daily_P&L < -2% of account:
    STOP_TRADING = True (don't trade rest of day)
    
This is MANDATORY, not optional.
```

**Why?** Protects account on bad days (market gaps, unexpected volatility, GEX failure). Better to sit out 1 bad day than turn a -2% day into -10%.

### Gate Compliance Logging

Every trade must be logged with gate status:

```python
trade_log = {
    'entry_time': '10:45 AM',
    'bot_type': 'BULLISH',
    'gates': {
        'gex': 'PASS',
        'vix1d': 'PASS',
        'calendar': 'PASS',
        'time': 'PASS',
        'premium': 'PASS'
    },
    'short_strike': 5475,
    'long_strike': 5470,
    'credit': 70,
    'exit_time': '11:30 AM',
    'exit_type': 'PROFIT_TARGET',
    'P&L': 42
}
```

Target: 100% gate compliance (all 5 gates logged, 0 trades on gate failures).

---

## Daily Discipline Checklist

### Pre-Market (8:00-9:30 AM)

- [ ] Download latest SPX daily data (for 20-SMA)
- [ ] Calculate today's opening range expectations
- [ ] Check economic calendar (any events in trading hours?)
- [ ] Check GEX forecast (expect positive or negative today?)
- [ ] Check VIX1D (current and 20-day average)
- [ ] Review yesterday's trades (any lessons?)

### Entry Window (10:30 AM-1:00 PM)

- [ ] Wait for opening range to form (9:30-10:30 AM, NO trading)
- [ ] Once 10:30 AM hits, evaluate signals:
  - [ ] All 5 gates pass?
  - [ ] 4-signal confluence achieved?
  - [ ] Which bot? (BULLISH/BEARISH/NONE)
- [ ] If gates FAIL → Log NO_TRADE, move to next opportunity
- [ ] If gates PASS and signals align → Enter position:
  - [ ] Sell appropriate strikes
  - [ ] Buy protective strikes
  - [ ] Log trade details (entry time, credit, max risk)
  - [ ] Set alerts (profit target = 60% credit, stop = 50 delta loss)

### Management (1:00-3:30 PM)

- [ ] Monitor position every 15-30 minutes
- [ ] Check if profit target hit → Close and take profit
- [ ] Check if stop loss hit → Close and take loss
- [ ] Monitor delta + gamma (no surprises?)
- [ ] Log any manual exits with reason

### Exit (3:30 PM Mandatory)

- [ ] CLOSE ALL OPEN POSITIONS (no exceptions)
- [ ] Log final P&L for each position
- [ ] Log reason for exit (profit/loss/time)
- [ ] Update daily summary (total trades, total P&L, win rate)

### Post-Market (4:00 PM+)

- [ ] Calculate daily metrics:
  - [ ] Win rate (# wins / # trades)
  - [ ] Total P&L
  - [ ] Largest win
  - [ ] Largest loss
  - [ ] Max drawdown today
- [ ] Check gate compliance (% of gates passed today)
- [ ] Write brief journal entry (what worked, what didn't)
- [ ] Update running win rate, monthly P&L

---

## Summary Table

| Component | Bullish Bot | Bearish Bot |
|-----------|------------|------------|
| **Spread Type** | Bull Put (sell put) | Bear Call (sell call) |
| **Short Strike** | Below ATM | Above ATM |
| **Long Strike** | Further below | Further above |
| **Entry Signal** | BULLISH trend + breakout | BEARISH trend + breakout |
| **Profit If** | SPX stays above short | SPX stays below short |
| **Max Profit** | Credit collected | Credit collected |
| **Max Loss** | Width - credit | Width - credit |
| **Win Target** | 60% of credit | 60% of credit |
| **Stop** | 50 delta loss | 50 delta loss |
| **Time Exit** | 3:30 PM ET | 3:30 PM ET |

---

**Version:** 4.0  
**Status:** Production-Ready  
**Recommended Config:** C-Strict  
**Next:** Set up broker API + paper trading
