# MEMORY.md - Long-Term Memory

## Key Preferences

### Web Browsing
- **When browsing the web, use puppeteer** (via the browser tool)
- This is more reliable than web_search or web_fetch for dynamic content
- Prefer browser automation for research tasks

### Tools & Integrations
- Brave Search API: Not configured (would need setup)
- Browser tool: Available and preferred for web research
- E-Trade API: Not yet set up (Nana will need to configure)

---

## Projects

### 0DTE SPX Trading Strategy (Active)
- **Status:** Backtesting engine built & tested
- **Key insight:** Use puppeteer for web research; real data backtesting works
- **Files:**
  - SPX_0DTE_TRADING_PRD.md (strategy design)
  - 0DTE_RESEARCH_SUMMARY.md (research notes)
  - backtest_engine_realdata.py (NEW: production backtester)
  - BACKTEST_SETUP.md (NEW: documentation)
- **Backtester Features:**
  - Real SPX prices from Yahoo Finance (yfinance)
  - Black-Scholes option pricing with Greeks
  - GEX estimation based on IV rank + realized vol
  - Iron condor 0DTE strategy simulation
  - Metrics: win rate, profit factor, Sharpe ratio, max drawdown
- **Tested:** 2-year backtest (481 trading days, 402 simulated trades)
- **Next phase:** Integrate real CBOE options data + paper trading
- **Critical edge:** GEX filtering (estimated in engine, need real data from SpotGamma.com or CBOE)

---

## Notes for Future Self

- Nana appreciates direct, concise communication
- Keep memory updated with significant decisions and preferences
- When unsure about approach, check this file first
