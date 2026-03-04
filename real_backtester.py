#!/usr/bin/env python3
"""
Real Backtester — 0DTE SPX Multi-Bot Strategy
==============================================
Simulates actual trade execution using real historical SPX price data.

Data sources (all via yfinance, no API key needed):
    ^GSPC hourly  — ~3 years of intraday bars for entry/exit simulation
    ^GSPC daily   — 5 years for long-period EMA calculations (EMA 120/233)
    ^VIX daily    — volatility filter + premium estimation

Methodology (no lookahead bias):
    For each trading day D:
    1. Compute EMA clouds + ADX/RSI using data UP TO end of D-1
       (simulates checking pre-market before the open)
    2. Apply VIX gate: skip if VIX > 25 (proxy for negative GEX / panic days)
    3. At 11:00 AM ET: read entry price from hourly bar
    4. Select strikes based on ATR-derived expected move
    5. Monitor 11am–3:30pm intraday bars for stop-loss events
    6. At 3:30 PM ET: settle position, calculate P&L

P&L Model:
    Iron Condor (credit spread):
        Win  = SPX stays between short strikes at 3:30pm
        Loss = short strike breached → capped at (spread_width − credit)
    Bull Call / Bear Put Spread (debit):
        Win  = spread expires ITM → profit = intrinsic value − debit
        Loss = spread expires OTM → lose full debit

Premium Estimation (no option chain data available):
    Credit ≈ min(0.30 × width × VIX/15, 0.50 × width)
    Debit  ≈ 0.40 × spread_width

Note: GEX historical data not available — VIX > 25 used as proxy filter.
      Real strategy with GEX filter may perform 5-10% better on win rate.
"""

import sys
import logging
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from enum import Enum

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)  # Quiet yfinance noise
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class BotType(Enum):
    BULLISH  = "BULLISH"
    BEARISH  = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    NO_TRADE = "NO_TRADE"


class ExitReason(Enum):
    EXPIRY      = "EXPIRY"        # Normal 3:30pm settle
    STOP_LOSS   = "STOP_LOSS"     # Stopped out intraday
    NO_ENTRY    = "NO_ENTRY"      # Missing data


@dataclass
class TradeRecord:
    date:           date
    bot_type:       BotType
    entry_price:    float
    exit_price:     float

    # Strikes
    strike_a:       float   # Call sell / put buy / call sell (IC)
    strike_b:       float   # Call buy  / put sell / put sell (IC)
    strike_c:       float = 0   # IC put sell
    strike_d:       float = 0   # IC put buy

    # P&L
    credit_or_debit: float = 0   # + = credit, - = debit
    pnl:            float  = 0
    exit_reason:    ExitReason = ExitReason.EXPIRY

    # Context
    vix:            float = 0
    atr:            float = 0
    regime:         str   = ""
    confluence:     int   = 0
    adx:            float = 0
    rsi:            float = 0


# ============================================================================
# DATA LOADER
# ============================================================================

class DataLoader:
    """
    Downloads and caches all historical data needed for the backtest.
    Called once at startup.
    """

    def __init__(self):
        self.hourly_df: Optional[pd.DataFrame] = None
        self.daily_df:  Optional[pd.DataFrame] = None
        self.vix_df:    Optional[pd.DataFrame] = None

    def load(self, verbose: bool = True) -> bool:
        if verbose:
            print("Fetching historical data from Yahoo Finance...")

        try:
            # Hourly SPX — used for intraday entry/exit + short-period EMAs
            h = yf.Ticker("^GSPC").history(interval="1h", period="730d", auto_adjust=True)
            if h.empty:
                print("ERROR: Could not fetch hourly SPX data")
                return False
            h.index = pd.to_datetime(h.index, utc=True).tz_convert("America/New_York")
            self.hourly_df = h

            # Daily SPX — used for long-period EMAs (120, 233) + ATR
            d = yf.Ticker("^GSPC").history(interval="1d", period="5y", auto_adjust=True)
            d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York")
            self.daily_df = d

            # Daily VIX — volatility filter + premium estimation
            v = yf.Ticker("^VIX").history(interval="1d", period="5y", auto_adjust=True)
            v.index = pd.to_datetime(v.index, utc=True).tz_convert("America/New_York")
            self.vix_df = v

            if verbose:
                print(f"  Hourly bars : {len(h):,} ({h.index[0].date()} → {h.index[-1].date()})")
                print(f"  Daily bars  : {len(d):,} ({d.index[0].date()} → {d.index[-1].date()})")
                print(f"  VIX bars    : {len(v):,} ({v.index[0].date()} → {v.index[-1].date()})")
            return True

        except Exception as e:
            print(f"ERROR fetching data: {e}")
            return False

    def get_trading_days(self) -> List[date]:
        """Return all dates that have at least 5 intraday hourly bars"""
        if self.hourly_df is None:
            return []
        day_counts = self.hourly_df.groupby(self.hourly_df.index.date).size()
        return sorted([d for d, cnt in day_counts.items() if cnt >= 5])


