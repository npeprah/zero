# Architecture - Code Structure & Design

**Version:** 4.0  
**Status:** Production Ready

---

## Overview

The ZERO framework is organized around a **central TradingEngine** that orchestrates all decisions. Data flows through specialized calculators and detectors, then reaches a bot selector that determines which bot (BULLISH/BEARISH/NO_TRADE) to deploy.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    TradingEngine                            │
│     (Main orchestrator, decision coordination)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌─────────────┐ ┌──────────────┐
    │  Gate    │ │ Indicator   │ │   Regime     │
    │ System   │ │ Calculator  │ │  Detector    │
    │          │ │             │ │              │
    │ 5 gates: │ │ Calcs:      │ │ Calcs:       │
    │ - GEX    │ │ - 20-SMA    │ │ - EMA clouds │
    │ - VIX1D  │ │ - VWAP      │ │ - ADX/RSI    │
    │ - Cal    │ │ - EMA 5/40  │ │ - OR breakout│
    │ - Time   │ │             │ │              │
    │ - Prem   │ │             │ │              │
    └──────────┘ └─────────────┘ └──────────────┘
          │            │              │
          └────────────┼──────────────┘
                       ▼
            ┌──────────────────────┐
            │   BotSelector        │
            │ (Confluence logic)   │
            │ Returns:             │
            │ BULLISH/BEARISH/     │
            │ NO_TRADE             │
            └──────────┬───────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────────┐
    │ Bullish  │ │ Bearish  │ │ Strike       │
    │ Bot      │ │ Bot      │ │ Calculator   │
    │ (PUT)    │ │ (CALL)   │ │              │
    │          │ │          │ │ Calcs:       │
    │ Returns: │ │ Returns: │ │ - Strikes    │
    │ Trade    │ │ Trade    │ │   based on   │
    │ Setup    │ │ Setup    │ │   VIX1D      │
    │          │ │          │ │              │
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

---

## Core Files

### 1. `real_backtester.py` (Production Code)

**Size:** ~700 lines  
**Purpose:** Run 4 parallel configurations on historical data with no lookahead bias

**Key Classes:**

```python
class BotType(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NO_TRADE = "NO_TRADE"

class DataSet:
    """Holds OHLCV + indicators for backtesting"""
    dates: List[date]
    spx_open, spx_high, spx_low, spx_close, spx_volume
    vix1d, gex_forecast
    ema_120, ema_233, atr, adx, rsi

class TradeRecord:
    """Single trade details"""
    entry_date, entry_time, entry_price
    exit_date, exit_time, exit_price
    bot_type, short_strike, long_strike
    credit, max_risk
    profit_loss
    exit_reason (PROFIT/LOSS/TIME)
    gates (all 5 logged)

class BacktestConfig:
    """Parameter set for one config variant"""
    name: str  # "A-Loose", "B-Medium", "C-Strict", "D-Best"
    condor_strike_width: float  # ATR multiple
    adx_filter: float
    vix_limit: float
    rsi_filter: float
    confluence_min: float
    early_exit_pct: float

class BacktestEngine:
    """Main engine"""
    def run(self) -> BacktestResults
    def evaluate_signals(date) -> BotType
    def execute_trade(bot) -> TradeRecord
    def calculate_metrics() -> BacktestResults
```

**Data Flow:**

```
1. Load data (yfinance): SPX hourly/daily, VIX1D
2. Calculate indicators (EMA clouds, ADX, RSI, OR levels)
3. For each trading day D:
   a. Load market data for D (only data BEFORE D, no lookahead)
   b. Evaluate regime + signals
   c. If gates pass + signals align → enter trade
   d. Simulate entry at 11:00 AM, monitor hourly, exit at 3:30 PM
   e. Record trade + P&L
4. Calculate metrics (win rate, Sharpe, drawdown, etc.)
5. Output backtest_results.csv
```

**Key Method: `evaluate_signals(date)`**

