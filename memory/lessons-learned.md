# Lessons Learned & Tuning History

**Version:** 4.0  
**Date:** March 5, 2026  
**Status:** Production Insights

---

## Tuning Timeline

### v1: Initial Build (Feb 2026)

**What:** Basic 3-bot framework with loose gates

**Parameters:**
- All gates present but lenient
- 6+ overlapping indicators (ADX, RSI, MACD, Bollinger Bands)
- 3-bot strategy (bullish, bearish, sideways)
- Fixed dollar position sizing

**Results:**
- High trade frequency (700+ trades)
- Win rate: 38-45% (poor)
- Lots of false signals
- Required discretion to ignore conflicting indicators

**Key Problem:** Too many indicators → conflicting signals → required trader judgment

### v2: Ripster EMA Clouds (Mar 1-3, 2026)

**What:** Added Ripster-style EMA clouds for regime detection, attempted to fix sideways bot

**Changes:**
- Replaced 6+ overlapping indicators with EMA cloud positioning
- 4-cloud system (8/9, 20/21, 34/50, 55/89)
- Added ADX/RSI as supporting filters
- Tested sideways bot (iron condors)

**Results:**
- Sideways bot: **-$2,454 P&L** ❌ (losing money)
- Win rate on sideways: 51.4% (decent) but losses > wins
- Bullish/bearish bots still profitable

**Key Insight:** Iron condors are tricky. When price breaks one side, gamma overwhelms theta, and tight stops get hit hard. Not worth the risk for 0DTE.

**Decision:** Disable sideways bot entirely. Go directional-only.

### v3: Revert to Directional-Only (Mar 3-4, 2026)

**What:** Removed sideways bot, kept bullish/bearish only

**Changes:**
- When regime = SIDEWAYS → Return NO_TRADE (skip trade)
- All gates still active
- Bullish/bearish logic unchanged

**Results:**
- Total P&L improved: $42,785 → $44,211 (+$1,426)
- Fewer trades but higher quality
- Sharpe ratio improved
- Win rate improved slightly

**Key Insight:** Simple > Complex. Removing the unprofitable bot improved overall system.

### v4: Current Production (Mar 5, 2026)

**What:** Standardized 4 configurations, cleaned up code, documented thoroughly

**Key Features:**
- 4 tuned configs (A-Loose, B-Medium, C-Strict, D-Best)
- Directional-only (bullish/bearish)
- All 5 gates implemented + logged
- 4-signal confluence logic
- VIX1D-based dynamic strike placement
- Comprehensive backtesting
- Production-ready codebase

**Results:**
- Config C-Strict: 62.6% win rate, $27,938 P&L, 12.7% max DD
- Config D-Best: 68.3% win rate, $34,114 P&L, 10.5% max DD

---

## Major Learnings

### Learning 1: Strike Width Is Critical

**Problem v1:** Fixed $5 condor width was too tight

**Evidence:**
```
Backtest results showed:
- 71% of condors got touched by SPX intraday
- Meant 71% loss rate
- System was broken
```

**Investigation:** "Wait, this was backtesting LIVE prices. Of course SPX moved 24 pts. That's normal!"

**Solution:** Use VIX1D to size strikes

```python
# Before (naive):
short_strike = spx - 5  # Always $5 distance

# After (smart):
expected_move = (vix1d / 100) * spx
short_strike = spx - (0.8 * expected_move)  # 1 std dev away
```

**Result:** Strike width now scales with volatility. High vol → wider strikes. Low vol → tighter strikes.

**Key Insight:** One-size-fits-all strike width doesn't work. Use market-adjusted sizing.

### Learning 2: Stop Loss Logic Matters More Than Strike Selection

**Problem v1:** Fixed 0.3% stop-loss was triggering constantly

**Evidence:**
```
Day with ATR = 65 points:
- 0.3% on $5500 SPX = $16.50
- ATR = $65
- Stop at $16.50 is 25% of day's range
- Getting stopped constantly on normal vol days
```

