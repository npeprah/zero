"""
Configuration and constants for SPX 0DTE trading
"""

from enum import Enum
from dataclasses import dataclass


# ============================================================================
# ACCOUNT CONFIGURATION
# ============================================================================

@dataclass
class AccountConfig:
    """Account settings"""
    name: str = "SPX_0DTE_LIVE"
    initial_capital: float = 100000.0
    max_daily_loss_pct: float = 0.02  # 2%
    max_trade_risk_pct: float = 0.01  # 1%
    min_trade_risk_pct: float = 0.005  # 0.5%
    max_daily_trades: int = 6
    max_concurrent_positions: int = 3


# ============================================================================
# TRADING CONFIGURATION
# ============================================================================

@dataclass
class TradingConfig:
    """Trading parameters"""
    # Time windows (in ET)
    market_open: str = "09:30"
    opening_range_start: str = "09:30"
    opening_range_end: str = "10:30"
    entry_start: str = "10:30"
    entry_end: str = "13:00"
    exit_time: str = "15:30"
    market_close: str = "16:00"
    
    # Spread configuration
    spread_width: float = 10.0  # dollars
    target_delta_short: float = 25.0  # 25 delta for short strike
    target_delta_long: float = 15.0  # 15 delta for long strike
    
    # Expected move buffer
    expected_move_buffer_pct: float = 0.10  # 10% of expected move


# ============================================================================
# INDICATOR CONFIGURATION
# ============================================================================

@dataclass
class IndicatorConfig:
    """Indicator parameters"""
    # Moving averages
    sma_period: int = 20
    ema_fast_period: int = 5
    ema_slow_period: int = 40
    
    # Price vs SMA tolerance
    near_sma_threshold_pct: float = 0.003  # 0.3%
    
    # VWAP slope detection
    vwap_slope_lookback_minutes: int = 30
    vwap_slope_threshold_pct: float = 0.001  # 0.1%
    
    # Opening Range
    opening_range_minutes: int = 60


# ============================================================================
# GATE CONFIGURATION
# ============================================================================

@dataclass
class GateConfig:
    """Gate system parameters"""
    # GEX
    gex_fail_threshold: float = 0.0  # Negative GEX = FAIL
    gex_warning_threshold: float = -0.5
    
    # VIX1D
    vix1d_danger_level: float = 25.0  # > 25 = FAIL
    vix1d_warning_level: float = 20.0
    
    # Premium check
    vix1d_premium_rich_threshold_pct: float = 0.0  # > 20-day avg
    
    # Economic calendar
    major_events: list = None  # FOMC, CPI, NFP, etc.
    
    def __post_init__(self):
        if self.major_events is None:
            self.major_events = ['FOMC', 'CPI', 'NFP', 'PPI', 'Fed Speaker', 'FOMC Minutes']


# ============================================================================
# RISK MANAGEMENT
# ============================================================================

@dataclass
class RiskConfig:
    """Risk management settings"""
    # Per-trade stops
    max_delta_for_rebalance: float = 20.0  # If short delta > ±20
    short_delta_reversal_threshold: float = 50.0  # If delta rises > 50% = exit
    
    # Time-based exits
    no_progress_timeout_minutes: int = 60  # Exit if no movement in 60 min
    pre_close_exit_minutes: int = 30  # Close 30 min before market close
    
    # Loss limits
    loss_stop_multiple: float = 2.0  # Close at 2x credit collected loss
    profit_target_min_pct: float = 50.0  # Close at 50% of max profit
    profit_target_max_pct: float = 75.0  # Close at 75% of max profit
    
    # Losing streak rules
    consecutive_loss_threshold: int = 3  # 3 losses in a row = pause
    weekly_loss_threshold_pct: float = 0.05  # 5% = reduce size 50%
    monthly_loss_threshold_pct: float = 0.10  # 10% = cease and review


# ============================================================================
# DEFAULT INSTANCES
# ============================================================================

# Use these as defaults throughout the system
DEFAULT_ACCOUNT = AccountConfig()
DEFAULT_TRADING = TradingConfig()
DEFAULT_INDICATORS = IndicatorConfig()
DEFAULT_GATES = GateConfig()
DEFAULT_RISK = RiskConfig()


# ============================================================================
# PRESET PROFILES
# ============================================================================

class TradingProfile(Enum):
    """Preset trading profiles"""
    CONSERVATIVE = "conservative"  # Smaller size, tighter stops
    MODERATE = "moderate"  # Standard size and stops
    AGGRESSIVE = "aggressive"  # Larger size, wider stops
    PAPER_TRADING = "paper"  # Demo, no real money


def get_profile_config(profile: TradingProfile) -> AccountConfig:
    """Get account config for a profile"""
    
    if profile == TradingProfile.CONSERVATIVE:
        return AccountConfig(
            initial_capital=100000.0,
            max_daily_loss_pct=0.015,  # 1.5% daily max
            max_trade_risk_pct=0.005,  # 0.5% per trade
        )
    
    elif profile == TradingProfile.MODERATE:
        return AccountConfig(
            initial_capital=100000.0,
            max_daily_loss_pct=0.02,  # 2% daily max
            max_trade_risk_pct=0.01,  # 1% per trade
        )
    
    elif profile == TradingProfile.AGGRESSIVE:
        return AccountConfig(
            initial_capital=100000.0,
            max_daily_loss_pct=0.025,  # 2.5% daily max
            max_trade_risk_pct=0.015,  # 1.5% per trade
        )
    
    elif profile == TradingProfile.PAPER_TRADING:
        return AccountConfig(
            name="SPX_0DTE_PAPER",
            initial_capital=100000.0,
            max_daily_loss_pct=0.05,  # More lenient for learning
            max_trade_risk_pct=0.02,
        )
    
    return DEFAULT_ACCOUNT