```python
def evaluate_signals(self, date):
    # Check all 5 gates
    if not self.check_gex(date):
        return BotType.NO_TRADE
    if not self.check_vix1d(date):
        return BotType.NO_TRADE
    if self.is_economic_event(date):
        return BotType.NO_TRADE
    if not self.is_trading_time(date):
        return BotType.NO_TRADE
    if not self.check_premium(date):
        return BotType.NO_TRADE
    
    # All gates pass, check regime
    regime = self.detect_regime(date)  # BULLISH/BEARISH/SIDEWAYS
    
    # Check 4-signal confluence
    confluence = self.count_bullish_signals(date)
    
    if regime == "BULLISH" and confluence >= 3:
        return BotType.BULLISH
    elif regime == "BEARISH" and confluence >= 3:
        return BotType.BEARISH
    else:
        return BotType.NO_TRADE
```

### 2. `multi_bot_engine.py` (Bot Logic)

**Size:** ~300 lines  
**Purpose:** Regime detection + bot selection logic

**Key Classes:**

```python
class MultiBot:
    """Regime detection and bot selection"""
    
    def detect_regime(self, df_day) -> Regime:
        """Uses EMA clouds + ADX/RSI"""
        # Check 4-cloud position (8/9, 20/21, 34/50, 55/89)
        # If all clouds stacked bullish → BULLISH
        # If all clouds stacked bearish → BEARISH
        # Else → SIDEWAYS (current: skip, NO_TRADE)
        
    def check_or_breakout(self, price, or_high, or_low) -> Direction:
        """Price vs opening range"""
        if price > or_high:
            return Direction.BULLISH
        elif price < or_low:
            return Direction.BEARISH
        else:
            return Direction.NEUTRAL
    
    def select_bot(self, regime, signals) -> BotType:
        """Confluence logic"""
        if regime == BULLISH and all_signals_bullish():
            return BotType.BULLISH
        elif regime == BEARISH and all_signals_bearish():
            return BotType.BEARISH
        else:
            return BotType.NO_TRADE

class BullishBot:
    """Bull put spread logic"""
    def create_setup(self, spx_price, vix1d) -> TradeSetup
    def calculate_strikes(self, spx_price, vix1d) -> (short, long)
    def calculate_credit(self, strikes) -> float

class BearishBot:
    """Bear call spread logic"""
    def create_setup(self, spx_price, vix1d) -> TradeSetup
    def calculate_strikes(self, spx_price, vix1d) -> (short, long)
    def calculate_credit(self, strikes) -> float
```

### 3. `ema_clouds_filter.py` (Indicator Calculation)

**Size:** ~400 lines  
**Purpose:** EMA cloud calculation + regime detection

**Key Functions:**

```python
def calculate_ema_clouds(df):
    """Calculate 4 cloud levels"""
    ema_8 = df['close'].ewm(span=8).mean()
    ema_9 = df['close'].ewm(span=9).mean()
    ema_20 = df['close'].ewm(span=20).mean()
    ema_21 = df['close'].ewm(span=21).mean()
    ema_34 = df['close'].ewm(span=34).mean()
    ema_50 = df['close'].ewm(span=50).mean()
    ema_55 = df['close'].ewm(span=55).mean()
    ema_89 = df['close'].ewm(span=89).mean()
    
    return ema_8, ema_9, ema_20, ema_21, ema_34, ema_50, ema_55, ema_89

def detect_regime_from_clouds(price, clouds):
    """Check if clouds are bullish, bearish, or sideways"""
    cloud1_bullish = cloud1_lower < cloud1_upper
    cloud2_bullish = cloud2_lower < cloud2_upper
    cloud3_bullish = cloud3_lower < cloud3_upper
    cloud4_bullish = cloud4_lower < cloud4_upper
    
    if all([cloud1_bullish, cloud2_bullish, cloud3_bullish, cloud4_bullish]):
        return "BULLISH"
    elif not any([...]):
        return "BEARISH"
    else:
        return "SIDEWAYS"

def calculate_adx_rsi(df):
    """Supporting regime indicators"""
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    rsi = ta.rsi(df['close'], length=14)
    return adx, rsi
```

### 4. `config.py` (Configuration)

**Size:** ~200 lines  
**Purpose:** Parameter sets for all 4 configs

**Structure:**