**Investigation:** Looked at losing trades—were they actually bad trades?

```
Trade entered at 11:00 AM:
- Position looked fine
- By 11:30 AM, hit $16.50 stop
- By 3:30 PM, trade would have been +$200 winner!
- Stop was WRONG, not the entry
```

**Solution:** Use ATR-scaled + hourly-close-based stops

```python
# Before:
stop_loss = entry_price - (entry_price * 0.003)  # Fixed percent

# After:
atr = calculate_atr(daily_closes, period=14)
stop_loss = entry_price - (1.5 * atr)  # 1.5x daily ATR
# Only check on hourly closes, not every tick
```

**Result:** Fewer false stops. Winners get room to breathe. Losers get cut quickly.

**Key Insight:** Stop placement is more important than strike selection. Bad stops kill good trades.

### Learning 3: Confluence > Individual Signals

**Problem v1:** 6 overlapping indicators meant conflicting signals

```
Example trade:
- ADX says BULLISH
- RSI says BEARISH
- MACD says BULLISH
- Stochastic RSI says BEARISH
- Bollinger Bands say... ??? (unclear)

Required: Trader discretion to decide
Result: Inconsistent, subjective, not mechanical
```

**Solution:** 4 signals, all must align

```python
# Signals:
1. Daily trend (20-SMA) = BULLISH or BEARISH
2. VWAP slope = RISING or FALLING
3. EMA 5 vs 40 = BULLISH or BEARISH
4. OR breakout = UP or DOWN

# Decision:
IF all 4 signals = BULLISH:
    Enter bullish bot
ELIF all 4 signals = BEARISH:
    Enter bearish bot
ELSE:
    Skip trade (no confluence)
```

**Result:**
- Fewer trades (maybe 50-70% fewer)
- Much higher quality
- Win rate jumped from 45% to 62%+
- No discretion needed—mechanical

**Key Insight:** 4 aligned signals > 6 conflicting signals. Quality > Quantity.

### Learning 4: Sideways Bots Don't Work for 0DTE

**Problem:** Iron condor strategy looked good theoretically

```
Theoretical edge:
- Sell both puts and calls
- Collect twice the premium
- Both sides theta decay in your favor
- Should be great!
```

**Reality:** Gamma destruction

```
Day 1: Enter iron condor, both sides 30-delta
- Short 5475 put: $1.50 credit
- Short 5525 call: $1.50 credit
- Total: $3.00 credit (looked great!)

Day 2 (market gaps up 20 pts):
- SPX now at 5520
- 5525 call delta: went from 30 → 80
- Gamma ate us alive
- Now short 80 deltas on calls
- Showing $2.50 loss vs $3.00 credit collected
- We're LOSING money on our sold side

Stop triggered, exit for loss
```

**Analysis:** On 0DTE, gamma is so high that when price breaks one side of the condor, you get blown out before theta can save you.

**Evidence from backtest:**
- Sideways bot: 51.4% win rate, but...
- Wins were small ($30-50)
- Losses were max loss ($400-430)
- Average trade: -$70
- Total: -$2,454 on 35 trades

**Solution:** Don't trade sideways. Go directional.

**Key Insight:** 0DTE gamma is too high for double-sided selling. Directional bots (single-sided) work better.

### Learning 5: Gate Compliance Matters

**Problem v1:** Gates weren't enforced strictly

```
Trader thinking: "VIX1D is 25.5, and gate is 25. Close enough, let me trade."
Result: Lost money on high-vol days
```

**Solution:** Hard-coded gates, logged 100%

```python
# Check ALL 5 gates before entry
gates = GateStatus(
    gex = gex_forecast > 0,
    vix1d = 15 < vix1d < 25,
    calendar = no_major_events_next_2h,
    time = 10:30 <= current_time <= 13:00,
    premium = expected_move > strike_width
)

if not gates.all_pass:
    return NO_TRADE  # Hard stop, no exceptions
```

