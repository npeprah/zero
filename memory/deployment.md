# Deployment Roadmap

**Version:** 4.0  
**Date:** March 5, 2026  
**Status:** Ready for Paper Trading

---

## Deployment Phases

```
PHASE 1: Paper Trading (2-4 weeks)
├─ Set up broker API (paper account)
├─ Live execution of strategy
├─ Validate system + performance
└─ Decision: Go live micro or pause

PHASE 2: Live Micro (1 month)
├─ 1 contract per bot (~$500 risk/trade)
├─ Real money, small size
├─ Monitor closely
└─ Decision: Scale or pause

PHASE 3: Live Standard (2 months)
├─ Scale to 2-5 contracts
├─ Target 3-8% monthly return
├─ Professional operation
└─ Ongoing optimization
```

---

## Phase 1: Paper Trading (Weeks 1-4)

### Week 1: Setup

**Task 1: Choose Broker**
- [ ] E-Trade (recommended for 0DTE options)
- [ ] ThinkOrSwim / TD Ameritrade
- [ ] Interactive Brokers
- [ ] Tastytrade

**Task 2: Get Paper Trading Account**
```
1. Open broker account (real or paper)
2. Request paper trading access (usually free)
3. Provide API credentials to system
4. Test connection with sample order
```

**Task 3: Build Order Execution Module**

```python
# Pseudo-code for executing trade
class OrderExecutor:
    def place_order(self, trade_setup):
        # trade_setup = TradeSetup object from backtest
        # Returns: OrderID, filled_price
        
        # For bull put spread:
        order1 = broker.sell_put(
            symbol="SPXW",
            strike=5475,
            expiration="today",
            quantity=1
        )
        order2 = broker.buy_put(
            symbol="SPXW",
            strike=5470,
            expiration="today",
            quantity=1
        )
        return order1, order2
    
    def close_position(self, position):
        # Buy back sold puts or sell bought calls
        order = broker.buy_put(
            symbol="SPXW",
            strike=position.short_strike,
            quantity=position.quantity
        )
        return order
```

**Task 4: Build Monitoring Dashboard**
- Real-time trade status
- Current P&L
- Greeks (delta, gamma, theta)
- Time to 3:30 PM exit

### Weeks 2-4: Paper Trading

**Daily Execution:**
1. **Pre-market (8:00 AM)**
   - Download market data
   - Check GEX, VIX1D, calendar
   - Prepare analysis

2. **9:30 AM - 10:30 AM**
   - Watch opening range form
   - No trading yet (OR not confirmed)

3. **10:30 AM - 1:00 PM**
   - Evaluate signals
   - If all gates pass + high confluence → Enter trade in paper account
   - Log entry (time, price, credit, max risk)

4. **1:00 PM - 3:30 PM**
   - Monitor position
   - Check profit target, stop loss, time exit
   - Close position when triggered

5. **Post-market (4:00 PM)**
   - Calculate daily metrics
   - Log trade details
   - Update weekly summary

**Tracking Metrics:**

```python
# Daily
{
    "date": "2026-03-05",
    "trades_entered": 2,
    "trades_exited": 2,
    "gates_passed": 2,
    "gates_failed": 0,  # (if signal detected but gate failed)
    "wins": 1,
    "losses": 1,
    "p&l": 50,
}

# Weekly
{
    "week_start": "2026-03-03",
    "total_trades": 9,
    "win_rate": 66.7,
    "p&l": 450,
    "vs_backtest": "+12% ✓ (paper beating backtest)"
}

# Monthly
{
    "month": "March 2026",
    "total_trades": 35,
    "win_rate": 62.3,
    "p&l": 1800,
    "sharpe": 2.1,
    "vs_target": "Expected $2000, got $1800 (-10%, acceptable)"
}
```

