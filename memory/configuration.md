# Configuration & Parameter Tuning

**Version:** 4.0  
**Date:** March 5, 2026

---

## Config Overview

Four pre-built trading profiles are tested and compared. Each represents a different balance between trade frequency and signal quality.

Think of them as **4 different traders**:
- **A-Loose:** "I'll trade anything" (high frequency, lower quality)
- **B-Medium:** "I'll trade good setups" (balanced)
- **C-Strict:** "I only trade the best" (high quality, **RECOMMENDED**)
- **D-Best:** "I only trade perfect setups" (extremely selective)

---

## Config Parameters Explained

### Strike Width: `condor_strike_atrs`

**What:** How far from ATM (At The Money) to place the short strike

**Formula:**
```
Expected Move = (VIX1D / 100) × Current SPX Price
Short Strike Distance = condor_strike_atrs × ATR × 14-period volatility
```

**Values:**
- **0.75x ATR** (A-Loose) → TIGHT strikes, higher chance of max loss
- **0.80x ATR** (B-Medium) → Medium tightness
- **0.90x ATR** (C-Strict, D-Best) → WIDE strikes, lower chance of max loss

**Impact:** Wider strikes = fewer stops hit = higher win rate, but smaller profit per trade.

**Example:**
```
SPX = 5500, VIX1D = 20, ATR = 65

Expected Move = (20/100) × 5500 = $110

A-Loose:  0.75 × 65 = $49 from ATM  → 5500 - 49 = 5451 short put strike
B-Medium: 0.80 × 65 = $52 from ATM  → 5500 - 52 = 5448 short put strike
C-Strict: 0.90 × 65 = $59 from ATM  → 5500 - 59 = 5441 short put strike
D-Best:   0.90 × 65 = $59 from ATM  → 5500 - 59 = 5441 short put strike
```

Wider strikes (C/D) are further from the expected move, so less likely to get hit.

### Early Exit: `early_exit_pct`

**What:** When to take profit (as % of credit collected)

**Values:**
- **60%** (A/B/C) → Take 60% of credit as profit
- **70%** (C/D) → Wait for 70% (more greedy)

**Example:**
```
Collected $70 credit

60% exit: When P&L = $42 profit → CLOSE
70% exit: When P&L = $49 profit → CLOSE

70% usually hits, but sometimes price moves and we never get there.
60% hits more often.
```

**Impact:** Lower % = more profit-taking opportunities = higher win rate.

### ADX Filter: `adx_min`

**What:** Minimum trend strength (Average Directional Index, 0-100)

**Values:**
- **20** (none, basically)
- **25** (C-Strict) → Some trend required
- **30-35** (B/D) → Stronger trend required

**Interpretation:**
- ADX < 20 = weak trend, choppy market
- ADX 20-40 = normal trend
- ADX > 40 = strong trend

**Impact:** Higher ADX requirement = fewer trades, but trades are in clearer trends.

### VIX1D Limit: `vix_limit`

**What:** Skip trading if intraday vol is too high

**Values:**
- **22** (C-Strict) → STRICT, only trade calm days
- **25** (A) → Trade even elevated vol
- **35** (none)

**Example:**
```
Tuesday: VIX1D = 15 → PASS ✓ (can trade)
Wednesday: VIX1D = 28 → SKIP ✗ (if limit is 22)
```

**Impact:** Lower limit = fewer trades, but trades are in better environments.

### RSI Filter: `rsi_bullish`, `rsi_bearish`

**What:** Momentum filter (RSI = Relative Strength Index, 0-100)

**Values:**
- **Bullish side:** 50.5 (C-Strict) to 55.0 (D-Best)
- **Bearish side:** 49.5 (C-Strict) to 45.0 (D-Best)

**Interpretation:**
- RSI > 70 = overbought
- RSI 50-70 = bullish momentum
- RSI 30-50 = bearish momentum
- RSI < 30 = oversold

**Impact:** Higher threshold = fewer trades with clear momentum.

### Confluence Minimum: `confluence_min`

**What:** Minimum number of signals that must align