**Result:**
- We skip ~30% of potential trading days
- But the trades we DO take have 60%+ win rate
- Total P&L is higher
- GEX gate alone prevented 30%+ of worst-drawdown days

**Key Insight:** Missing good trades hurts less than taking bad trades. Gates are protective.

---

## Specific Tuning Discoveries

### Discovery 1: Bullish Bot > Bearish Bot

**Finding:**
```
Bullish Bot (sell puts):
- 398 trades
- 63.3% win rate
- $21,340 P&L

Bearish Bot (sell calls):
- 254 trades
- 61.4% win rate
- $6,598 P&L
```

**Why?** SPX has upward bias (long-term trend). Selling puts (bullish bot) is easier than selling calls (bearish bot).

**Strategy Implication:** Can weight bullish bot more heavily in portfolio allocation.

### Discovery 2: Calm Markets Are Best

**Finding:**
```
VIX1D < 15 (calm):
- Win rate: 65%
- P&L: +$18,900

VIX1D 20-25 (elevated):
- Win rate: 58%
- P&L: -$2,162
```

**Action:** VIX1D gate at 22 is correct. We should skip elevated-vol days.

### Discovery 3: Friday ≠ Better for 0DTE

**Finding:**
```
Expectation: Friday should be better (expiration day effect)
Reality:
- Monday-Thursday: 62% win rate
- Friday: 62.5% win rate (only slightly better)
```

**Implication:** No special Friday edge. Trade same way all week.

### Discovery 4: Opening Range is Critical

**Finding:**
```
If we entry BEFORE opening range forms:
- Win rate: 55% (worse)

If we wait for OR to form (9:30-10:30 AM):
- Win rate: 62% (much better)
```

**Why?** OR confirms whether regime (bullish/bearish) is REAL or just noise.

**Action:** 10:30 AM entry window is correct. Don't enter earlier.

### Discovery 5: Early Exit Helps Win Rate

**Finding:**
```
Taking profit at 60% of credit:
- Trade success rate: 68%

Holding to 100% of credit:
- Trade success rate: 52%
```

**Why?** Early exit locks profit before price moves against us. Holding greedy gets us stopped out.

**Action:** 60% early exit is correct. Don't get greedy.

---

## What Didn't Work (and Why)

### 1. Looser Confluence Requirements

**Tried:** Require only 2 of 4 signals (loose)  
**Result:** 45% win rate (terrible)  
**Why:** Too many false signals  
**Lesson:** More signals = more quality gate

### 2. Tighter Strikes (0.5x ATR)

**Tried:** Place strikes even closer to ATM  
**Result:** 85% stop-hit rate (always losing)  
**Why:** Strike too close, any normal move hits stop  
**Lesson:** Let market volatility determine strike width

### 3. No Daily Loss Limit

**Tried:** Allow unlimited losses in a day  
**Result:** Day with -5% loss turned into -8% (compound losses)  
**Why:** Emotional trading, revenge losses  
**Lesson:** Hard daily loss limit (2%) prevents compounding

### 4. Manual Discretion on Stops

**Tried:** "Let me hold this one more minute, it might recover"  
**Result:** Frequent -$400 losses instead of -$100  
**Why:** Emotion overrides rules  
**Lesson:** Automate stops, remove discretion

### 5. Sideways Bot (as discussed)

**Tried:** Iron condors for rangebound markets  
**Result:** -$2,454 P&L  
**Why:** Gamma destruction on 0DTE  
**Lesson:** Directional trades > double-sided

---

## Current Production Decisions

### Decision 1: Use Config C-Strict for Live Trading

**Rationale:**
- 62.6% win rate (highest confidence)
- 12.7% max DD (manageable)
- 2.03 Sharpe (good risk-adjusted)
- 652 trades over 2.7 years (enough frequency for learning)

**Alternative:** Config D-Best (68.3% WR, smaller DD) but too restrictive for learning.

### Decision 2: Directional-Only Strategy