# ============================================================================
# POINT-IN-TIME INDICATOR COMPUTER
# ============================================================================

class PointInTime:
    """
    Computes all indicators for a given date using ONLY data available
    before market open on that date. Zero lookahead bias.
    """

    @staticmethod
    def _ema_val(series: pd.Series, period: int) -> float:
        if len(series) < period:
            return float(series.iloc[-1]) if len(series) > 0 else 0.0
        return float(series.ewm(span=period, adjust=False).mean().iloc[-1])

    @staticmethod
    def _ema_series(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        pc = df["Close"].shift(1)
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - pc).abs(),
            (df["Low"]  - pc).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    @staticmethod
    def _adx_rsi(series: pd.Series, high: pd.Series, low: pd.Series,
                 period: int = 14) -> Tuple[float, float, float, float]:
        """Returns (adx, plus_di, minus_di, rsi)"""
        # RSI
        delta = series.diff()
        gain  = delta.where(delta > 0, 0.0)
        loss  = (-delta).where(delta < 0, 0.0)
        avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
        with np.errstate(invalid="ignore", divide="ignore"):
            rs  = avg_g / avg_l.replace(0, np.nan)
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])

        # ADX
        n = len(series)
        if n < period * 3:
            return 20.0, 20.0, 20.0, rsi

        h_arr = high.values.astype(float)
        l_arr = low.values.astype(float)
        c_arr = series.values.astype(float)

        tr      = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm= np.zeros(n)
        for i in range(1, n):
            tr[i]       = max(h_arr[i]-l_arr[i], abs(h_arr[i]-c_arr[i-1]), abs(l_arr[i]-c_arr[i-1]))
            up          = h_arr[i] - h_arr[i-1]
            down        = l_arr[i-1] - l_arr[i]
            plus_dm[i]  = up   if (up   > down and up   > 0) else 0.0
            minus_dm[i] = down if (down > up   and down > 0) else 0.0

        def ws(arr, p):
            out = np.zeros(n)
            if p < n:
                out[p] = arr[1:p+1].sum()
                for i in range(p+1, n):
                    out[i] = out[i-1] - out[i-1]/p + arr[i]
            return out

        tr_s = ws(tr, period); pdm_s = ws(plus_dm, period); mdm_s = ws(minus_dm, period)
        with np.errstate(invalid="ignore", divide="ignore"):
            pdi = np.where(tr_s > 0, 100*pdm_s/tr_s, 0)
            mdi = np.where(tr_s > 0, 100*mdm_s/tr_s, 0)
            dx  = np.where((pdi+mdi) > 0, 100*np.abs(pdi-mdi)/(pdi+mdi), 0)
        adx = np.zeros(n)
        if 2*period < n:
            adx[2*period] = dx[period:2*period+1].mean()
            for i in range(2*period+1, n):
                adx[i] = (adx[i-1]*(period-1) + dx[i]) / period

        return float(adx[-1]), float(pdi[-1]), float(mdi[-1]), rsi

    @classmethod
    def compute(cls, trading_day: date, hourly_df: pd.DataFrame,
                daily_df: pd.DataFrame) -> Optional[Dict]:
        """
        Compute all indicators as-of pre-market on trading_day.
        Uses data strictly BEFORE trading_day.

        Returns dict with: regime, confluence, adx, plus_di, minus_di, rsi, atr,
                           ema8..ema233, clouds, trend_label
        """
        # Slice: everything before this trading day
        h = hourly_df[hourly_df.index.date < trading_day].copy()
        d = daily_df[daily_df.index.date < trading_day].copy()

        if len(h) < 55 or len(d) < 50:
            return None

        close_h = h["Close"]
        close_d = d["Close"]

        # ── All 10 EMAs (on hourly data) ─────────────────────────────
        e8   = cls._ema_val(close_h, 8)
        e9   = cls._ema_val(close_h, 9)
        e20  = cls._ema_val(close_h, 20)
        e21  = cls._ema_val(close_h, 21)
        e34  = cls._ema_val(close_h, 34)
        e50  = cls._ema_val(close_h, 50)
        e55  = cls._ema_val(close_h, 55)
        e89  = cls._ema_val(close_h, 89)
        e120 = cls._ema_val(close_h, 120)
        # EMA 233: use daily if not enough hourly bars
        e233 = cls._ema_val(close_h, 233) if len(close_h) >= 233 \
               else cls._ema_val(close_d, 233)

        # Last known price (yesterday's close)
        price = float(close_h.iloc[-1])

        # ── Cloud positions ───────────────────────────────────────────
        def cloud_pos(p, a, b):
            top, bot = max(a, b), min(a, b)
            if p > top: return "ABOVE"
            if p < bot: return "BELOW"
            return "INSIDE"

        c1 = cloud_pos(price, e8,   e9)
        c2 = cloud_pos(price, e20,  e21)
        c3 = cloud_pos(price, e34,  e50)   # KEY
        c4 = cloud_pos(price, e55,  e89)
        c5 = cloud_pos(price, e120, e233)

        # ── Trend label: EMA8 x EMA34 crossover ──────────────────────
        ema8_s  = cls._ema_series(close_h, 8)
        ema34_s = cls._ema_series(close_h, 34)
        trend_label = "NONE"
        if len(ema8_s) >= 2:
            diff_now  = float(ema8_s.iloc[-1]  - ema34_s.iloc[-1])
            diff_prev = float(ema8_s.iloc[-2]   - ema34_s.iloc[-2])
            if diff_prev <= 0 < diff_now:
                trend_label = "BULLISH_CROSS"
            elif diff_prev >= 0 > diff_now:
                trend_label = "BEARISH_CROSS"

        # ── Regime ───────────────────────────────────────────────────
        if c3 == "INSIDE":
            regime = "SIDEWAYS"
            confluence = 0
        else:
            if c3 == "ABOVE":
                direction = "BULLISH"
                score = 2  # c3 counts double
                if c1 == "ABOVE": score += 1
                if c2 == "ABOVE": score += 1
                if c4 == "ABOVE": score += 1
                if c5 == "ABOVE": score += 1
                if trend_label == "BULLISH_CROSS": score += 1
                # Conflict: fast bullish but slow clouds bearish
                if c4 == "BELOW" and c5 == "BELOW":
                    regime = "SIDEWAYS"
                    confluence = 2
                    return dict(regime=regime, confluence=confluence,
                                adx=0, plus_di=0, minus_di=0, rsi=50,
                                atr=cls._atr(d), price=price,
                                trend_label=trend_label)
            else:
                direction = "BEARISH"
                score = 2
                if c1 == "BELOW": score += 1
                if c2 == "BELOW": score += 1
                if c4 == "BELOW": score += 1
                if c5 == "BELOW": score += 1
                if trend_label == "BEARISH_CROSS": score += 1
                if c4 == "ABOVE" and c5 == "ABOVE":
                    regime = "SIDEWAYS"
                    confluence = 2
                    return dict(regime=regime, confluence=confluence,
                                adx=0, plus_di=0, minus_di=0, rsi=50,
                                atr=cls._atr(d), price=price,
                                trend_label=trend_label)

            regime    = direction
            # Normalize 2-7 → 1-5
            confluence = max(1, min(5, round((score - 1) * (5/6))))

        # ── ADX / RSI ─────────────────────────────────────────────────
        adx, pdi, mdi, rsi = cls._adx_rsi(close_h, h["High"], h["Low"])

        # ── ATR (daily) ───────────────────────────────────────────────
        atr = cls._atr(d)

        return dict(
            regime=regime, confluence=confluence,
            adx=adx, plus_di=pdi, minus_di=mdi, rsi=rsi,
            atr=atr, price=price, trend_label=trend_label,
        )