**Values:**
- **2.0** (A-Loose) → 2 of 4 signals needed
- **3.0-3.5** (B/C) → 3+ of 4 signals needed
- **4.0** (D-Best) → ALL 4 signals needed

**Signals:** Daily trend, VWAP, EMA 5/40, OR breakout

**Example:**
```
Signals available:
  - Daily trend: BULLISH ✓
  - VWAP: RISING ✓
  - EMA 5 > 40: YES ✓
  - OR: BREAKOUT UP ✓

With confluence_min = 2.0: BULLISH BOT ✓ (2+ signals met)
With confluence_min = 3.0: BULLISH BOT ✓ (3+ signals met)
With confluence_min = 3.5: BULLISH BOT ✓ (4 signals met)
With confluence_min = 4.0: BULLISH BOT ✓ (all 4 signals met)

But if only 3 signals bullish:
With confluence_min = 3.5: NO_TRADE ✗ (not enough)
With confluence_min = 4.0: NO_TRADE ✗ (not all agree)
```

**Impact:** Higher minimum = fewer trades, but much higher quality (higher win rate).

### DI Gap Minimum: `di_gap_min`

**What:** Directional strength requirement

**Values:**
- **0** (A-Loose) → No directional strength needed
- **3-5** (B/C) → Some directional conviction
- **6-8** (D-Best) → Strong directional conviction

**Calculation:** DI+ vs DI- difference (part of ADX)

**Impact:** Higher = fewer trades with clearer direction.

---

## Side-by-Side Comparison

### All Parameters

| Parameter | A-Loose | B-Medium | C-Strict | D-Best |
|-----------|---------|----------|----------|---------|
| **Strike width** | 0.75x ATR | 0.80x ATR | 0.90x ATR | 0.90x ATR |
| **Early exit** | 60% | 60% | 70% | 70% |
| **ADX min** | 60.0 | 30.0 | 25.0 | 35.0 |
| **VIX limit** | 35.0 | 22.0 | 22.0 | 20.0 |
| **RSI bullish** | 50.0 | 53.0 | 50.5 | 55.0 |
| **RSI bearish** | 50.0 | 47.0 | 49.5 | 45.0 |
| **Confluence min** | 2.0 | 3.0 | 3.5 | 4.0 |
| **DI gap min** | 0.0 | 3.0 | 5.0 | 8.0 |

### Results Summary

| Metric | A-Loose | B-Medium | C-Strict | D-Best |
|--------|---------|----------|----------|---------|
| **Trades** | 669 | 664 | 652 | 646 |
| **Win Rate** | 45.3% | 55.7% | 62.6% | 68.3% |
| **Total P&L** | $34,916 | $25,676 | $27,938 | $34,114 |
| **Sharpe Ratio** | 2.03 | 1.69 | 2.03 | 2.73 |
| **Max Drawdown** | 22.0% | 16.5% | 12.7% | 10.5% |
| **Profit Factor** | 1.62 | 1.72 | 1.84 | 2.01 |

---

## Choosing Your Config

### For Paper Trading (Recommended: C-Strict)

**Why C-Strict?**
- **Win Rate:** 62.6% (high confidence)
- **Sharpe:** 2.03 (good risk-adjusted returns)
- **Trades:** 652 per 2.7 years (enough to learn from)
- **Drawdown:** 12.7% (emotionally manageable)
- **Sweet Spot:** Between D (too strict) and A (too loose)

**Setup:**
```python
config = TradingConfig.C_STRICT
backtester = BacktestEngine(config)
```

### For Conservative Traders (Alternative: D-Best)

**Why D-Best?**
- **Win Rate:** 68.3% (highest quality)
- **Sharpe:** 2.73 (best risk-adjusted)
- **Drawdown:** 10.5% (smoothest ride)
- **Trade Count:** Lower (but still 646 over 2.7 years)

**Use if:** You're already profitable and want low stress.

### For Aggressive Traders (Not Recommended: A-Loose)

**Why NOT A-Loose?**
- **Win Rate:** 45.3% (frequent losses)
- **Drawdown:** 22.0% (emotional stress)
- **Sharpe:** 2.03 (lower risk-adjusted than C)