**Exit Criteria (Stop Paper Trading If):**
- [ ] Win rate drops below 50% (something is wrong)
- [ ] Gate compliance < 90% (system isn't following rules)
- [ ] 3+ consecutive losing days (investigate)
- [ ] System outage or data lag (fix before live)

**Success Criteria (Ready for Live):**
- [x] 2+ weeks of positive paper P&L
- [x] Win rate ≥ 50% (blended across all trades)
- [x] 100% gate compliance (all 5 gates logged correctly)
- [x] 90%+ stop execution (no failures to exit)
- [x] All rules followed exactly (no discretion)
- [x] System stable (no crashes or lag)

---

## Phase 2: Live Micro (Month 1)

### Transition: From Paper to Live

**Account Setup:**
```
- Live account at broker
- Fund with trading capital (e.g., $25,000)
- Max risk per trade: 1% = $250
- Therefore: Position size = $250 / $430 (max risk) = 0.58 contracts
- Trade size: 1 contract per bot
- Max daily loss: 2% = $500 (then STOP)
```

**Risk Management:**
```
Account Size: $25,000
Max Risk Per Trade: 1% = $250
Max Daily Loss: 2% = $500

One spread (bull put or bear call):
- Width: $5 per contract
- Max loss per contract: $5 - credit

Example trade:
- Sell 5475 put @ $1.50 = $150
- Buy 5470 put @ $0.80 = $80
- Net credit: $70
- Max loss: $5 - $0.70 = $4.30 × 100 = $430 per contract

Safe position size: $250 / $430 = 0.58 contracts → Trade 1 contract
Actual risk: $430 (know max loss upfront)
```

### Daily Execution (Same as Paper)

1. **Pre-market analysis**
2. **Wait for opening range**
3. **Evaluate signals + gates**
4. **Enter if all pass (now with REAL money)**
5. **Monitor + close by 3:30 PM**
6. **Log trade + metrics**

### Success Criteria (Ready to Scale)

- [ ] 50%+ win rate (remove fear)
- [ ] Gate compliance = 100%
- [ ] Stop execution = 90%+ (no hesitation)
- [ ] Zero rule violations
- [ ] Break-even or better (don't need big profits yet)
- [ ] Emotional control (no revenge trading, no skipping gates)

### Pause Criteria (Stop Live If)

- Win rate drops below 40%
- Gate compliance drops below 80%
- Daily loss exceeds 2% (don't lose more on bad days)
- 3+ consecutive losing days → Pause, analyze, restart
- Weekly loss exceeds 5% → Pause and reassess

---

## Phase 3: Live Standard (Months 2+)

### Scale Strategy

**Week 1-2 (Micro: 1 contract)**
- Target: Break-even or 0.5-1% monthly
- Validate everything works

**Week 3-4 (Mini: 2 contracts)**
- Target: 1-2% monthly
- If profitable, increase

**Week 5-8 (Small: 3-5 contracts)**
- Target: 3-8% monthly
- Typical full size for retail account

**Month 3+ (Full Size)**
- Scale based on account size
- Typically 5-10 contracts
- Target: 3-8% monthly, < 10% max drawdown

### Monthly Operations

**Daily (Automated):**
- [ ] Execute trades per signal
- [ ] Close by 3:30 PM
- [ ] Log P&L

**Weekly Review:**
- [ ] Calculate win rate (rolling 20-trade avg)
- [ ] Analyze losers (patterns?)
- [ ] Check GEX filter effectiveness
- [ ] Monitor max drawdown

**Monthly Review:**
- [ ] Total return (target 3-8%)
- [ ] Sharpe ratio (target > 1.5)
- [ ] Max drawdown (target < 10%)
- [ ] Gate compliance (target 100%)
- [ ] Any system issues?

### Red Flags (Pause If):

| Signal | Action |
|--------|--------|
| Win rate < 50% | Pause, analyze past 20 trades |
| Gate compliance < 90% | Fix system immediately |
| Stop execution < 80% | Manual override or system issue |
| Daily loss > 2% | Stop trading for day |
| 3+ consecutive losses | Pause 1 day, analyze |
| Weekly loss > 5% | Pause, deep analysis |
| Monthly loss > 10% | STOP, return to backtest |

---

## Integration Checklist

### Data Pipeline

- [ ] Live SPX prices (hourly)
- [ ] Real-time VIX1D (CBOE)
- [ ] GEX forecast (SpotGamma)
- [ ] Economic calendar (Investing.com API)
- [ ] Options chain data (broker API)
- [ ] Greeks calculation (Black-Scholes)

### Broker API

- [ ] Paper trading enabled
- [ ] Live trading enabled
- [ ] Order placement (sell puts/calls, buy spreads)
- [ ] Position monitoring (P&L, Greeks)
- [ ] Position closing (buy to close, sell to close)
- [ ] Historical trade logging
- [ ] Account balance tracking

### Monitoring & Alerts

- [ ] Gate status dashboard
- [ ] Trade entry alert (Discord/email)
- [ ] Trade exit alert
- [ ] Stop loss trigger alert
- [ ] Daily P&L summary
- [ ] Weekly performance summary
- [ ] Error alerts (system issues)

### Risk Management

- [ ] Position sizing automatic
- [ ] Daily loss limit enforced
- [ ] Mandatory 3:30 PM exit
- [ ] Stop loss on every trade
- [ ] Profit target on every trade
- [ ] Account margin monitoring
- [ ] Emergency close button (manual override)

### Record Keeping

- [ ] Trade database (SQLite or CSV)
- [ ] Daily journal (what happened, lessons)
- [ ] Monthly summary (P&L, metrics, review)
- [ ] Broker statements (audit trail)
- [ ] Gate compliance log (100% audit)
- [ ] System errors log (debugging)

---

## Deployment Timeline Estimate

```
Week 1: Paper trading setup
Week 2: Paper trading validation
Week 3: Live micro decision
Week 4: Live micro 1 contract
Week 5-8: Live mini 2-5 contracts
Month 2+: Live standard scaling

Total: 8-12 weeks from now to full deployment
```

---

## Go/No-Go Decision Points

### Paper Trading → Live Micro

**Go if:**
- [ ] 2+ weeks of positive P&L (or break-even)
- [ ] Win rate ≥ 50%
- [ ] All systems stable
- [ ] 100% gate compliance

**No-Go if:**
- Win rate < 40%
- System failures (crashes, data lag)
- Can't follow rules (tempted to skip gates)

### Live Micro → Live Standard

**Go if:**
- [ ] 4+ weeks of 50%+ win rate
- [ ] P&L ≥ 0 (break-even or better)
- [ ] 100% gate compliance
- [ ] No emotional issues (can handle real money)

**No-Go if:**
- Win rate drops below 40%
- Emotional reactions (revenge trading, skipping gates)
- System issues unresolved

---

## Common Issues & Solutions

### Issue 1: System Lag (Slow Execution)

**Problem:** Orders take 30+ seconds to fill, miss entry prices

**Solution:**
- Upgrade to faster internet
- Use broker's direct order entry (not web)
- Set wider limit price bands
- Consider higher-speed hosting

### Issue 2: Gate Compliance Failing

**Problem:** Trader manually overrides gates ("just this once")

**Solution:**
- Hard-code gates (no manual override option)
- Log every gate override
- Add friction (require 2-step confirmation)
- If you can't follow rules, pause trading

### Issue 3: Win Rate Degrading Over Time

**Problem:** Strategy worked in backtest, fails in live

**Possible causes:**
- Market regime changed (more volatile)
- Slippage worse than expected
- Fills not at expected prices
- Trader getting emotional (skipping losses)

**Solution:**
- Review past 20 trades (are gates still valid?)
- Compare live vs backtest (what's different?)
- Re-run backtest on recent data
- Adjust config if needed (wider strikes, stricter gates)

### Issue 4: Mandatory 3:30 PM Exit Not Happening

**Problem:** "Let me hold through close to see if it works"

**Solution:**
- Automate exit (no manual intervention allowed)
- Set hard stop at 3:29:59 PM ET
- Alert trader at 3:25 PM if position still open
- Don't allow manual exceptions

---

## Success & Celebration

**If you reach this point:**
- Consistent 50%+ win rate
- 3-8% monthly return
- < 10% max drawdown
- 100% rule compliance
- 6+ months live trading

**You've built a real, working trading system.**

Now the work is:
1. Keep it disciplined (no rule violations)
2. Monitor performance (weekly/monthly)
3. Improve gradually (test new parameters in backtest first)
4. Scale gradually (don't risk too much too fast)
5. Keep learning (study your losing trades)

---

**Version:** 4.0  
**Status:** Ready for Paper Trading  
**Next Action:** Set up broker API (Week 1)
**Target Live Date:** 8-12 weeks from now