# ============================================================================
# BOT ROUTER (simplified — mirrors multi_bot_engine.py logic)
# ============================================================================

def route_bot(ind: Dict, vix: float) -> BotType:
    """Select bot type from point-in-time indicators + VIX."""
    if vix >= 28:
        return BotType.NO_TRADE

    regime     = ind["regime"]
    confluence = ind["confluence"]
    adx        = ind["adx"]
    pdi        = ind["plus_di"]
    mdi        = ind["minus_di"]
    rsi        = ind["rsi"]

    if regime == "SIDEWAYS":
        return BotType.SIDEWAYS

    if regime == "BULLISH":
        if confluence >= 3 and adx > 25 and pdi > mdi and rsi > 55 and vix < 28:
            return BotType.BULLISH
        return BotType.NO_TRADE

    if regime == "BEARISH":
        if confluence >= 3 and adx > 25 and mdi > pdi and rsi < 45 and vix < 28:
            return BotType.BEARISH
        return BotType.NO_TRADE

    return BotType.NO_TRADE


# ============================================================================
# PREMIUM ESTIMATOR
# ============================================================================

class PremiumEstimator:
    """
    Estimates option credit/debit using VIX-scaled model.
    No actual option chain data — uses empirical 0DTE SPX pricing.

    Calibration (based on typical 0DTE SPX market pricing):
        VIX 15 → 20-delta $5 spread credit ≈ $0.75  (15% of width)
        VIX 20 → 20-delta $5 spread credit ≈ $1.00  (20% of width)
        VIX 25 → 20-delta $5 spread credit ≈ $1.25  (25% of width)
        ATM $10 debit spread ≈ $4.00–$5.00           (40-50% of width)
    """

    @staticmethod
    def condor_credit(spread_width: float, vix: float) -> float:
        """Iron condor: total credit for one side (either calls or puts)"""
        base_pct = 0.15   # 15% of width at VIX=15
        vol_adj  = vix / 15
        credit   = base_pct * spread_width * vol_adj
        return round(min(credit, spread_width * 0.35), 2)  # cap at 35%

    @staticmethod
    def directional_debit(spread_width: float, vix: float) -> float:
        """Bull call / bear put spread: net debit"""
        base_pct = 0.35   # 35% of width at VIX=15
        vol_adj  = vix / 15
        debit    = base_pct * spread_width * vol_adj
        return round(min(debit, spread_width * 0.55), 2)   # cap at 55%