**Could use if:** You want maximum capital deployment, but emotionally prepared for big swings.

---

## Parameter Tuning Examples

### Example 1: "I want more trades"

**Current:** C-Strict (652 trades)  
**Solution:** Lower confluence minimum

```python
# Change from:
confluence_min: 3.5  # Need strong alignment

# To:
confluence_min: 3.0  # Lower threshold
# Expected result: +~50 trades, -2% win rate (more quantity, less quality)
```

### Example 2: "I want fewer losers"

**Current:** B-Medium (55.7% win rate)  
**Solution:** Increase confluence + widen strikes

```python
# Change from:
confluence_min: 3.0
strike_width: 0.80x ATR

# To:
confluence_min: 3.5
strike_width: 0.90x ATR
# Expected result: Fewer trades, higher win rate
```

### Example 3: "I want bigger profits per trade"

**Current:** C-Strict ($27,938 / 652 = $42.80 per trade)  
**Solution:** Lower early exit %

```python
# Change from:
early_exit_pct: 70%  # Wait for 70% of credit

# To:
early_exit_pct: 50%  # Take 50% and move on
# Expected: More trades hit profit target, lower avg profit per hit
# But more total wins = better P&L
```

---

## How to Change Config at Runtime

### In Python

```python
from config import TradingConfig

# Use pre-built config
config = TradingConfig.C_STRICT

# Or create custom config
config = TradingConfig(
    name="Custom",
    condor_strike_atrs=0.85,
    early_exit_pct=65,
    adx_min=28,
    vix_limit=23,
    rsi_bullish=51,
    rsi_bearish=49,
    confluence_min=3.2,
    di_gap_min=4
)

# Pass to engine
engine = BacktestEngine(config)
results = engine.run()
```

### In Command Line

```bash
# Run with Config C-Strict (default)
python3 real_backtester.py

# Run all 4 configs and compare
python3 real_backtester.py --compare-all

# Run custom config
python3 real_backtester.py --config custom --confluence 3.2 --adx 28
```

---

## Monitoring: Track Your Config Performance

### Daily (For Live Trading)

```python
daily_stats = {
    "date": "2026-03-05",
    "trades_today": 2,
    "wins": 1,
    "losses": 1,
    "p&l": 80,
    "win_rate": 50.0,  # Running
    "gates_passed": 3,  # Out of 5 possible
}
```

### Weekly

```python
weekly_stats = {
    "week": "2026-03-03 to 2026-03-07",
    "trades": 9,
    "wins": 6,
    "losses": 3,
    "win_rate": 66.7,
    "total_p&l": 620,
    "max_dd": 280,
}
```

### Monthly + Beyond

```python
monthly_stats = {
    "month": "March 2026",
    "trades": 35,
    "wins": 22,
    "losses": 13,
    "win_rate": 62.9,
    "total_p&l": 2450,
    "sharpe": 2.15,
    "max_dd": 350,
}
```

---

## Red Flags: When to Adjust Config

| Signal | Meaning | Action |
|--------|---------|--------|
| Win rate drops below 50% | Config getting worse | Review last 10 trades, consider stricter config |
| 3+ consecutive losses | Unusual losing streak | Pause trading, analyze market conditions |
| Win rate above 80% | Possible overfitting | Great if real money validates, but be cautious |
| Max drawdown > 15% | More painful than expected | Widen strikes or lower confluence min |
| Trades dropping by 50%+ | Config too restrictive | Lower confluence minimum |

---

## Production Checklist: Before Going Live

- [ ] Chose Config C-Strict (or D-Best if conservative)
- [ ] Ran 2+ week backtest to validate numbers
- [ ] Checked win rate ≥ 50% (soft requirement; 55%+ is better)
- [ ] Checked Sharpe > 1.5 (risk-adjusted returns are good)
- [ ] Checked max drawdown < 15% (emotionally tolerable)
- [ ] Logged all parameters in config.py
- [ ] Documented rationale for any custom parameters
- [ ] Set up alerts for red flags

---

**Version:** 4.0  
**Status:** Production-Ready  
**Recommended Config:** C-Strict  
**Next:** Paper trading validation