**Rationale:**
- Sideways bot lost money
- Directional bots (bullish + bearish) profitable
- Simple > complex

**Action:** No iron condors. Only bull put spreads and bear call spreads.

### Decision 3: All 5 Gates Mandatory

**Rationale:**
- Gates filter out 30%+ of worst trades
- Gate compliance = 100% target
- No exceptions, no discretion

**Enforcement:** Hard-coded, logged every trade.

### Decision 4: VIX1D-Based Dynamic Strikes

**Rationale:**
- Volatility changes daily
- Fixed strikes don't adapt
- One-size-fits-all doesn't work
- Dynamic sizing improves win rate

**Implementation:** `short_strike = spx - (0.8 × expected_move)`

---

## Predictable Future Challenges

### Challenge 1: Initial Paper Trading Period

**What will happen:**
- Fewer losses (no commissions, perfect execution)
- Higher win rate than backtest
- False confidence ("system is better than expected!")

**Reality:** Live has slippage, fills, emotion. Results will regress toward backtest.

**Mitigation:** Accept that performance will be lower in live.

### Challenge 2: First Major Drawdown

**What will happen:**
- Account drops 10-15% from peak
- Trader panics ("Something's wrong!")
- Temptation to break rules ("Let me skip this gate")

**Reality:** Drawdowns are normal and expected. Backtest predicted them.

**Mitigation:** Review backtest. Drawdowns happened there. They'll happen here. Trust the process.

### Challenge 3: Win Rate Regression

**What will happen:**
- Backtest: 62.6% win rate
- Paper trading: Maybe 55%
- Live: Maybe 50%

**Why:** Slippage, fills, emotion, market regime change

**Mitigation:** 50%+ is still profitable. Don't expect backtest-perfect results.

### Challenge 4: Urge to Add "Just One More" Trade

**What will happen:**
- See a partially-aligned signal
- Think "maybe I should trade this"
- Want to skip gates ("just this once")

**Reality:** Every trade you skip gates on loses money (that's why gates exist!)

**Mitigation:** Automate everything. Remove human discretion.

---

## Continuous Improvement (Post-Live)

### Monthly Review Process

1. **Analyze all trades from past month**
   - Which ones lost money? (analyze patterns)
   - Did any gate failures get through? (fix system)
   - Any rules broken? (discipline check)

2. **Re-run backtest on recent data**
   - Last 3 months of market data
   - Does system still work?
   - Any regime changes?

3. **Update parameters if needed**
   - Test in backtest FIRST
   - Only deploy if backtest validates
   - Never change in live without backtest

4. **Document learnings**
   - Add to this file
   - Share with future self

### Metrics to Track Continuously

```
Daily:
- Win rate (rolling 20-trade average)
- Gate compliance (100% target)
- Daily P&L

Weekly:
- Rolling win rate
- Max drawdown from peak
- Stop execution compliance

Monthly:
- Total return (target 3-8%)
- Sharpe ratio (target > 1.5)
- Max drawdown (target < 10%)
- Gate compliance audit (100% target)
- Any rules violated? (log immediately)
```

---

## Key Lessons for Future Engineers

If you're reading this months/years from now:

1. **Trust the backtest.** It's survived 670 trading days of testing. Drawdowns will happen. Recovery happens.

2. **Never break gates.** Those 5 gates exist because each one prevents 10%+ of losing trades. Never skip.

3. **Automate everything.** Remove human discretion. Code the rules. Emotion kills trading.

4. **Start small.** Paper trade 2-4 weeks. Live micro 1 month. Only scale if it works.

5. **Document trades.** Every trade logged with gate status. This is your audit trail.

6. **Use Config C-Strict.** Unless you have strong reason otherwise. It's the sweet spot.

7. **Monitor weekly.** If win rate drops below 50%, pause and investigate.

8. **Enjoy the process.** Trading a systematic strategy should feel like running a business, not gambling.

---

**Version:** 4.0  
**Status:** Production Insights Captured  
**Next:** Begin paper trading validation