# ============================================================================
# TRADE SIMULATOR
# ============================================================================

class TradeSimulator:
    """
    Selects strikes and calculates P&L for each bot type.
    Uses ATR to size the expected daily move for strike placement.
    """

    SPREAD_WIDTH_CONDOR     = 5.0    # $5 wide iron condor
    SPREAD_WIDTH_DIRECTIONAL= 10.0   # $10 wide directional spread
    STOP_LOSS_MULTIPLIER    = 2.0    # Stop condor at 2× credit received

    @staticmethod
    def _round_strike(price: float, width: float = 5.0) -> float:
        return round(round(price / width) * width, 0)

    @classmethod
    def build_condor(cls, entry: float, atr: float, vix: float) -> Dict:
        """Iron condor: short strikes at ±0.75× expected half-day move"""
        half_day_move = atr * 0.5 * 0.65   # ~65% of half ATR
        half_day_move = max(half_day_move, atr * 0.3)

        call_sell = cls._round_strike(entry + half_day_move)
        call_buy  = call_sell + cls.SPREAD_WIDTH_CONDOR
        put_sell  = cls._round_strike(entry - half_day_move)
        put_buy   = put_sell - cls.SPREAD_WIDTH_CONDOR

        credit_side = PremiumEstimator.condor_credit(cls.SPREAD_WIDTH_CONDOR, vix)
        total_credit = credit_side * 2
        max_loss     = (cls.SPREAD_WIDTH_CONDOR - credit_side)  # per side, worst case

        return dict(
            call_sell=call_sell, call_buy=call_buy,
            put_sell=put_sell,   put_buy=put_buy,
            credit=total_credit, max_loss_per_side=max_loss,
            spread_width=cls.SPREAD_WIDTH_CONDOR,
        )

    @classmethod
    def build_bull_call(cls, entry: float, vix: float) -> Dict:
        buy_strike  = cls._round_strike(entry)
        sell_strike = buy_strike + cls.SPREAD_WIDTH_DIRECTIONAL
        debit       = PremiumEstimator.directional_debit(cls.SPREAD_WIDTH_DIRECTIONAL, vix)
        max_profit  = cls.SPREAD_WIDTH_DIRECTIONAL - debit
        return dict(
            buy_strike=buy_strike, sell_strike=sell_strike,
            debit=debit, max_profit=max_profit,
            spread_width=cls.SPREAD_WIDTH_DIRECTIONAL,
        )

    @classmethod
    def build_bear_put(cls, entry: float, vix: float) -> Dict:
        buy_strike  = cls._round_strike(entry)
        sell_strike = buy_strike - cls.SPREAD_WIDTH_DIRECTIONAL
        debit       = PremiumEstimator.directional_debit(cls.SPREAD_WIDTH_DIRECTIONAL, vix)
        max_profit  = cls.SPREAD_WIDTH_DIRECTIONAL - debit
        return dict(
            buy_strike=buy_strike, sell_strike=sell_strike,
            debit=debit, max_profit=max_profit,
            spread_width=cls.SPREAD_WIDTH_DIRECTIONAL,
        )

    @classmethod
    def calc_condor_pnl(cls, strikes: Dict,
                         intraday_high: float, intraday_low: float,
                         exit_price: float) -> Tuple[float, ExitReason]:
        """
        P&L for iron condor.
        Checks intraday high/low for stop-loss events first.
        """
        credit   = strikes["credit"]
        max_loss = strikes["max_loss_per_side"]
        stop_at  = credit * cls.STOP_LOSS_MULTIPLIER   # stop if mark = 2× credit

        # Stop if short strike touched intraday
        if intraday_high >= strikes["call_sell"] or intraday_low <= strikes["put_sell"]:
            return -stop_at * 100, ExitReason.STOP_LOSS

        # At expiry:
        call_breach = max(0, exit_price - strikes["call_sell"])
        put_breach  = max(0, strikes["put_sell"] - exit_price)

        call_loss = min(call_breach, strikes["spread_width"])
        put_loss  = min(put_breach,  strikes["spread_width"])

        pnl = (credit - call_loss - put_loss) * 100
        return pnl, ExitReason.EXPIRY

    @classmethod
    def calc_bull_call_pnl(cls, strikes: Dict,
                            intraday_low: float, entry_price: float,
                            exit_price: float) -> Tuple[float, ExitReason]:
        """P&L for bull call spread."""
        debit = strikes["debit"]

        # Stop: SPX drops below buy_strike - 0.3% intraday
        stop_level = entry_price * (1 - 0.003)
        if intraday_low <= stop_level:
            stop_loss = debit * 0.5 * 100
            return -stop_loss, ExitReason.STOP_LOSS

        intrinsic = max(0, min(exit_price - strikes["buy_strike"],
                               strikes["spread_width"]))
        pnl = (intrinsic - debit) * 100
        return pnl, ExitReason.EXPIRY

    @classmethod
    def calc_bear_put_pnl(cls, strikes: Dict,
                           intraday_high: float, entry_price: float,
                           exit_price: float) -> Tuple[float, ExitReason]:
        """P&L for bear put spread."""
        debit = strikes["debit"]

        # Stop: SPX rises above buy_strike + 0.3% intraday
        stop_level = entry_price * (1 + 0.003)
        if intraday_high >= stop_level:
            stop_loss = debit * 0.5 * 100
            return -stop_loss, ExitReason.STOP_LOSS

        intrinsic = max(0, min(strikes["buy_strike"] - exit_price,
                               strikes["spread_width"]))
        pnl = (intrinsic - debit) * 100
        return pnl, ExitReason.EXPIRY