```python
@dataclass
class TradingConfig:
    name: str
    # Strike settings
    condor_strike_atrs: float  # 0.75x, 0.80x, 0.85x, 0.90x
    early_exit_pct: float     # 60%, 70%, etc
    
    # Regime filters
    adx_min: float            # 20, 25, 30, 35
    vix_limit: float          # 22, 25, 30, 35
    
    # Indicator filters
    rsi_bullish: float        # 50-55 range
    rsi_bearish: float        # 45-50 range
    
    # Trade logic
    confluence_min: float     # 2.5, 3.0, 3.5, 4.0
    di_gap_min: float         # 0, 2, 4, 6

# Four pre-defined configs
CONFIGS = {
    'A': TradingConfig(name='A-Loose', ...),
    'B': TradingConfig(name='B-Medium', ...),
    'C': TradingConfig(name='C-Strict', ...),
    'D': TradingConfig(name='D-Best', ...),
}
```

---

## Data Classes (Contracts)

All data passed between components uses explicit data classes:

```python
@dataclass
class IndicatorValues:
    """Daily indicators"""
    sma_20: float
    vwap: float
    vwap_slope: str  # "rising" / "flat" / "falling"
    ema_5: float
    ema_40: float
    ema_signal: str  # "bullish" / "bearish" / "flat"
    price_vs_sma: str  # "above" / "below" / "near"

@dataclass
class VIX1DData:
    """Volatility context"""
    vix1d: float
    vix1d_20day_avg: float
    expected_move_points: float
    is_rich_premiums: bool
    is_normal_vol: bool

@dataclass
class GateStatus:
    """All 5 gates"""
    gex: bool
    vix1d: bool
    calendar: bool
    time: bool
    premium: bool
    
    @property
    def all_pass(self):
        return all([self.gex, self.vix1d, self.calendar, self.time, self.premium])

@dataclass
class TradeSetup:
    """Ready to trade"""
    bot_type: BotType
    short_strike: float
    long_strike: float
    width: float
    credit: float
    max_risk: float
    entry_time: str
    stop_delta: float
    profit_target: float
```

---

## Key Interfaces

### Gate System Interface

```python
class GateSystem:
    def check_gex(self, gex_value: float) -> bool
    def check_vix1d(self, vix1d: float, vix1d_20avg: float) -> bool
    def check_economic_calendar(self, date: date) -> bool
    def check_time(self, current_time: time) -> bool
    def check_premium(self, vix1d, strike_width) -> bool
    
    def check_all_gates(self, market_data) -> GateStatus:
        """Convenience method"""
```

### Indicator Calculator Interface

```python
class IndicatorCalculator:
    def calculate_sma(self, prices: List[float], period: int) -> float
    def calculate_vwap(self, intraday_bars) -> float
    def calculate_vwap_slope(self) -> str
    def calculate_ema(self, prices: List[float], period: int) -> float
    def get_all_indicators(self, market_data) -> IndicatorValues
```

### Regime Detector Interface

```python
class RegimeDetector:
    def detect_regime(self, market_data) -> Regime
    def get_or_levels(self, date) -> (high, low)
    def check_or_breakout(self, price, or_high, or_low) -> Direction
```

### Bot Selection Interface

```python
class BotSelector:
    def evaluate_confluence(self, 
                           daily_trend: str,
                           vwap_signal: str,
                           ema_signal: str,
                           or_breakout: str) -> int  # 0-4
    def select_bot(self, 
                   gates: GateStatus,
                   indicators: IndicatorValues,
                   regime: Regime) -> BotType
```

---

## Data Flow During Backtesting

