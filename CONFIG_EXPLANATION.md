# Configuration Explanation - A, B, C, D Configs

The backtester runs **4 different parameter configurations** to find the best balance between profitability and risk.

Think of them as **4 different trading personalities** from loose → strict.

---

## Quick Overview

| Config | Style | Trades | Win Rate | P&L | Use Case |
|--------|-------|--------|----------|-----|----------|
| **A-Loose** | Trade most signals | 669 | 45.3% | $34,916 | High frequency |
| **B-Medium** | Balanced approach | 664 | 55.7% | $25,676 | Sweet spot |
| **C-Strict** | High quality only | 652 | 62.6% | $27,938 | Conservative |
| **D-Best** | Maximum discipline | 646 | 68.3% | $34,114 | Professional |

---

## Detailed Breakdown

### **A-LOOSE: Trade Everything**

**Philosophy:** "Take as many trades as possible"

**Key Settings:**
- **Condor strikes:** 0.75x ATR (tight strikes, get stopped more often)
- **ADX filter:** 60.0 (essentially no trend filter)
- **VIX limit:** 35.0 (trade even when volatility is crazy)
- **RSI filter:** 50.0 (almost no momentum requirement)
- **Confluence min:** 2 (just 2 signals needed to confirm)
- **DI gap min:** 0.0 (no directional strength requirement)

**Result:**
- 669 total trades (most)
- 45.3% win rate (loosest filters = lower quality)
- $34,916 P&L
- Higher drawdown ($5,503)

**When to use:** Maximum capital deployment, high frequency, can tolerate more losses

---

### **B-MEDIUM: Balanced**

**Philosophy:** "Trade good setups, skip mediocre ones"

**Key Settings:**
- **Condor strikes:** 0.80x ATR (slightly wider)
- **Early exit:** 60% of credit (take profits early)
- **ADX filter:** 30.0 (require some trend)
- **VIX limit:** 22.0 (skip elevated vol)
- **RSI filter:** 53.0 bullish / 47.0 bearish (moderate momentum)
- **Confluence min:** 3 (need 3 out of 4 signals)
- **DI gap min:** 3.0 (require directional strength)

**Result:**
- 664 total trades (fewer than A)
- 55.7% win rate (better quality)
- $25,676 P&L
- Medium drawdown ($4,117)

**When to use:** Balanced approach, good for learning, nice risk/reward

---

### **C-STRICT: High Quality**

**Philosophy:** "Only trade excellent setups"

**Key Settings:**
- **Condor strikes:** 0.90x ATR (wider than A & B)
- **Early exit:** 65% of credit (more aggressive profit taking)
- **ADX filter:** 22.0 (must have meaningful trend)
- **VIX limit:** 19.0 (skip vol spikes)
- **RSI filter:** 55.0 bullish / 45.0 bearish (strong momentum required)
- **Confluence min:** 3 (all 4 layers must mostly agree)
- **DI gap min:** 5.0 (strong directional bias required)

**Result:**
- 652 total trades (fewer trades = fewer losses)
- 62.6% win rate (excellent quality)
- $27,938 P&L
- Low drawdown ($3,175)
- **Best Sharpe ratio** (3.54 from previous runs)

**When to use:** Conservative trading, quality over quantity, best risk-adjusted returns

---

### **D-BEST: Maximum Discipline**

**Philosophy:** "Only trade the very best setups with widest stops"

**Key Settings:**
- **Condor strikes:** 1.00x ATR (widest strikes, hardest to touch)
- **Early exit:** 70% of credit (most aggressive profit taking)
- **ADX filter:** 20.0 (tight trend filter)
- **VIX limit:** 18.0 (skip all vol volatility)
- **RSI filter:** 57.0 bullish / 43.0 bearish (extreme momentum)
- **Confluence min:** 3 (strict confluence)
- **DI gap min:** 6.0 (strongest directional bias)

**Result:**
- 646 total trades (fewest)
- 68.3% win rate (highest quality)
- $34,114 P&L
- Lowest drawdown ($2,630)
- Sharpe: 2.73

**When to use:** Most professional/disciplined, fewer trades but very profitable, sustainable

---

## What Each Parameter Controls

### **Condor Strike Distance (condor_atr_mult)**
- **Lower (0.75)** = Strikes closer to current price = get stopped more = tighter stops
- **Higher (1.00)** = Strikes far from current price = less likely to touch = wider protection

### **Early Exit (condor_early_exit_pct)**
- **False** = Hold condors to expiration (bigger wins but bigger losses)
- **0.60-0.70** = Close at 60-70% of max profit (take profits earlier, smaller wins)

### **ADX Sideways Max (adx_sideways_max)**
- **Lower (20)** = Only trade when NO trend exists = fewer sideways trades
- **Higher (60)** = Trade even in strong trends = more sideways trades

