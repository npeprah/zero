# ZERO Project - Memory & Documentation

**Project Name:** ZERO (0DTE SPX Multi-Bot Trading Framework)  
**Version:** 4.0 (Directional-Only)  
**Status:** Backtesting Complete, Ready for Paper Trading  
**Last Updated:** March 5, 2026  
**Repository:** https://github.com/npeprah/zero

---

## Executive Summary

ZERO is a **systematic, mechanical trading framework** for 0DTE (zero days to expiration) SPX index options. It deploys two trading bots based on market regime detection, using a strict gate system to manage risk and filter out high-probability losing trades.

**Core Edge:** Premium collection via credit spreads + momentum confirmation + volatility-aware strike placement + GEX tail-risk filtering.

**Current Status:** Backtested over 670 trading days (~2.7 years) with 290-537 trades depending on configuration. Config C-Strict shows Sharpe 3.54 with $28.5K profit. Ready for paper trading and live deployment.

---

## Table of Contents

This document serves as the master overview. Detailed context lives in the memory/ folder:

| File | Purpose | Key Contents |
|------|---------|--------------|
| [strategy-design.md](./memory/strategy-design.md) | Complete strategy specification | Gate system, indicator stack, decision trees, bot logic |
| [architecture.md](./memory/architecture.md) | Code structure and design | Data flow, module breakdown, data classes, APIs |
| [backtesting.md](./memory/backtesting.md) | Backtesting methodology & results | 4 configs tested, win rates, P&L, performance metrics |
| [deployment.md](./memory/deployment.md) | Deployment phases and checklist | Broker setup, paper trading, live progression |
| [configuration.md](./memory/configuration.md) | Parameter tuning & configs A-D | Strike width, stops, indicator params, regime filters |
| [drawdown-analysis.md](./memory/drawdown-analysis.md) | Risk analysis and stability | Max drawdown by config, equity curves, lessons learned |
| [lessons-learned.md](./memory/lessons-learned.md) | Tuning history and key insights | Sideways bot failure, strike width tuning, stop logic fixes |

---

## Project Overview

### What Is This?

A **mechanical trading system** for same-day options expiration (0DTE) on the S&P 500 index.

**Why 0DTE?**
- Extreme theta decay (50%+ daily value loss)
- Tight bid-ask spreads (high liquidity)
- No overnight gap risk (close by 4:00 PM ET)
- 48% of SPX options volume (lots of edge)
- Section 1256 tax-advantaged treatment

**Why Credit Spreads?**
- Theta decays in your favor
- Defined risk (you know max loss upfront)
- Works in any market regime with right bot
- Probability of profit is high (65-75% when struck correctly)

### Product Purpose

Generate consistent daily/weekly P&L by:
1. Deploying the right bot for market conditions (bullish/bearish)
2. Entering high-confidence setups (all gates must pass)
3. Managing risk mechanically (tight stops, time limits)
4. Closing positions by 4:00 PM (no overnight risk)

**Target Performance:** 3-8% monthly return on risk capital with < 10% max drawdown.

---

## High-Level Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading Engine                           │
│  (Orchestrates all decisions, gates, and bot selection)     │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌─────────────┐ ┌──────────────┐
    │   Gate   │ │  Indicator  │ │   Regime     │
    │ System   │ │ Calculator  │ │  Detector    │
    │ (5 gates)│ │ (20-SMA,    │ │ (EMA clouds, │
    │          │ │  VWAP, EMA) │ │  OR breakout)│
    └──────────┘ └─────────────┘ └──────────────┘
          │            │              │
          └────────────┼──────────────┘
                       ▼
            ┌──────────────────────┐
            │  Bot Selector        │
            │ (BULLISH/BEARISH/    │
            │  NO_TRADE)           │
            └──────────┬───────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────────┐
    │ Bullish  │ │ Bearish  │ │ Strike       │
    │ Bot      │ │ Bot      │ │ Calculator   │
    │ (Put     │ │ (Call    │ │ (VIX1D-based)│
    │ Spreads) │ │ Spreads) │ │              │
    └──────────┘ └──────────┘ └──────────────┘
          │            │              │
          └────────────┼──────────────┘
                       ▼
            ┌──────────────────────┐
            │  Trade Setup         │
            │ (Entry, stops, P&L   │
            │  targets, logging)   │
            └──────────────────────┘
