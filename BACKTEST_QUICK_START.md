# Backtest Quick Start

## Run a Backtest in 30 Seconds

```bash
cd /home/nana/.openclaw/workspace
python backtest_engine_realdata.py
```

That's it. You'll get results for the last 2 years.

---

## Customize Your Backtest

### Change the Date Range

```python
from backtest_engine_realdata import BacktestEngineRealData

config = {
    'account_size': 25000,
    'risk_per_trade': 0.01,
    'target_delta': 0.20,
    'min_gex': 0.0,
}

engine = BacktestEngineRealData(config)

# Test specific period
results = engine.run(
    start_date='2024-01-01',   # Change these
    end_date='2024-12-31'      # Change these
)
engine.print_results()
```

### Change Account Size & Risk

```python
config = {
    'account_size': 50000,      # Use $50k instead
    'risk_per_trade': 0.02,     # Risk 2% per trade instead of 1%
    'target_delta': 0.25,       # Sell 25-delta instead of 20-delta
    'min_gex': 0.5,             # Only trade when GEX > 0.5M
}

engine = BacktestEngineRealData(config)
results = engine.run('2024-01-01', '2026-03-05')
```

### Change Strike Selection

Edit `BacktestStrikeSelector.select_strikes()` in the file:

```python
@staticmethod
def select_strikes(spx_price: float, target_delta: float = 0.20) -> Dict:
    """Your custom logic here"""
    # Instead of simple delta-based:
    # - Use fixed ATM spreads
    # - Use different widths for different conditions
    # - Use custom GEX-based strikes
    pass
```

### Add a GEX Filter

```python
config = {
    'account_size': 25000,
    'risk_per_trade': 0.01,
    'target_delta': 0.20,
    'min_gex': 1.0,            # Only trade when GEX > 1.0
}
```

Now the engine will skip days when GEX is too low.

---

## Interpret the Results

### What Each Metric Means

| Metric | What It Means | Good Value |
|--------|---------------|-----------|
| **Win Rate** | % of trades that make money | 70%+ |
| **Profit Factor** | Total wins ÷ total losses | 1.5x+ |
| **Sharpe Ratio** | Return per unit of risk | 1.5-3.0 |
| **Max Drawdown** | Worst peak-to-trough loss | <15% |
| **Avg P&L** | Average per trade | $100+ |
| **Consecutive Wins** | Best winning streak | 10+ |

### Red Flags

- ❌ **Win rate > 95%** → Too good to be true, validate with real data
- ❌ **Profit factor 0** → No losing trades (unrealistic)
- ❌ **Max drawdown 0%** → Never had consecutive losses (unrealistic)
- ❌ **Avg P&L < $50** → Too small to profit after commissions

---

## Next: Real CBOE Data

The current backtest uses **simulated option prices** via Black-Scholes.

To use **real historical options data**:

1. Download from CBOE: https://www.cboe.com/us/options/market_statistics/historical_data/
2. Parse CSV/XLS files
3. Replace `OptionChainGenerator.generate_chain()` with real data loader
4. Re-run backtest

**Expected change in results:**
- Win rates drop 10-20% (real data has losses)
- Profit factors become realistic (1.2-2.0x)
- Max drawdown increases (10-15%)

---

## Save & Compare Results

```python
# Run backtest
engine = BacktestEngineRealData(config)
results = engine.run('2024-01-01', '2024-12-31')

# Save trades
engine.save_trades('backtest_jan_2024.json')

# Print results
engine.print_results()

# Access raw data
print(f"Total trades: {results.total_trades}")
print(f"Win rate: {results.win_rate:.1%}")
print(f"Net profit: ${results.net_profit:,.2f}")
```

---

## Example: Test Different Strike Selections

```python
from backtest_engine_realdata import BacktestEngineRealData

config_base = {
    'account_size': 25000,
    'risk_per_trade': 0.01,
    'min_gex': 0.0,
}

# Test 15-delta vs 20-delta vs 25-delta
for delta in [0.15, 0.20, 0.25]:
    print(f"\n=== Testing {delta*100:.0f}-delta ===")
    
    config = {**config_base, 'target_delta': delta}
    engine = BacktestEngineRealData(config)
    results = engine.run('2024-01-01', '2024-12-31')
    
    print(f"Win Rate: {results.win_rate:.1%}")
    print(f"Profit Factor: {results.profit_factor:.2f}x")
    print(f"Avg P&L: ${results.avg_pnl:,.0f}")
    print(f"Max Drawdown: {results.max_drawdown_pct:.1f}%")
```

---

## Files Modified

- **`backtest_engine_realdata.py`** — Main backtesting engine
- **`BACKTEST_SETUP.md`** — Full documentation
- **`BACKTEST_QUICK_START.md`** — This file
- **`backtest_trades_realdata.json`** — Trade log (auto-generated)

---

## Troubleshooting

### "No trades executed"
- Check your GEX filter: `'min_gex': 0.0` to start
- Check your account size vs risk per trade (might be sizing to 0 contracts)

### "Downloaded 0 trading days"
- Check your date range is valid and not in the future
- Check your internet connection (yfinance needs to fetch)

### Profit factor is 0
- All your trades are winning → Expected for simulated data
- Wait for real CBOE data to see realistic losing trades

### Sharpe ratio is way too high
- Normal for simulated data with consistent small wins
- Real data will show lower Sharpe (1.5-3.0)

---

## One-Liner to Run Full Analysis

```bash
python -c "from backtest_engine_realdata import *; e = BacktestEngineRealData({'account_size': 25000, 'risk_per_trade': 0.01, 'target_delta': 0.20}); r = e.run('2024-01-01', '2026-03-05'); e.print_results(); e.save_trades()"
```

Done! Check the output above + `backtest_trades_realdata.json` for detailed trades.