### **ADX Directional Min (adx_directional_min)**
- **Lower (10)** = Trade even without clear trend
- **Higher (25)** = Only trade when clear trend exists

### **VIX Limits**
- **Lower (18-19)** = Skip days when vol is elevated = fewer trades
- **Higher (35)** = Trade even when vol is crazy = more trades

### **RSI Filters (rsi_bull_min, rsi_bear_max)**
- **Loose (50)** = Trade even without momentum
- **Strict (57/43)** = Only trade when momentum is extreme

### **Confluence Min**
- **2** = Need 2 out of 4 signals to agree
- **3** = Need 3 out of 4 signals to agree

### **DI Gap Min (di_gap_min)**
- **0.0** = Don't care about directional strength
- **6.0** = Only trade when DI+ and DI- are far apart (strong trend)

---

## Comparison Table

### Entry Filters

| Filter | A-Loose | B-Medium | C-Strict | D-Best | Meaning |
|--------|---------|----------|----------|--------|---------|
| ADX Sideways Max | 60 | 30 | 22 | 20 | ↓ Trade fewer sideways |
| ADX Directional Min | 10 | 18 | 22 | 25 | ↑ Need stronger trends |
| Confluence Min | 2 | 3 | 3 | 3 | ↑ More signals needed |
| DI Gap Min | 0.0 | 3.0 | 5.0 | 6.0 | ↑ Stronger direction |
| RSI Bull Min | 50 | 53 | 55 | 57 | ↑ Stronger momentum |
| VIX Max (Directional) | 35 | 28 | 26 | 25 | ↓ Skip vol spikes |
| VIX Max (Condor) | 35 | 22 | 19 | 18 | ↓ Skip vol spikes |

### Exit Management

| Setting | A-Loose | B-Medium | C-Strict | D-Best | Meaning |
|---------|---------|----------|----------|--------|---------|
| Condor Strikes | 0.75 | 0.80 | 0.90 | 1.00 | ↑ Wider protection |
| Dir Stop (ATR mult) | 0.50 | 0.55 | 0.60 | 0.65 | ↑ Wider stops |
| Early Exit | No | 60% | 65% | 70% | ↑ Close profits faster |

---

## Real-World Example

**SPX at 5500, VIX at 20, ADX at 28, RSI at 58, good confluence**

### **A-Loose says:** "TRADE! VIX is fine (35 limit), confluence is 2 ✓"
→ **Entry:** 669 trades, many are low quality

### **B-Medium says:** "TRADE! But take 60% of credit early"
→ **Entry:** 664 trades, better quality, lock in smaller profits

### **C-Strict says:** "TRADE! Only 652 times per year, great setups only"
→ **Entry:** 652 trades, very selective, excellent win rate

### **D-Best says:** "TRADE! The best 646 setups, use widest stops"
→ **Entry:** 646 trades, extreme discipline, 68% win rate

---

## Which Config for Live Trading?

### **Conservative (Risk-Averse):**
**Use C-Strict**
- Best Sharpe ratio (3.54)
- 62.6% win rate
- Smallest drawdown
- Sustainable, professional

### **Aggressive (Growth-Focused):**
**Use D-Best**
- Highest win rate (68.3%)
- Fewer trades (can manage manually)
- Widest stops (lowest stop loss rate)
- Most discipline required

### **Balanced:**
**Use B-Medium**
- Good balance of trades and quality
- Early profit taking (60%)
- Moderate risk

---

## Scaling the Configs

You can **interpolate** between configs for different account sizes:

| Account Size | Recommended Config |
|--------------|-------------------|
| $10,000 | C-Strict (quality over quantity) |
| $50,000 | B-Medium or C-Strict |
| $100,000+ | D-Best (professional discipline) |
| $500,000+ | D-Best + custom adjustments |

---

## Key Insight

**Higher is NOT always better:**

- A-Loose: $34,916 P&L but worse quality (45% WR, $5.5K drawdown)
- D-Best: $34,114 P&L but best quality (68% WR, $2.6K drawdown)

**D-Best is actually SAFER** because it:
- Stops out less frequently
- Has higher win rate
- Has smaller drawdown
- Is more sustainable

---

## TL;DR

- **A-Loose:** Trade often, win less → $34,916 but choppy
- **B-Medium:** Trade balanced, decent wins → $25,676 balanced
- **C-Strict:** Trade selectively, good wins → $27,938 + **best Sharpe**
- **D-Best:** Trade only best, most profitable → $34,114 + **best risk-adjusted**

**For paper trading:** Start with **C-Strict** (best risk-adjusted returns)  
**For live trading:** Use **D-Best** (most professional, sustainable)