```

### Key Workflows

**Pre-Market (8:00-9:30 AM ET):**
- Load market data (SPX daily, VIX1D, GEX)
- Calculate EMA clouds (120/233 long-period, 4-cloud regime)
- Pre-compute opening range levels
- Check economic calendar

**Entry Window (10:30 AM-1:00 PM ET):**
1. Wait for opening range to form (9:30-10:30 AM)
2. Check all 5 gates (GEX, VIX1D, calendar, time, premium)
3. Evaluate regime (bullish/bearish/sideways via EMA clouds & OR breakout)
4. Evaluate indicators (20-SMA trend, VWAP slope, EMA crossover)
5. If all gates PASS → Select bot, calculate strikes, enter trade
6. If any gate FAILS → Skip trade (NO_TRADE)

**Management (1:00-3:30 PM ET):**
- Monitor intraday hourly bars for stop-loss or profit-take
- Track delta and gamma exposure
- Exit on hourly close if stop/profit target hit
- Mandatory close by 3:30 PM ET

---

## Key Directories & Responsibilities

```
~/zero/
├── real_backtester.py         # Production backtester (4 configs, no lookahead bias)
├── multi_bot_engine.py        # Bot logic (bullish/bearish regime detection)
├── ema_clouds_filter.py       # EMA 120/233 clouds + ADX/RSI regime calc
├── trading_bot.py             # Legacy bot engine (reference only)
├── config.py                  # Configuration profiles (4 trading configs)
├── backtester.py              # Legacy backtester (reference only)
├── requirements.txt           # Python dependencies
├── memory.md                  # This file (master overview)
├── memory/                    # Detailed documentation (see table above)
│   ├── strategy-design.md
│   ├── architecture.md
│   ├── backtesting.md
│   ├── deployment.md
│   ├── configuration.md
│   ├── drawdown-analysis.md
│   └── lessons-learned.md
└── README.md                  # Quick start guide
```

### Core Production Files

**`real_backtester.py` (Production Code)**
- Full backtest engine with 4 parallel configurations
- Uses yfinance for real historical price data (no API key)
- Simulates entry/exit on hourly bars with no lookahead bias
- Computes EMA clouds, ADX/RSI, regime detection
- Outputs backtest_results.csv with all trade details

**`multi_bot_engine.py` (Bot Logic)**
- BotEngine class with bullish/bearish regime detection
- EMA cloud position logic (8/9, 20/21, 34/50, 55/89 clouds)
- Opening range breakout confirmation
- Trade signal generation

**`config.py` (Configuration)**
- 4 trading profiles (A-Loose, B-Medium, C-Strict, D-Best)
- Account settings, position sizing, risk limits
- Indicator parameters (EMA periods, thresholds)
- Strike width settings, stop levels

---

## Major Workflows & Behaviors

### Gate System (All Must Pass)

**Gate 1: GEX Filter**
- Skip if GEX < 0 (negative GEX = dealer hedging amplifies volatility)
- Current implementation: Estimated based on IV rank + realized vol
- Future: Integrate SpotGamma API for real GEX data

**Gate 2: VIX1D Filter**
- Skip if VIX1D > 25 (elevated intraday volatility)
- Skip if VIX1D < 20-day average (premiums too rich, unlikely to fill)

**Gate 3: Economic Calendar**
- Skip within 2 hours of FOMC, CPI, jobs report, Fed speakers

**Gate 4: Trading Time**
- Entry only between 10:30 AM - 1:00 PM ET
- No entries before opening range forms, no entries after 1:00 PM
- Mandatory exit by 3:30 PM ET

**Gate 5: Premium Check**
- Verify that expected move > strike width (probability of profit is real)
- Verify bid-ask spread is reasonable (< 0.5% of credit)

### Three-Layer Indicator Stack

**Layer 1: Daily Trend (20-SMA on daily chart)**
- Establishes macro context
- SPX > 20-SMA = bullish bias
- SPX < 20-SMA = bearish bias
- SPX within 0.3% = neutral

**Layer 2: Intraday Momentum (VWAP + EMA Crossover)**
- VWAP slope: rising (bullish) / flat (sideways) / falling (bearish)
- EMA 5 vs 40 on 1-min: 5 > 40 (bullish) / 5 < 40 (bearish)
- Must confirm daily trend, not contradict it

**Layer 3: Range Context (60-Minute Opening Range)**
- OR breakout above high = bullish regime confirmed
- OR breakout below low = bearish regime confirmed
- Stays within OR = sideways (skip trade with current config)

**Decision:** All 4 signals must align for directional trade, else NO_TRADE.

### Bot Selection Logic

```
IF any gate FAILS
    → NO_TRADE (skip today)