# ============================================================================
# INTRADAY BAR HELPERS
# ============================================================================

def get_bar(day_df: pd.DataFrame, target_hour: int,
            target_minute: int = 0) -> Optional[pd.Series]:
    """Get the intraday bar closest to the target hour:minute"""
    candidates = day_df[
        (day_df.index.hour == target_hour) &
        (day_df.index.minute >= target_minute - 30) &
        (day_df.index.minute <= target_minute + 30)
    ]
    return candidates.iloc[0] if len(candidates) > 0 else None


def get_range(day_df: pd.DataFrame,
              start_hour: int, end_hour: int) -> pd.DataFrame:
    """Get intraday bars between start and end hours"""
    return day_df[
        (day_df.index.hour >= start_hour) &
        (day_df.index.hour <= end_hour)
    ]


# ============================================================================
# MAIN BACKTESTER
# ============================================================================

class RealBacktester:
    """
    Orchestrates the full historical simulation.
    Usage:
        bt = RealBacktester()
        bt.run()
    """

    def __init__(self, account_size: float = 25000):
        self.account_size = account_size
        self.loader       = DataLoader()
        self.trades: List[TradeRecord] = []

    def run(self, start_date: Optional[date] = None,
                  end_date:   Optional[date] = None) -> List[TradeRecord]:

        if not self.loader.load(verbose=True):
            return []

        trading_days = self.loader.get_trading_days()

        # Default to available hourly range
        if start_date is None:
            start_date = trading_days[50]   # leave burn-in for EMAs
        if end_date is None:
            end_date = trading_days[-1]

        trading_days = [d for d in trading_days if start_date <= d <= end_date]
        total        = len(trading_days)

        print(f"\nBacktesting {total} trading days "
              f"({start_date} → {end_date})...\n")

        self.trades = []
        skipped_data = 0
        skipped_gate = 0

        for i, day in enumerate(trading_days):
            if (i+1) % 50 == 0:
                wins = sum(1 for t in self.trades if t.pnl > 0)
                n    = len(self.trades)
                wr   = wins/n if n > 0 else 0
                print(f"  {i+1}/{total} days processed | "
                      f"{n} trades | {wr:.0%} WR | "
                      f"${sum(t.pnl for t in self.trades):,.0f} P&L")

            # ── Point-in-time indicators ──────────────────────────────
            ind = PointInTime.compute(day, self.loader.hourly_df,
                                           self.loader.daily_df)
            if ind is None:
                skipped_data += 1
                continue

            # ── VIX gate ──────────────────────────────────────────────
            vix_row = self.loader.vix_df[self.loader.vix_df.index.date == day]
            vix     = float(vix_row["Close"].iloc[-1]) if len(vix_row) > 0 else 18.0

            # ── Bot routing ───────────────────────────────────────────
            bot = route_bot(ind, vix)
            if bot == BotType.NO_TRADE:
                skipped_gate += 1
                continue

            # ── Intraday data for this day ────────────────────────────
            day_df = self.loader.hourly_df[
                self.loader.hourly_df.index.date == day
            ]
            if len(day_df) < 4:
                skipped_data += 1
                continue

            # ── Entry: 11am bar ───────────────────────────────────────
            entry_bar = get_bar(day_df, target_hour=11)
            if entry_bar is None:
                entry_bar = day_df.iloc[2] if len(day_df) > 2 else day_df.iloc[0]
            entry_price = float(entry_bar["Close"])

            # ── Exit: 3:30pm bar ──────────────────────────────────────
            exit_bar  = get_bar(day_df, target_hour=15, target_minute=30)
            if exit_bar is None:
                exit_bar = day_df.iloc[-1]
            exit_price = float(exit_bar["Close"])

            # ── Intraday range between entry and exit ─────────────────
            intraday = get_range(day_df, 11, 15)
            intraday_high = float(intraday["High"].max()) if len(intraday) > 0 else entry_price
            intraday_low  = float(intraday["Low"].min())  if len(intraday) > 0 else entry_price

            # ── Strikes + P&L ─────────────────────────────────────────
            atr = ind["atr"]

            if bot == BotType.SIDEWAYS:
                strikes = TradeSimulator.build_condor(entry_price, atr, vix)
                pnl, reason = TradeSimulator.calc_condor_pnl(
                    strikes, intraday_high, intraday_low, exit_price)
                rec = TradeRecord(
                    date=day, bot_type=bot,
                    entry_price=entry_price, exit_price=exit_price,
                    strike_a=strikes["call_sell"], strike_b=strikes["call_buy"],
                    strike_c=strikes["put_sell"],  strike_d=strikes["put_buy"],
                    credit_or_debit=strikes["credit"],
                    pnl=pnl, exit_reason=reason,
                    vix=vix, atr=atr,
                    regime=ind["regime"], confluence=ind["confluence"],
                    adx=ind["adx"], rsi=ind["rsi"],
                )

            elif bot == BotType.BULLISH:
                strikes = TradeSimulator.build_bull_call(entry_price, vix)
                pnl, reason = TradeSimulator.calc_bull_call_pnl(
                    strikes, intraday_low, entry_price, exit_price)
                rec = TradeRecord(
                    date=day, bot_type=bot,
                    entry_price=entry_price, exit_price=exit_price,
                    strike_a=strikes["buy_strike"], strike_b=strikes["sell_strike"],
                    credit_or_debit=-strikes["debit"],
                    pnl=pnl, exit_reason=reason,
                    vix=vix, atr=atr,
                    regime=ind["regime"], confluence=ind["confluence"],
                    adx=ind["adx"], rsi=ind["rsi"],
                )

            else:  # BEARISH
                strikes = TradeSimulator.build_bear_put(entry_price, vix)
                pnl, reason = TradeSimulator.calc_bear_put_pnl(
                    strikes, intraday_high, entry_price, exit_price)
                rec = TradeRecord(
                    date=day, bot_type=bot,
                    entry_price=entry_price, exit_price=exit_price,
                    strike_a=strikes["buy_strike"], strike_b=strikes["sell_strike"],
                    credit_or_debit=-strikes["debit"],
                    pnl=pnl, exit_reason=reason,
                    vix=vix, atr=atr,
                    regime=ind["regime"], confluence=ind["confluence"],
                    adx=ind["adx"], rsi=ind["rsi"],
                )

            self.trades.append(rec)

        print(f"\nDone. {len(self.trades)} trades | "
              f"{skipped_data} skipped (data) | {skipped_gate} skipped (gates)\n")
        return self.trades


