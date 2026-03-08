# ZERO Project Status

**Working Directory:** `~/zero`  
**Last Updated:** 2026-03-05  
**Status:** Active development — backtesting engine functional, tuning in progress

## What Is This?

0DTE SPX multi-bot trading strategy with real historical backtesting engine. Simulates entry/exit on hourly bars with no lookahead bias.

## Current Files

### Core Engine
- **real_backtester.py** — Production backtester (4 bot configs tested in parallel)
- **multi_bot_engine.py** — Bot logic (bullish, bearish, sideways, no-trade)
- **ema_clouds_filter.py** — EMA 120/233 cloud + ADX/RSI regime detection
- **backtester.py** — Legacy version (keep for reference)
- **trading_bot.py** — Trade execution logic

### Configuration
- **config.py** — Bot parameters (entry times, strike widths, stops)
- **CONFIG_EXPLANATION.md** — Detailed parameter guide

### Strategy Docs
- **SPX_0DTE_TRADING_PRD_v4.md** — Full PRD (strategy design, rationale)
- **IMPLEMENTATION_SUMMARY.md** — Architecture overview
- **DEPLOYMENT_CHECKLIST.md** — Production readiness guide

### Analysis & Findings
- **backtest_results.csv** — Raw backtest output (481 trading days)
- **DRAWDOWN_EXPLAINED.md** — Max drawdown analysis
- **SIDEWAYS_RESTORATION_ANALYSIS.md** — Sideways bot tuning notes
- **SIDEWAYS_BOT_REVERT.md** — Historical revert doc

## Latest Results

**Config:** Real Backtester (multi-bot, 4 variants)  
**Period:** 481 trading days (~2 years)  
**Trades:** 402 completed  
**Metrics:**
- Win Rate: Variant dependent (see backtest_results.csv)
- Profit Factor: TBD on latest run
- Sharpe Ratio: TBD on latest run
- Max Drawdown: Analyzed in DRAWDOWN_EXPLAINED.md

## Next Steps

1. **Current Focus:** Validate sideways bot tuning + finalize parameter set
2. **Real Data Integration:** Fetch actual CBOE options data for better Greeks (currently using Black-Scholes estimate)
3. **GEX Filtering:** Integrate SpotGamma or CBOE GEX data for pinpoint entry timing
4. **Paper Trading:** Set up E-Trade API for live paper trading (no real capital)
5. **Deployment:** Push to production once paper trading validates

## How to Use

```bash
cd ~/zero
python3 real_backtester.py
```

Output: backtest_results.csv + console metrics

## Key Insights

- **Strike Width:** Condors at 24 pts from ATM were too tight (71% touch rate)
- **Stop Logic:** Hourly-close-based + ATR-scaled stops outperform fixed percent
- **Regime Filter:** EMA clouds + ADX/RSI significantly reduce false signals
- **Time Value:** Condors by 3:30 PM avg +$222 → strikes are sound, execution matters

## Team

- **Strategy:** Nana
- **Implementation:** Chief (AI)
- **Backtesting:** real_backtester.py (v1 tuning complete, multi-config testing)

---

**Remember:** All work happens here (`~/zero`), not in ~/.openclaw/workspace. Keep this directory clean and git-tracked.