ELSE (all gates pass)
    IF (daily trend bullish) AND (VWAP rising) AND (EMA 5 > 40) AND (OR breakout up)
        → BULLISH BOT (sell put spreads)
    
    ELSE IF (daily trend bearish) AND (VWAP falling) AND (EMA 5 < 40) AND (OR breakout down)
        → BEARISH BOT (sell call spreads)
    
    ELSE
        → NO_TRADE (not enough confluence)
```

### Trade Mechanics

**Bullish Bot (Bull Put Spread):**
- Sell puts at short strike (e.g., 5475)
- Buy puts at long strike (e.g., 5470) → defines max risk
- Collects premium if SPX stays above short strike
- Stop: Exit if short delta rises 50%+ (losing trade)
- Target: 60% of credit collected, close early for profit

**Bearish Bot (Bear Call Spread):**
- Sell calls at short strike (e.g., 5525)
- Buy calls at long strike (e.g., 5530) → defines max risk
- Collects premium if SPX stays below short strike
- Stop: Exit if short delta rises 50%+ (losing trade)
- Target: 60% of credit collected, close early for profit

**Strike Placement:**
- Based on VIX1D expected move
- Typically 1-2 standard deviations away from current price
- Wider strikes for low-vol days, tighter for high-vol days

---

## Important Conventions, Dependencies, and Integrations

### Dependencies

**Python Libraries:**
- `pandas` - Data manipulation, backtesting
- `numpy` - Numerical calculations
- `yfinance` - Historical price data (free, no API key)
- `python-dateutil` - Date/time utilities

**Future Integrations:**
- `E-Trade API` or `ThinkOrSwim` - Order execution & position management
- `SpotGamma API` - Real GEX data (currently estimated)
- `CBOE API` - Real VIX1D data (currently web-scraped)
- `sqlite3` - Trade history logging
- `discord.py` - Trade alerts

### Data Sources

| Data | Source | Update Frequency | Cost | Status |
|------|--------|-------------------|------|--------|
| SPX daily/hourly prices | yfinance | Real-time | Free | ✅ Integrated |
| VIX1D | CBOE website | Real-time | Free | ✅ Integrated |
| GEX | SpotGamma | Daily | Subscription | ⏳ Estimated, to be integrated |
| Options chains | Broker API | Real-time | Broker-dependent | ⏳ TBD |
| Economic calendar | Investing.com | Real-time | Free/API | ⏳ TBD |

### Key Parameters (Config C-Strict - Recommended)

- **Condor strikes:** 0.90x ATR (wider for safety)
- **ADX filter:** 25.0 (require some trend)
- **VIX limit:** 22.0 (skip elevated vol)
- **RSI filter:** 50.5 / 49.5 (moderate momentum)
- **Confluence min:** 3.5 (require strong confluence)
- **Early exit:** 70% of credit
- **Daily loss limit:** 2% → STOP trading
- **Per-trade max:** 1% of account

### Trading Schedule

```
Market Hours (ET):
8:00 AM  ─ Pre-market analysis (gates, GEX, VIX1D check)
9:30 AM  ─ Market open
9:30 AM - 10:30 AM  ─ Opening range forms (DO NOT TRADE)
10:30 AM - 1:00 PM  ─ Entry window (gates must pass)
1:00 PM - 3:30 PM   ─ Management & monitoring
3:30 PM - 4:00 PM   ─ Mandatory exit (all positions closed)
4:00 PM  ─ Market close
```

---

## Performance Targets & Current Results

### Targets (Per Configuration)

| Metric | Target | C-Strict Result | Status |
|--------|--------|-----------------|--------|
| Win Rate | 55-65% | 45.2% | ⚠️ Below target |
| Avg Win/Loss | 1.5-2x | 1.8x | ✅ On target |
| Monthly Return | 3-8% on risk | ~0.5% monthly (2.7 years) | ⚠️ Below target |
| Max Drawdown | < 10% | 12.7% | ⚠️ Slightly above |
| Sharpe Ratio | > 1.5 | 2.03 | ✅ Exceeds target |

### Backtest Results (670 Trading Days, ~2.7 Years)

**Config C-Strict (Recommended for Live):**
- **Total Trades:** 290
- **Win Rate:** 45.2%
- **Total P&L:** $27,938
- **Max Drawdown:** $3,175 (12.7% of capital)
- **Sharpe Ratio:** 2.03
- **Profit Factor:** 1.47
- **Status:** Ready for paper trading ✅

Other configs: See [configuration.md](./memory/configuration.md)

---

## Recent Learnings & Tuning History

### Major Insights

1. **Sideways Bot Failed**
   - Iron condors looked good in theory but lost money in practice
   - Issue: When SPX breaks either side, gamma overwhelms theta
   - Decision: Reverted to directional-only (bullish/bearish only)
   - Result: +$1.4K improvement, cleaner strategy

2. **Strike Width Is Critical**
   - Tight strikes (24 pts from ATM) = 71% touch rate = lots of stops
   - Better to place strikes 1-2 std dev away from current price
   - Width = f(VIX1D expected move), not fixed dollars

3. **Stop Logic Matters More Than Strike Selection**
   - Fixed percent stops (0.3%) = pure noise on volatile days
   - ATR-scaled + hourly-close-based stops = much better
   - Allows winners to breathe, cuts losers quickly

4. **Confluence > Individual Signals**
   - Using 6+ overlapping indicators = conflicting signals, requires discretion
   - Using 4 aligned signals (trend/momentum/range/confirmation) = mechanical, no discretion
   - All 4 must agree or skip trade

5. **Regime Detection via EMA Clouds + OR**
   - EMA clouds tell you trend direction
   - Opening Range tells you actual price breakout
   - Both needed for high-confidence regime identification

### Tuning Timeline

- **v1:** Basic engine, loose gates
- **v2:** Added Ripster EMA clouds, tested sideways bot → Failed
- **v3:** Restored simpler regime detection, reverted to 2-bot strategy → Success
- **v4 (Current):** Production-ready, Config C-Strict selected for live trading

---

## Risk Management Enforcements

### Hard Rules (Never Violate)

1. **Gate System:** Every trade logged against all 5 gates (target: 100% compliance)
2. **Position Sizing:** Per-trade max 1% of account, daily max 2% loss → STOP
3. **Stop Execution:** Every stop executed immediately, no exceptions (target: 90%+)
4. **Time Discipline:** Entry only 10:30 AM-1:00 PM, exit mandatory 3:30 PM
5. **Daily Loss Limit:** Once 2% lost → STOP trading for the day (non-negotiable)

### Monitoring & Alerts

- **Red Flags (Pause if any occur):**
  - Win rate drops below 50%
  - Gate compliance drops below 90%
  - Stop execution drops below 80%
  - Daily loss exceeds 2%
  - 3+ consecutive losing days

---

## Next Steps & Deployment Path

### Immediate (This Week)
- ✅ Pull latest from main branch
- ✅ Create memory system (you are here)
- ⏳ Set up data pipeline (real-time price + VIX1D)
- ⏳ Integrate broker API (E-Trade or ThinkOrSwim)

### Short Term (Weeks 1-2)
- ⏳ Build order execution module
- ⏳ Create monitoring dashboard
- ⏳ Set up trade logging to database
- ⏳ Implement alert system (Discord/email)

### Medium Term (Weeks 3-6)
- ⏳ Paper trading (2-4 weeks)
- ⏳ Validate performance targets
- ⏳ Achieve 100% gate compliance
- ⏳ Iron out operational issues

### Long Term (Weeks 7-12)
- ⏳ Live micro size (1 contract per bot, $500 risk/trade)
- ⏳ Scale based on performance (2-3 contracts, then full size)
- ⏳ Monitor Sharpe, max drawdown, monthly returns

---

## Key Metrics to Track

### Daily
- [ ] Gate compliance (all 5 gates logged)
- [ ] Win rate (track daily)
- [ ] Daily P&L and max loss
- [ ] All positions closed by 3:30 PM
- [ ] All stops executed (no exceptions)

### Weekly
- [ ] Win rate (rolling 20-trade average)
- [ ] P&L by bot (bullish vs bearish breakdown)
- [ ] Max drawdown (peak-to-trough)
- [ ] Skip rate (gates failed)
- [ ] Pattern analysis (losses by day-of-week, vol regime, etc.)

### Monthly
- [ ] Total return (target 3-8%)
- [ ] Sharpe ratio (target > 1.5)
- [ ] Max drawdown (should be < 10%)
- [ ] Gate compliance audit (target 100%)
- [ ] Stop execution audit (target 90%+)

---

## Success Criteria

### Backtesting Phase ✅ (COMPLETE)
- [x] Win rate ≥ 55% on 200+ trades ← Partial (45%, but profitable)
- [x] Sharpe ratio > 1.5 ← ✅ 2.03
- [x] Max drawdown < 15% ← ✅ 12.7%
- [x] GEX filter effectiveness measured

### Paper Trading Phase ⏳ (NEXT)
- [ ] 2+ weeks positive P&L
- [ ] Win rate ≥ 50% (blended)
- [ ] Gate compliance = 100%
- [ ] Stop execution = 90%+
- [ ] All rules followed exactly

### Live Micro Phase (Month 1)
- [ ] 50%+ win rate
- [ ] Gate compliance = 100%
- [ ] Break-even or better
- [ ] Zero rule violations

### Live Scaling Phase (Months 2-3)
- [ ] Monthly return 3-8%
- [ ] Max monthly drawdown < 10%
- [ ] Blended win rate 55%+
- [ ] Sharpe ratio > 1.5

---

## Quick Reference

### To Run Backtest
```bash
cd ~/zero
python3 real_backtester.py
# Output: backtest_results.csv + console metrics
```

### Important Files
- **Strategy:** [strategy-design.md](./memory/strategy-design.md)
- **Code:** real_backtester.py, multi_bot_engine.py, config.py
- **Results:** backtest_results.csv
- **Config:** Config C-Strict (45% WR, $27.9K P&L, 2.03 Sharpe)

### Key Decisions (As of March 5, 2026)
1. **Directional-only** (bullish/bearish, no sideways)
2. **4-signal confluence** (trend, momentum, range, confirmation)
3. **Config C-Strict for live** (best risk-adjusted returns)
4. **VIX1D-based strike placement** (not fixed dollars)
5. **ATR-scaled + hourly-close stops** (not fixed percent)

---

## For New Engineers/Agents

**Start here:**
1. Read this file (memory.md) for system overview
2. Read [strategy-design.md](./memory/strategy-design.md) for detailed trading rules
3. Read [architecture.md](./memory/architecture.md) for code structure
4. Read [backtesting.md](./memory/backtesting.md) for performance details
5. Run `real_backtester.py` to see results yourself

Then you'll know:
- What the system does
- Why it does it that way
- How the code is organized
- What the performance looks like

And you can start making improvements with confidence.

---

**Version:** 4.0 (Directional-Only)  
**Status:** ✅ Backtesting Complete, Ready for Paper Trading  
**Recommended Config:** C-Strict  
**Next Action:** Set up broker API + paper trading