```
1. INITIALIZATION
   ├─ Load config (C-Strict parameters)
   ├─ Create BotSelector with config
   ├─ Create BacktestEngine with 670 trading days
   └─ Initialize empty TradeLog

2. FOR EACH TRADING DAY D:
   ├─ Load ONLY data available BEFORE day D (no lookahead)
   │  ├─ SPX daily closes (for 20-SMA)
   │  ├─ SPX hourly OHLC (for entry/exit)
   │  ├─ VIX1D
   │  ├─ GEX forecast
   │  └─ Economic calendar
   │
   ├─ CALCULATE INDICATORS (using only data up to D-1)
   │  ├─ 20-SMA on daily
   │  ├─ EMA 120/233 daily (for clouds + ADX/RSI)
   │  ├─ Opening Range (9:30-10:30 AM on day D)
   │  └─ VWAP/EMA 5/40 (intraday on day D)
   │
   ├─ CHECK ALL 5 GATES
   │  ├─ GEX forecast for day D
   │  ├─ VIX1D level
   │  ├─ Economic calendar (any events?)
   │  ├─ Is trading time (10:30 AM-1:00 PM)?
   │  └─ Premium check (expected move vs width)
   │
   ├─ IF ANY GATE FAILS
   │  └─ Log NO_TRADE → Continue to next day
   │
   ├─ IF ALL GATES PASS
   │  ├─ DETECT REGIME
   │  │  ├─ Check EMA clouds bullish/bearish/sideways
   │  │  └─ Check OR breakout direction
   │  │
   │  ├─ EVALUATE 4-SIGNAL CONFLUENCE
   │  │  ├─ Daily trend vs 20-SMA
   │  │  ├─ VWAP slope
   │  │  ├─ EMA 5 vs 40
   │  │  └─ OR breakout
   │  │
   │  ├─ SELECT BOT
   │  │  ├─ If all 4 signals bullish → BULLISH BOT
   │  │  ├─ Else if all 4 signals bearish → BEARISH BOT
   │  │  └─ Else → NO_TRADE
   │  │
   │  ├─ IF BOT SELECTED
   │  │  ├─ CALCULATE STRIKES
   │  │  │  ├─ Use VIX1D expected move
   │  │  │  ├─ Short strike = ATM ± (0.8 * expected move)
   │  │  │  └─ Long strike = short ± 5 (width)
   │  │  │
   │  │  ├─ SIMULATE ENTRY (11:00 AM on day D)
   │  │  │  ├─ Price SPX at 11:00 AM
   │  │  │  ├─ Estimate credit collected
   │  │  │  ├─ Set max risk = width - credit
   │  │  │  └─ Log entry
   │  │  │
   │  │  ├─ SIMULATE MANAGEMENT (hourly from 11:00 AM to 3:30 PM)
   │  │  │  ├─ Check profit target (60% credit closed)
   │  │  │  ├─ Check stop loss (delta rises 50%+)
   │  │  │  ├─ Check time (3:30 PM exit)
   │  │  │  └─ Update P&L each hour
   │  │  │
   │  │  ├─ LOG TRADE
   │  │  │  ├─ Entry time, entry price
   │  │  │  ├─ Exit time, exit price, exit reason
   │  │  │  ├─ Short/long strikes
   │  │  │  ├─ Credit, max risk, actual P&L
   │  │  │  └─ All 5 gate statuses
   │  │  │
   │  │  └─ UPDATE RUNNING METRICS
   │  │     ├─ Total trades++
   │  │     ├─ If P&L > 0: wins++
   │  │     ├─ Update max drawdown
   │  │     └─ Update cumulative P&L
   │
   └─ Continue to next day

3. FINALIZE METRICS
   ├─ Win rate = wins / total_trades
   ├─ Profit factor = sum_wins / abs(sum_losses)
   ├─ Sharpe ratio = annual_return / annual_volatility
   ├─ Max drawdown = peak - trough (from all trades)
   ├─ Sort trades, analyze winners/losers
   └─ Output backtest_results.csv
```

---

## Testing & Validation

### Unit Tests (Recommended)

```python
def test_gate_gex():
    gate = GateSystem()
    assert gate.check_gex(0.5) == True
    assert gate.check_gex(-0.2) == False

def test_confluence_logic():
    selector = BotSelector()
    signals = ["BULLISH", "BULLISH", "BULLISH", "BEARISH"]
    assert selector.count_confluence(signals) == 3

def test_strike_placement():
    bot = BullishBot()
    strikes = bot.calculate_strikes(spx=5500, vix1d=20)
    assert strikes.short < 5500
    assert strikes.long < strikes.short
```

### Backtest Validation

- **No lookahead bias:** Indicators calculated only using data before trade date
- **Realistic slippage:** Entry at bid-ask midpoint, 1% slippage on exits
- **Commission:** 0% (conservative, real commission helps returns)
- **Position sizing:** Fixed 1% risk per trade
- **Mandatory exits:** No positions held overnight

---

## Future Enhancements

### API Integration
- Real E-Trade order execution
- Live option chains
- Real-time GEX (SpotGamma API)
- Real-time economic calendar (Investing.com)

### Monitoring
- Discord alerts on trades
- Daily P&L email
- Live equity curve dashboard
- Heat map of results by day-of-week, vol regime

### Risk Management
- Database logging of all trades
- Automatic hedge positions
- Portfolio Greeks (delta, gamma, vega)
- Correlation across bots

---

**Version:** 4.0  
**Status:** Production-Ready  
**Next:** Broker API integration
