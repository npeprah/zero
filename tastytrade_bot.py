#!/usr/bin/env python3
"""
SPX 0DTE Iron Condor Trading Bot
Tastytrade API Integration
"""

import os
import json
import logging
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import math

from ema_clouds_filter import EMACloudsFilter, MarketRegime
from multi_bot_engine import MultiBotEngine, BotType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('0dte_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIG & CREDENTIALS
# ============================================================================

@dataclass
class BotConfig:
    """Bot configuration"""
    # Tastytrade API
    API_BASE_URL = "https://api.tastyworks.com"
    SANDBOX_MODE = True  # Set to False for live trading
    
    # Trading params
    ACCOUNT_SIZE = 25000  # Account size in dollars
    RISK_PER_TRADE = 0.01  # 1% risk per trade
    TARGET_DELTA = 0.20  # 20 delta spreads
    SPREAD_WIDTH = 5  # $5 wide spreads
    
    # Time params
    TRADING_START = 9.5  # 9:30 AM ET
    TRADING_END = 15.5  # 3:30 PM ET (30 min before close)
    MIN_TIME_TO_EXPIRY = 3  # 3+ hours
    
    # GEX params
    GEX_CHECK_ENABLED = True
    MIN_GEX_VALUE = 0  # Only trade if GEX >= 0

    # EMA Clouds (Ripster MTF) params
    EMA_CLOUDS_ENABLED = True
    # Only enter iron condor when regime is SIDEWAYS or UNKNOWN
    # Set to False to allow trading in any detected regime (still logs regime)
    EMA_CLOUDS_REQUIRE_SIDEWAYS = True
    # Minimum confluence score (0-3) required for directional regime to BLOCK trade
    # e.g. score=2 means: only skip if 2+ timeframes confirm bearish/bullish
    EMA_CLOUDS_MIN_CONFIDENCE = 2
    
    # Risk management
    MAX_LOSS_PER_TRADE = None  # Calculated based on RISK_PER_TRADE
    PROFIT_TARGET_PCT = 0.50  # Take 50% of max profit
    DELTA_REBALANCE_THRESHOLD = 0.15  # 15 delta max per side
    
    def __post_init__(self):
        self.MAX_LOSS_PER_TRADE = self.ACCOUNT_SIZE * self.RISK_PER_TRADE


class TastytradeAuth:
    """Handle Tastytrade API authentication"""
    
    def __init__(self, session_token: str = None, config: BotConfig = None):
        self.config = config or BotConfig()
        self.session_token = session_token
        self.refresh_token = None
        self.auth_header = None
        
    def authenticate(self, email: str, password: str) -> bool:
        """
        Authenticate with Tastytrade API
        
        Args:
            email: Tastytrade account email
            password: Tastytrade account password
            
        Returns:
            bool: True if successful
        """
        try:
            url = f"{self.config.API_BASE_URL}/auth/login"
            payload = {
                "login": email,
                "password": password,
                "remember-me": True
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            self.session_token = data.get('session_token')
            self.refresh_token = data.get('refresh_token')
            self.auth_header = {'Authorization': f'Bearer {self.session_token}'}
            
            logger.info("✓ Authenticated with Tastytrade")
            return True
            
        except Exception as e:
            logger.error(f"✗ Authentication failed: {e}")
            return False
    
    def get_headers(self) -> Dict:
        """Get auth headers for API requests"""
        return self.auth_header or {}


# ============================================================================
# DATA FETCHING
# ============================================================================

class TastytradeData:
    """Fetch data from Tastytrade API"""
    
    def __init__(self, auth: TastytradeAuth, config: BotConfig = None):
        self.auth = auth
        self.config = config or BotConfig()
    
    def get_account_info(self, account_id: str) -> Optional[Dict]:
        """Get account balance and buying power"""
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{account_id}"
            response = requests.get(url, headers=self.auth.get_headers())
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None
    
    def get_spx_quote(self) -> Optional[float]:
        """Get current SPX price"""
        try:
            url = f"{self.config.API_BASE_URL}/quote-streamer"
            params = {'symbols': 'SPX'}
            response = requests.get(url, params=params, headers=self.auth.get_headers())
            response.raise_for_status()
            
            data = response.json()
            if 'data' in data:
                return data['data'].get('last', None)
            return None
        except Exception as e:
            logger.error(f"Failed to get SPX quote: {e}")
            return None
    
    def get_option_chains(self, symbol: str = 'SPX') -> Optional[List[Dict]]:
        """
        Get SPX 0DTE option chain
        
        Returns:
            List of option contracts with Greeks
        """
        try:
            url = f"{self.config.API_BASE_URL}/option-chains"
            params = {
                'symbol': symbol,
                'include-quotes': 'true',
                'include-greeks': 'true'
            }
            response = requests.get(url, params=params, headers=self.auth.get_headers())
            response.raise_for_status()
            
            data = response.json()
            return data.get('items', [])
        except Exception as e:
            logger.error(f"Failed to get option chain: {e}")
            return None
    
    def get_0dte_expiration(self) -> Optional[str]:
        """Get 0DTE (today's) expiration date"""
        try:
            url = f"{self.config.API_BASE_URL}/option-expirations"
            params = {'symbol': 'SPX'}
            response = requests.get(url, params=params, headers=self.auth.get_headers())
            response.raise_for_status()
            
            data = response.json()
            expirations = data.get('expirations', [])
            
            # Find today's expiration
            today = datetime.now().strftime('%Y-%m-%d')
            for exp in expirations:
                if exp.startswith(today):
                    return exp
            
            logger.warning("No 0DTE expiration found")
            return None
        except Exception as e:
            logger.error(f"Failed to get expiration: {e}")
            return None


# ============================================================================
# GEX FILTERING
# ============================================================================

class GEXFilter:
    """Check Gamma Exposure Index from SpotGamma"""
    
    GEX_URL = "https://www.spotgamma.com/api/v1/spx"
    
    @staticmethod
    def get_gex() -> Optional[float]:
        """
        Fetch current GEX from SpotGamma
        
        Returns:
            float: GEX value or None if failed
        """
        try:
            response = requests.get(GEXFilter.GEX_URL, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            gex = data.get('gex', None)
            
            if gex is not None:
                logger.info(f"GEX: {gex:,.0f}")
            return gex
        except Exception as e:
            logger.warning(f"Failed to fetch GEX: {e}")
            return None
    
    @staticmethod
    def should_trade(config: BotConfig) -> bool:
        """Check if GEX permits trading"""
        if not config.GEX_CHECK_ENABLED:
            return True
        
        gex = GEXFilter.get_gex()
        if gex is None:
            logger.warning("GEX unavailable, proceeding with caution")
            return True
        
        if gex >= config.MIN_GEX_VALUE:
            logger.info(f"✓ GEX check passed (GEX={gex:,.0f})")
            return True
        else:
            logger.warning(f"✗ GEX too low ({gex:,.0f}), skipping trade")
            return False


# ============================================================================
# STRIKE SELECTION & GREEKS CALCULATION
# ============================================================================

class GreeksCalculator:
    """Calculate option Greeks using Black-Scholes"""
    
    from math import sqrt, log, exp, pi
    
    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d1 for Black-Scholes"""
        from math import sqrt, log
        return (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    
    @staticmethod
    def d2(d1: float, sigma: float, T: float) -> float:
        """Calculate d2 for Black-Scholes"""
        from math import sqrt
        return d1 - sigma * sqrt(T)
    
    @staticmethod
    def norm_pdf(x: float) -> float:
        """Standard normal probability density function"""
        from math import exp, pi
        return exp(-0.5 * x ** 2) / (pi ** 0.5)
    
    @staticmethod
    def norm_cdf(x: float) -> float:
        """Standard normal cumulative distribution"""
        from math import erf
        return 0.5 * (1 + erf(x / (2 ** 0.5)))
    
    @staticmethod
    def calculate_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str = 'call') -> float:
        """Calculate option delta"""
        d1 = GreeksCalculator.d1(S, K, T, r, sigma)
        cdf = GreeksCalculator.norm_cdf(d1)
        
        if option_type == 'call':
            return cdf
        else:  # put
            return cdf - 1
    
    @staticmethod
    def calculate_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate option gamma"""
        d1 = GreeksCalculator.d1(S, K, T, r, sigma)
        pdf = GreeksCalculator.norm_pdf(d1)
        from math import sqrt
        return pdf / (S * sigma * sqrt(T))
    
    @staticmethod
    def calculate_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str = 'call') -> float:
        """Calculate option theta (daily decay)"""
        from math import sqrt, exp
        d1 = GreeksCalculator.d1(S, K, T, r, sigma)
        d2 = GreeksCalculator.d2(d1, sigma, T)
        pdf = GreeksCalculator.norm_pdf(d1)
        cdf = GreeksCalculator.norm_cdf(d2)
        
        if option_type == 'call':
            theta = (-S * pdf * sigma) / (2 * sqrt(T)) - r * K * exp(-r * T) * cdf
        else:  # put
            cdf_neg = GreeksCalculator.norm_cdf(-d2)
            theta = (-S * pdf * sigma) / (2 * sqrt(T)) + r * K * exp(-r * T) * cdf_neg
        
        return theta / 365  # Convert to daily


class StrikeSelector:
    """Select optimal strikes for iron condor"""
    
    @staticmethod
    def select_strikes(
        spx_price: float,
        expiration: str,
        target_delta: float = 0.20,
        config: BotConfig = None
    ) -> Optional[Dict]:
        """
        Select call and put strikes based on delta
        
        Args:
            spx_price: Current SPX price
            expiration: Expiration date (YYYY-MM-DD)
            target_delta: Target delta (0.20 = 20 delta)
            config: Bot configuration
            
        Returns:
            Dict with call_sell, call_buy, put_sell, put_buy strikes
        """
        config = config or BotConfig()
        
        try:
            # Time to expiration in years
            exp_datetime = datetime.strptime(expiration, '%Y-%m-%d').replace(hour=16, minute=0)
            now = datetime.now()
            time_to_exp = (exp_datetime - now).total_seconds() / (365.25 * 24 * 3600)
            
            if time_to_exp < 0:
                logger.error("Expiration in the past")
                return None
            
            # Estimate volatility (use IV if available from API)
            sigma = 0.15  # Default 15% IV (adjust based on actual IV)
            r = 0.05  # Risk-free rate (approximate)
            
            # Binary search for strikes matching target delta
            call_strike = StrikeSelector._find_strike(
                spx_price, time_to_exp, r, sigma,
                target_delta, option_type='call'
            )
            
            put_strike = StrikeSelector._find_strike(
                spx_price, time_to_exp, r, sigma,
                target_delta, option_type='put'
            )
            
            # Round to nearest $1
            call_strike = round(call_strike)
            put_strike = round(put_strike)
            
            # Create spreads
            call_sell = call_strike
            call_buy = call_strike + config.SPREAD_WIDTH
            put_sell = put_strike
            put_buy = put_strike - config.SPREAD_WIDTH
            
            return {
                'call_sell': call_sell,
                'call_buy': call_buy,
                'put_sell': put_sell,
                'put_buy': put_buy,
                'spx_price': spx_price,
                'time_to_exp': time_to_exp
            }
        except Exception as e:
            logger.error(f"Strike selection failed: {e}")
            return None
    
    @staticmethod
    def _find_strike(S: float, T: float, r: float, sigma: float, target_delta: float, option_type: str) -> float:
        """Binary search to find strike matching target delta"""
        if option_type == 'call':
            low, high = S * 0.95, S * 1.10
        else:
            low, high = S * 0.90, S * 1.05
        
        for _ in range(50):  # 50 iterations should converge
            mid = (low + high) / 2
            delta = abs(GreeksCalculator.calculate_delta(S, mid, T, r, sigma, option_type))
            
            if delta < target_delta:
                if option_type == 'call':
                    low = mid
                else:
                    high = mid
            else:
                if option_type == 'call':
                    high = mid
                else:
                    low = mid
        
        return (low + high) / 2


# ============================================================================
# ORDER EXECUTION
# ============================================================================

class OrderExecutor:
    """Handle order placement and management"""
    
    def __init__(self, auth: TastytradeAuth, account_id: str, config: BotConfig = None):
        self.auth = auth
        self.account_id = account_id
        self.config = config or BotConfig()
    
    def submit_iron_condor(
        self,
        call_sell: int,
        call_buy: int,
        put_sell: int,
        put_buy: int,
        contracts: int = 1,
        expiration: str = None
    ) -> Optional[Dict]:
        """
        Submit iron condor order
        
        Args:
            call_sell: Call sell strike
            call_buy: Call buy strike
            put_sell: Put sell strike
            put_buy: Put buy strike
            contracts: Number of contracts
            expiration: Expiration date
            
        Returns:
            Order confirmation dict or None
        """
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{self.account_id}/orders"
            
            legs = [
                {
                    "symbol": f"SPX",
                    "quantity": contracts,
                    "action": "sell_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": call_sell,
                    "option_type": "call"
                },
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "buy_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": call_buy,
                    "option_type": "call"
                },
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "sell_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": put_sell,
                    "option_type": "put"
                },
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "buy_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": put_buy,
                    "option_type": "put"
                }
            ]
            
            payload = {
                "time_in_force": "day",
                "order_type": "limit",
                "legs": legs,
                "price": None  # Will be calculated
            }
            
            response = requests.post(
                url,
                json=payload,
                headers=self.auth.get_headers()
            )
            response.raise_for_status()
            
            order = response.json()
            order_id = order.get('order_id')
            logger.info(f"✓ Order submitted: {order_id}")
            logger.info(f"  Call spread: {call_sell}/{call_buy}")
            logger.info(f"  Put spread:  {put_sell}/{put_buy}")
            
            return order
        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            return None
    
    def submit_bull_call_spread(
        self,
        buy_strike: int,
        sell_strike: int,
        contracts: int = 1,
        expiration: str = None
    ) -> Optional[Dict]:
        """
        Submit Bull Call Spread order.
        Buy lower strike call (ATM), sell higher strike call (OTM).
        Net debit trade — directional bullish.
        """
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{self.account_id}/orders"

            legs = [
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "buy_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": buy_strike,
                    "option_type": "call"
                },
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "sell_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": sell_strike,
                    "option_type": "call"
                }
            ]

            payload = {
                "time_in_force": "day",
                "order_type": "limit",
                "legs": legs,
                "price": None
            }

            response = requests.post(url, json=payload, headers=self.auth.get_headers())
            response.raise_for_status()

            order = response.json()
            order_id = order.get("order_id")
            logger.info(f"✓ BULL CALL SPREAD submitted: {order_id}")
            logger.info(f"  Buy {buy_strike}C / Sell {sell_strike}C × {contracts}")
            return order

        except Exception as e:
            logger.error(f"Bull call spread submission failed: {e}")
            return None

    def submit_bear_put_spread(
        self,
        buy_strike: int,
        sell_strike: int,
        contracts: int = 1,
        expiration: str = None
    ) -> Optional[Dict]:
        """
        Submit Bear Put Spread order.
        Buy higher strike put (ATM/near-ATM), sell lower strike put (OTM).
        Net debit trade — directional bearish.
        """
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{self.account_id}/orders"

            legs = [
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "buy_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": buy_strike,
                    "option_type": "put"
                },
                {
                    "symbol": "SPX",
                    "quantity": contracts,
                    "action": "sell_to_open",
                    "instrument_type": "equity_option",
                    "expiration_date": expiration,
                    "strike_price": sell_strike,
                    "option_type": "put"
                }
            ]

            payload = {
                "time_in_force": "day",
                "order_type": "limit",
                "legs": legs,
                "price": None
            }

            response = requests.post(url, json=payload, headers=self.auth.get_headers())
            response.raise_for_status()

            order = response.json()
            order_id = order.get("order_id")
            logger.info(f"✓ BEAR PUT SPREAD submitted: {order_id}")
            logger.info(f"  Buy {buy_strike}P / Sell {sell_strike}P × {contracts}")
            return order

        except Exception as e:
            logger.error(f"Bear put spread submission failed: {e}")
            return None

    def close_position(self, order_id: str) -> bool:
        """Close an existing position"""
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{self.account_id}/orders/{order_id}/cancel"
            response = requests.post(url, headers=self.auth.get_headers())
            response.raise_for_status()
            
            logger.info(f"✓ Position closed: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            return False
    
    def get_positions(self) -> Optional[List[Dict]]:
        """Get current positions"""
        try:
            url = f"{self.config.API_BASE_URL}/accounts/{self.account_id}/positions"
            response = requests.get(url, headers=self.auth.get_headers())
            response.raise_for_status()
            return response.json().get('items', [])
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return None


# ============================================================================
# MAIN BOT ENGINE
# ============================================================================

class SPX0DTEBot:
    """Main trading bot"""
    
    def __init__(self, email: str, password: str, config: BotConfig = None):
        self.config = config or BotConfig()
        self.auth = TastytradeAuth(config=self.config)
        self.data = None
        self.executor = None
        self.account_id = None
        self.trades_log = []
        
        # Authenticate
        if self.auth.authenticate(email, password):
            self.data = TastytradeData(self.auth, self.config)
    
    def initialize(self, account_id: str) -> bool:
        """Initialize bot with account"""
        self.account_id = account_id
        self.executor = OrderExecutor(self.auth, account_id, self.config)
        
        account_info = self.data.get_account_info(account_id)
        if account_info:
            logger.info(f"✓ Bot initialized for account: {account_id}")
            return True
        return False
    
    def run_daily_check(self) -> Optional[Dict]:
        """
        Run daily trading check using the full multi-bot engine.

        Routes to:
            SIDEWAYS  → Iron Condor
            BULLISH   → Bull Call Spread
            BEARISH   → Bear Put Spread
            NO_TRADE  → skip

        All regime detection, technical confirmation, and strike
        selection is handled by MultiBotEngine.
        """
        logger.info("=" * 60)
        logger.info(f"Daily check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        # ── GEX filter (fast/cheap check — run before heavier analysis) ──
        if not GEXFilter.should_trade(self.config):
            logger.warning("GEX filter blocked trade")
            return None

        # ── Multi-bot engine: regime + technicals + strike selection ──────
        engine = MultiBotEngine(
            account_size=self.config.ACCOUNT_SIZE,
            risk_pct=self.config.RISK_PER_TRADE,
        )

        # Get 0DTE expiration from API first
        expiration = self.data.get_0dte_expiration()
        if not expiration:
            logger.error("No 0DTE expiration found")
            return None

        setup = engine.analyze(expiration=expiration)

        if setup is None:
            logger.info("MultiBotEngine returned NO_TRADE — skipping")
            return None

        bot_type  = setup["bot_type"]
        strikes   = setup["strikes"]
        contracts = strikes["contracts"]
        spx_price = setup["spx_price"]

        # ── Route to the correct order type ──────────────────────────────
        order = None

        if bot_type == BotType.BULLISH:
            logger.info(f"→ BULLISH BOT: Buy {strikes['buy_strike']}C / Sell {strikes['sell_strike']}C "
                        f"× {contracts}")
            order = self.executor.submit_bull_call_spread(
                buy_strike=strikes["buy_strike"],
                sell_strike=strikes["sell_strike"],
                contracts=contracts,
                expiration=expiration,
            )

        elif bot_type == BotType.BEARISH:
            logger.info(f"→ BEARISH BOT: Buy {strikes['buy_strike']}P / Sell {strikes['sell_strike']}P "
                        f"× {contracts}")
            order = self.executor.submit_bear_put_spread(
                buy_strike=strikes["buy_strike"],
                sell_strike=strikes["sell_strike"],
                contracts=contracts,
                expiration=expiration,
            )

        else:  # SIDEWAYS
            logger.info(f"→ SIDEWAYS BOT: Iron Condor "
                        f"Calls {strikes['call_sell']}/{strikes['call_buy']} "
                        f"Puts {strikes['put_sell']}/{strikes['put_buy']} "
                        f"× {contracts}")
            order = self.executor.submit_iron_condor(
                call_sell=strikes["call_sell"],
                call_buy=strikes["call_buy"],
                put_sell=strikes["put_sell"],
                put_buy=strikes["put_buy"],
                contracts=contracts,
                expiration=expiration,
            )

        if order:
            trade_record = {
                "timestamp":    datetime.now().isoformat(),
                "bot_type":     bot_type.value,
                "spx_price":    spx_price,
                "expiration":   expiration,
                "strikes":      strikes,
                "contracts":    contracts,
                "order_id":     order.get("order_id"),
                "status":       "open",
                # Signal metadata for logging/analysis
                "ema_regime":       setup["ema_regime"],
                "ema_confluence":   setup["ema_confluence"],
                "adx":              setup["adx"],
                "rsi":              setup["rsi"],
                "vix":              setup["vix"],
                "confidence":       setup["confidence"],
                "reasons":          setup["reasons"],
            }
            self.trades_log.append(trade_record)
            self._save_trades_log()
            return trade_record

        return None
    
    def _save_trades_log(self):
        """Save trades to JSON log"""
        try:
            with open('trades_log.json', 'w') as f:
                json.dump(self.trades_log, f, indent=2)
            logger.info("Trades log saved")
        except Exception as e:
            logger.error(f"Failed to save trades log: {e}")


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    
    # Configuration
    config = BotConfig()
    config.SANDBOX_MODE = True  # Start with sandbox
    config.GEX_CHECK_ENABLED = True
    
    # Get credentials
    email = os.getenv('TASTYTRADE_EMAIL')
    password = os.getenv('TASTYTRADE_PASSWORD')
    account_id = os.getenv('TASTYTRADE_ACCOUNT_ID')
    
    if not all([email, password, account_id]):
        logger.error("Missing credentials. Set TASTYTRADE_EMAIL, TASTYTRADE_PASSWORD, TASTYTRADE_ACCOUNT_ID")
        return
    
    # Initialize bot
    bot = SPX0DTEBot(email, password, config)
    
    if not bot.auth.session_token:
        logger.error("Failed to authenticate")
        return
    
    if not bot.initialize(account_id):
        logger.error("Failed to initialize bot")
        return
    
    # Run daily check
    bot.run_daily_check()


if __name__ == '__main__':
    main()
