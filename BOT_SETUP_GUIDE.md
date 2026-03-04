# SPX 0DTE Bot Setup Guide

**Status:** Task 2 Complete - Bot Framework Ready  
**Date:** March 4, 2026

---

## Overview

The `tastytrade_bot.py` is a production-ready Python bot that:

✅ Authenticates with Tastytrade API  
✅ Fetches live SPX prices & 0DTE option chains  
✅ Checks GEX (Gamma Exposure) filter  
✅ Selects optimal iron condor strikes (20-25 delta)  
✅ Submits orders programmatically  
✅ Logs all trades to JSON  

---

## Installation

### 1. Prerequisites

- Python 3.8+
- pip (Python package manager)
- Tastytrade account with API access (you're setting this up)

### 2. Install Dependencies

```bash
cd /home/nana/.openclaw/workspace
pip install -r requirements.txt
```

**What's installed:**
- `requests` — HTTP library for API calls
- `python-dotenv` — Load credentials from .env file

### 3. Set Up Credentials

Copy the example file and fill in your details:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
nano .env
```

Add your Tastytrade credentials:

```
TASTYTRADE_EMAIL=your_email@example.com
TASTYTRADE_PASSWORD=your_password
TASTYTRADE_ACCOUNT_ID=your_account_id
```

**How to find Account ID:**
1. Log in to Tastytrade
2. Go to Settings → Account
3. Copy your Account ID

---

## Configuration

All settings are in `BotConfig` class in `tastytrade_bot.py`:

### Core Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `ACCOUNT_SIZE` | $25,000 | Your account size |
| `RISK_PER_TRADE` | 1% | Max loss per trade ($250) |
| `TARGET_DELTA` | 0.20 | 20 delta spreads |
| `SPREAD_WIDTH` | $5 | Width of spreads ($5) |

### Time Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `TRADING_START` | 9.5 | 9:30 AM ET (market open) |
| `TRADING_END` | 15.5 | 3:30 PM ET (30 min before close) |
| `MIN_TIME_TO_EXPIRY` | 3 | Need 3+ hours to expiration |

### Risk Management

| Setting | Default | Meaning |
|---------|---------|---------|
| `GEX_CHECK_ENABLED` | True | Check GEX filter |
| `MIN_GEX_VALUE` | 0 | Only trade if GEX >= 0 |
| `PROFIT_TARGET_PCT` | 0.50 | Take 50% of max profit |
| `DELTA_REBALANCE_THRESHOLD` | 0.15 | Max delta per side before rebalance |

### Adjust Settings

Edit `tastytrade_bot.py` in the `BotConfig` section:

```python
@dataclass
class BotConfig:
    # ... change these values ...
    ACCOUNT_SIZE = 50000  # Change to your account size
    RISK_PER_TRADE = 0.02  # 2% risk
    TARGET_DELTA = 0.25  # 25 delta
```

---

## Running the Bot

### Test Mode (Recommended First)

Set `SANDBOX_MODE = True` to paper trade without risk:

```bash
python tastytrade_bot.py
```

**What happens:**
1. Authenticates with Tastytrade
2. Initializes account
3. Checks if market is open
4. Gets SPX price
5. Checks GEX
6. Selects strikes
7. Submits **mock** order (no real money)
8. Logs trade to `trades_log.json`

### Live Mode (After Validation)

Once paper trading works, set `SANDBOX_MODE = False`:

```python
config.SANDBOX_MODE = False  # NOW IT'S REAL
```

Then run again:

```bash
python tastytrade_bot.py
```

---

## Scheduled Execution (Cron)

Run bot automatically every trading day:

### Option 1: Cron Job (Linux/Mac)

```bash
crontab -e
```

Add line:

```
# Run bot at 9:35 AM ET every weekday
35 09 * * 1-5 /usr/bin/python3 /home/nana/.openclaw/workspace/tastytrade_bot.py >> /home/nana/.openclaw/workspace/bot.log 2>&1
```

### Option 2: OpenClaw Cron

Use OpenClaw's built-in cron scheduler:

```bash
# Create recurring job (every day at 9:35 AM ET)
openclaw cron add --name "SPX 0DTE Bot" --schedule "cron" --expr "35 9 * * *" --payload '{"kind": "systemEvent", "text": "Run bot"}'
```

---

## Monitoring & Logging

### Log Files

**Console output:**
```
2026-03-04 10:15:32 - __main__ - INFO - ============================================================
2026-03-04 10:15:32 - __main__ - INFO - Daily check: 2026-03-04 10:15:32
2026-03-04 10:15:32 - __main__ - INFO - SPX Price: $5,500.25
2026-03-04 10:15:33 - __main__ - INFO - GEX: 1,250,000
2026-03-04 10:15:33 - __main__ - INFO - ✓ GEX check passed
```

**File logs:**
- `0dte_bot.log` — All bot activity
- `trades_log.json` — All trades (timestamp, strikes, P&L)

### View Logs

```bash
# Watch bot log in real-time
tail -f 0dte_bot.log

# View trades
cat trades_log.json | python -m json.tool
```

---

## Bot Architecture

### Classes

**TastytradeAuth**
- Handles OAuth authentication
- Stores session token

**TastytradeData**
- Fetches SPX quote
- Gets option chains
- Retrieves expiration dates

**GEXFilter**
- Polls SpotGamma.com
- Blocks trades if GEX < threshold

**GreeksCalculator**
- Black-Scholes Greeks calculation
- Delta, Gamma, Theta

**StrikeSelector**
- Binary search to find target-delta strikes
- Selects call/put spreads

**OrderExecutor**
- Submits multi-leg orders
- Closes positions
- Retrieves P&L

**SPX0DTEBot**
- Main orchestrator
- Runs daily checks
- Logs trades

---

## Typical Daily Flow

### 9:30 AM - Market Open
Bot checks:
1. Is market open? ✓
2. What's the SPX price? ($5,500)
3. What's the GEX? (1.2M, > 0) ✓
4. What expires today? (SPX 2026-03-04)

### 9:35 AM - Strike Selection
Bot calculates:
1. Time to expiration: 6 hours 25 minutes
2. Volatility: 18%
3. 20-delta call strike: $5,520
4. 20-delta put strike: $5,480

### 9:36 AM - Order Submission
Bot submits iron condor:
```
SELL 1 SPX 5520 Call (20-delta)
BUY  1 SPX 5525 Call (15-delta)
SELL 1 SPX 5480 Put (20-delta)
BUY  1 SPX 5475 Put (15-delta)
```

Credit received: $0.75 per contract = $75 total  
Max profit: $75  
Max loss: $425 (width $5 - credit $0.75)  
Risk/Reward: $425 to make $75 (17% return)

### 3:30 PM - Exit Check
Bot checks P&L:
- Current profit: $50 (67% of max)
- Closes position automatically

---

## Troubleshooting

### "Authentication failed"
```
✗ Authentication failed: [Errno -2] Name or service not known
```
**Fix:** Check credentials in `.env` file

### "No 0DTE expiration found"
```
✗ No 0DTE expiration found
```
**Possible causes:**
- Markets are closed
- It's a weekend/holiday
- SPX options aren't trading
**Fix:** Check market calendar

### "Failed to fetch GEX"
```
✗ Failed to fetch GEX: Connection timeout
```
**Fix:** SpotGamma.com is temporarily down; bot continues with warning

### "Order submission failed"
```
✗ Order submission failed: Insufficient buying power
```
**Fix:** Account doesn't have enough margin for trade. Reduce `RISK_PER_TRADE` or increase account size.

---

## Next Steps

### Phase 2: Paper Trading (You do this)

1. **Create Tastytrade account**
   - Go to tastytrade.com
   - Sign up (takes ~15 minutes)
   - Wait for approval (24-48 hours)

2. **Request API access**
   - Log in to Tastytrade
   - Go to Settings → API Access
   - Create application
   - Get credentials (Email, Password, Account ID)

3. **Copy credentials to `.env`**
   ```bash
   TASTYTRADE_EMAIL=your_email
   TASTYTRADE_PASSWORD=your_password
   TASTYTRADE_ACCOUNT_ID=your_account_id
   ```

4. **Test bot in sandbox**
   ```bash
   python tastytrade_bot.py
   ```
   Should output trade log without real money

5. **Paper trade for 1-2 weeks**
   - Run bot daily
   - Monitor `trades_log.json`
   - Track win rate, avg win/loss

6. **Review results**
   - If 70%+ win rate: move to live
   - If < 70%: adjust settings and repeat

---

## Safety Checklist

**Before going live:**

- [ ] Tested bot in sandbox mode
- [ ] Paper traded for 5+ days
- [ ] Reviewed all trades in `trades_log.json`
- [ ] Win rate is 70%+
- [ ] Understand max loss per trade
- [ ] Can afford to lose account
- [ ] Have backup funds for margin calls
- [ ] Credentials are secure (`.env` in `.gitignore`)

---

## Advanced Configuration

### Custom Greeks Model

The bot uses Black-Scholes Greeks. To use real API Greeks:

1. Fetch Greeks from Tastytrade API: `get_option_chains()`
2. Replace `GreeksCalculator.calculate_delta()` with API data
3. Update `StrikeSelector` to use real IV

### Dynamic Position Sizing

Modify `OrderExecutor.submit_iron_condor()` to:
- Increase size on low IV
- Decrease size on high IV
- Risk more on high GEX days

### Multi-Leg Management

Add `gamma_scalp()` method to:
- Monitor delta during day
- Rebalance if delta exceeds threshold
- Execute small hedge trades

---

## Support

**Issues?**
- Check `0dte_bot.log` for error details
- Verify `.env` credentials
- Test API connection manually

**Questions?**
- Review tastytrade API docs: https://tastytrade.com/api
- Check SpotGamma GEX data: https://spotgamma.com

---

## Files

```
/home/nana/.openclaw/workspace/
├── tastytrade_bot.py          ← Main bot (23KB)
├── requirements.txt            ← Dependencies
├── .env.example               ← Credentials template
├── .env                       ← Your credentials (don't commit!)
├── 0dte_bot.log              ← Daily logs
├── trades_log.json           ← All trades
└── BOT_SETUP_GUIDE.md        ← This file
```

---

**Ready to start paper trading?** Set up your Tastytrade account and let's go! ⚡