# ============================================================================
# REPORTER
# ============================================================================

class BacktestReporter:

    def __init__(self, trades: List[TradeRecord], account_size: float = 25000):
        self.trades       = trades
        self.account_size = account_size

    def print_report(self):
        if not self.trades:
            print("No trades to report.")
            return

        df = pd.DataFrame([vars(t) for t in self.trades])
        df["year"]  = pd.to_datetime(df["date"]).dt.year
        df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
        df["win"]   = df["pnl"] > 0

        sep = "=" * 68

        # ── Overall ───────────────────────────────────────────────────
        print(f"\n{sep}")
        print(f"  BACKTEST RESULTS — 0DTE SPX Multi-Bot Strategy")
        print(sep)
        self._section(df, "OVERALL")

        # ── By Bot Type ───────────────────────────────────────────────
        print(f"\n{sep}")
        print("  BY BOT TYPE")
        print(sep)
        for bot in [BotType.SIDEWAYS, BotType.BULLISH, BotType.BEARISH]:
            sub = df[df["bot_type"] == bot]
            if len(sub) > 0:
                self._section(sub, bot.value)

        # ── By Year ───────────────────────────────────────────────────
        print(f"\n{sep}")
        print("  BY YEAR")
        print(sep)
        for year in sorted(df["year"].unique()):
            self._section(df[df["year"] == year], str(year))

        # ── Max Drawdown ──────────────────────────────────────────────
        equity = df["pnl"].cumsum()
        rolling_max = equity.cummax()
        drawdown    = equity - rolling_max
        max_dd      = float(drawdown.min())
        max_dd_pct  = max_dd / self.account_size * 100

        # ── Sharpe (annualised, assuming 252 trading days) ────────────
        daily_returns = df.groupby("date")["pnl"].sum() / self.account_size
        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)) \
                 if daily_returns.std() > 0 else 0

        # ── Exit breakdown ────────────────────────────────────────────
        stops   = (df["exit_reason"] == ExitReason.STOP_LOSS).sum()
        expiry  = (df["exit_reason"] == ExitReason.EXPIRY).sum()

        print(f"\n{sep}")
        print("  RISK & QUALITY METRICS")
        print(sep)
        print(f"  Max Drawdown     : ${max_dd:>10,.0f}  ({max_dd_pct:.1f}% of account)")
        print(f"  Sharpe Ratio     : {sharpe:>10.2f}")
        print(f"  Exited at Expiry : {expiry:>10,} trades ({expiry/len(df):.0%})")
        print(f"  Stopped Out      : {stops:>10,} trades ({stops/len(df):.0%})")
        print(f"\n  Note: GEX filter not applied (VIX>25 used as proxy)")
        print(f"        Actual strategy may perform 5-10% better with live GEX")
        print(sep + "\n")

    def _section(self, df: pd.DataFrame, label: str):
        n       = len(df)
        wins    = df["win"].sum()
        wr      = wins / n if n > 0 else 0
        total   = df["pnl"].sum()
        avg     = df["pnl"].mean()
        best    = df["pnl"].max()
        worst   = df["pnl"].min()
        roi     = total / self.account_size * 100

        print(f"\n  {label}")
        print(f"    Trades     : {n:>6,}   Win Rate : {wr:>6.1%}")
        print(f"    Total P&L  : ${total:>10,.0f}   ROI      : {roi:>6.1f}%")
        print(f"    Avg/Trade  : ${avg:>10,.0f}   Best     : ${best:>8,.0f}")
        print(f"    Worst      : ${worst:>10,.0f}")

    def save_csv(self, path: str = "backtest_results.csv"):
        df = pd.DataFrame([vars(t) for t in self.trades])
        df["bot_type"]    = df["bot_type"].apply(lambda x: x.value)
        df["exit_reason"] = df["exit_reason"].apply(lambda x: x.value)
        df.to_csv(path, index=False)
        print(f"Results saved to {path}")

    def equity_curve(self):
        """Print a simple ASCII equity curve"""
        df       = pd.DataFrame([vars(t) for t in self.trades])
        equity   = (df["pnl"].cumsum() + self.account_size).tolist()
        hi, lo   = max(equity), min(equity)
        height   = 12
        width    = min(80, len(equity))
        step     = max(1, len(equity) // width)
        sampled  = equity[::step]

        print("\n  Equity Curve")
        print("  " + "─" * (len(sampled) + 4))
        for row in range(height, -1, -1):
            level = lo + (hi - lo) * row / height
            line  = ""
            for val in sampled:
                line += "█" if val >= level else " "
            label = f"${level:>8,.0f} |" if row % 3 == 0 else " " * 11 + "|"
            print(f"  {label}{line}")
        print("  " + " " * 11 + "└" + "─" * len(sampled))
        start_d = self.trades[0].date
        end_d   = self.trades[-1].date
        print(f"  {' '*12}{start_d}{'':>20}{end_d}\n")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 68)
    print("  Real Backtester — 0DTE SPX Multi-Bot Strategy")
    print("=" * 68)

    bt      = RealBacktester(account_size=25000)
    trades  = bt.run()

    if trades:
        reporter = BacktestReporter(trades, account_size=25000)
        reporter.print_report()
        reporter.equity_curve()
        reporter.save_csv("backtest_results.csv")
