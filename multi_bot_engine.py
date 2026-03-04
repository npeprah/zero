#!/usr/bin/env python3
"""
Multi-Bot 0DTE SPX Engine
=========================
Unified routing across three specialized bots based on EMA Cloud regime
and technical confirmation filters.

Bot Routing:
    SIDEWAYS  → Iron Condor       (sell 20-delta both sides)
    BULLISH   → Bull Call Spread  (buy 30-35 delta call, sell 10-15 delta call)
    BEARISH   → Bear Put Spread   (buy 30-35 delta put,  sell 10-15 delta put)
    NO_TRADE  → Skip              (low confidence, bad conditions)

Signal Stack (in priority order):
    1. EMA Clouds (MTF regime — primary)
    2. ADX + DI+/DI- (trend strength — confirmation)
    3. RSI (momentum — confirmation)
    4. GEX (volatility filter — safety)
    5. VIX (fear gauge — safety)
    6. DTR consumed % (exhaustion guard — late-day filter)
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from ema_clouds_filter import EMACloudsFilter, MarketRegime, EMACloudAnalysis, TrendLabel

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class BotType(Enum):
    SIDEWAYS  = "SIDEWAYS"
    BULLISH   = "BULLISH"
    BEARISH   = "BEARISH"
    NO_TRADE  = "NO_TRADE"


@dataclass
class TechnicalSignals:
    """Computed technical indicators for regime confirmation"""
    adx:       float   # ADX value (> 25 = trending)
    plus_di:   float   # DI+ (bullish pressure)
    minus_di:  float   # DI- (bearish pressure)
    rsi:       float   # RSI-14
    vix:       float   # VIX level
    spx_price: float

    @property
    def is_trending(self) -> bool:
        return self.adx > 25

    @property
    def is_bullish_trend(self) -> bool:
        return self.is_trending and self.plus_di > self.minus_di and self.rsi > 55

    @property
    def is_bearish_trend(self) -> bool:
        return self.is_trending and self.minus_di > self.plus_di and self.rsi < 45

    @property
    def is_neutral(self) -> bool:
        return not self.is_trending and 40 <= self.rsi <= 60

    @property
    def vix_ok_neutral(self) -> bool:
        return self.vix < 20   # Calm enough for iron condors

    @property
    def vix_ok_directional(self) -> bool:
        return self.vix < 28   # Some vol acceptable for directional plays

    def summary(self) -> str:
        trend = "TREND" if self.is_trending else "FLAT"
        direction = "BULLISH" if self.is_bullish_trend else ("BEARISH" if self.is_bearish_trend else "NEUTRAL")
        return (
            f"ADX={self.adx:.1f}({trend}) DI+={self.plus_di:.1f} DI-={self.minus_di:.1f} "
            f"RSI={self.rsi:.1f} VIX={self.vix:.1f} → {direction}"
        )


@dataclass
class RoutingDecision:
    """Final bot routing decision with full rationale"""
    bot_type:       BotType
    confidence:     int      # 1-5 scale
    ema_regime:     MarketRegime
    ema_confluence: int      # 0-3
    signals:        TechnicalSignals
    reasons:        List[str] = field(default_factory=list)
    warnings:       List[str] = field(default_factory=list)

    def summary(self) -> str:
        conf_bar = "█" * self.confidence + "░" * (5 - self.confidence)
        return (
            f"Bot: {self.bot_type.value} [{conf_bar}] {self.confidence}/5\n"
            f"  EMA: {self.ema_regime.value} ({self.ema_confluence}/3 confluence)\n"
            f"  Tech: {self.signals.summary()}\n"
            f"  Why:  {' | '.join(self.reasons)}"
        )


@dataclass
class StrikePackage:
    """Strikes and structure for any bot type"""
    bot_type:   BotType
    spx_price:  float
    expiration: str

    # Leg 1 — Buy (debit) or Sell (credit) the primary leg
    leg1_strike: int
    leg1_action: str    # "buy_to_open" | "sell_to_open"
    leg1_type:   str    # "call" | "put"
    leg1_delta:  float

    # Leg 2 — The hedge leg
    leg2_strike: int
    leg2_action: str
    leg2_type:   str
    leg2_delta:  float

    # For iron condor: second spread (call side when bot_type = SIDEWAYS)
    leg3_strike: Optional[int] = None
    leg3_action: Optional[str] = None
    leg3_type:   Optional[str] = None
    leg4_strike: Optional[int] = None
    leg4_action: Optional[str] = None
    leg4_type:   Optional[str] = None

    # Position sizing
    contracts:   int   = 1
    max_loss_per_contract: float = 500.0
    estimated_credit_or_debit: float = 0.0   # + = credit, - = debit

    def describe(self) -> str:
        if self.bot_type == BotType.BULLISH:
            return (
                f"BULL CALL SPREAD | Buy {self.leg1_strike}C / Sell {self.leg2_strike}C | "
                f"{self.contracts} contract(s) | Est. debit: ${abs(self.estimated_credit_or_debit):.2f}"
            )
        elif self.bot_type == BotType.BEARISH:
            return (
                f"BEAR PUT SPREAD | Buy {self.leg1_strike}P / Sell {self.leg2_strike}P | "
                f"{self.contracts} contract(s) | Est. credit: ${self.estimated_credit_or_debit:.2f}"
            )
        else:
            return (
                f"IRON CONDOR | Calls {self.leg1_strike}/{self.leg2_strike} "
                f"Puts {self.leg3_strike}/{self.leg4_strike} | "
                f"{self.contracts} contract(s)"
            )


@dataclass
class ExitSignal:
    """Intraday exit management signal"""
    should_exit: bool
    action:      str          # 'TAKE_PROFIT' | 'STOP_LOSS' | 'TIME_STOP' | 'DELTA_STOP' | 'HOLD'
    urgency:     str          # 'IMMEDIATE' | 'NEXT_CYCLE' | 'NONE'
    expected_pnl: float
    reason:      str


# ============================================================================
# TECHNICAL INDICATORS (no TA-Lib dependency)
# ============================================================================

class TechnicalIndicators:
    """
    Pure pandas/numpy implementations of ADX, DI+/DI-, RSI.
    Uses the same yfinance data already pulled by EMACloudsFilter.
    """

    @staticmethod
    def adx_and_di(df: pd.DataFrame, period: int = 14) -> Tuple[float, float, float]:
        """
        Wilder's ADX + DI+/DI-.
        Returns (adx, plus_di, minus_di) — last bar values.
        """
        high  = df["High"].values.astype(float)
        low   = df["Low"].values.astype(float)
        close = df["Close"].values.astype(float)

        n = len(close)
        tr      = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm= np.zeros(n)

        for i in range(1, n):
            hl  = high[i]  - low[i]
            hpc = abs(high[i]  - close[i-1])
            lpc = abs(low[i]   - close[i-1])
            tr[i] = max(hl, hpc, lpc)

            up   = high[i] - high[i-1]
            down = low[i-1] - low[i]
            plus_dm[i]  = up   if (up   > down and up   > 0) else 0.0
            minus_dm[i] = down if (down > up   and down > 0) else 0.0

        def wilder_smooth(arr, p):
            out = np.zeros(len(arr))
            out[p] = arr[1:p+1].sum()
            for i in range(p+1, len(arr)):
                out[i] = out[i-1] - out[i-1]/p + arr[i]
            return out

        tr_s    = wilder_smooth(tr,       period)
        pdm_s   = wilder_smooth(plus_dm,  period)
        mdm_s   = wilder_smooth(minus_dm, period)

        with np.errstate(invalid="ignore", divide="ignore"):
            plus_di  = np.where(tr_s > 0, 100 * pdm_s / tr_s, 0)
            minus_di = np.where(tr_s > 0, 100 * mdm_s / tr_s, 0)
            dx = np.where(
                (plus_di + minus_di) > 0,
                100 * np.abs(plus_di - minus_di) / (plus_di + minus_di),
                0
            )

        with np.errstate(invalid="ignore"):
            adx = np.zeros(n)
            if 2 * period < n:
                adx[2*period] = dx[period:2*period+1].mean()
                for i in range(2*period+1, n):
                    adx[i] = (adx[i-1] * (period-1) + dx[i]) / period

        return float(adx[-1]), float(plus_di[-1]), float(minus_di[-1])

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> float:
        """Wilder RSI — returns last bar value"""
        delta = series.diff()
        gain  = delta.where(delta > 0, 0.0)
        loss  = (-delta).where(delta < 0, 0.0)
        avg_g = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1/period, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, np.nan)
        return float((100 - 100 / (1 + rs)).iloc[-1])

    @staticmethod
    def fetch_and_compute(symbol: str = "^GSPC") -> Optional[TechnicalSignals]:
        """Fetch 1-hour SPX data + VIX and return TechnicalSignals"""
        try:
            spx_df = yf.Ticker(symbol).history(interval="1h", period="10d", auto_adjust=True)
            vix_df = yf.Ticker("^VIX").history(interval="1d",  period="5d",  auto_adjust=True)

            if spx_df.empty or len(spx_df) < 40:
                logger.warning("Insufficient SPX data for technicals")
                return None

            adx, pdi, mdi = TechnicalIndicators.adx_and_di(spx_df)
            rsi_val        = TechnicalIndicators.rsi(spx_df["Close"])
            vix_val        = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else 18.0
            spx_price      = float(spx_df["Close"].iloc[-1])

            return TechnicalSignals(
                adx=adx, plus_di=pdi, minus_di=mdi,
                rsi=rsi_val, vix=vix_val, spx_price=spx_price
            )
        except Exception as e:
            logger.error(f"TechnicalIndicators.fetch_and_compute error: {e}", exc_info=True)
            return None


# ============================================================================
# BOT ROUTER
# ============================================================================

class BotRouter:
    """
    Combines EMA cloud regime + technical confirmation to select bot.

    Decision matrix:
    ┌─────────────────┬──────────────┬──────────────────┬──────────────┐
    │ EMA Regime      │ ADX/DI/RSI   │ VIX              │ Route To     │
    ├─────────────────┼──────────────┼──────────────────┼──────────────┤
    │ SIDEWAYS        │ ADX < 25     │ < 20             │ SidewaysBot  │
    │ SIDEWAYS        │ ADX > 25     │ any              │ SidewaysBot* │
    │ BULLISH (≥2)    │ DI+ > DI-    │ < 28             │ BullishBot   │
    │ BULLISH (≥2)    │ conflicting  │ any              │ NO_TRADE     │
    │ BEARISH (≥2)    │ DI- > DI+    │ < 28             │ BearishBot   │
    │ BEARISH (≥2)    │ conflicting  │ any              │ NO_TRADE     │
    │ UNKNOWN         │ any          │ any              │ SidewaysBot  │
    │ any             │ any          │ ≥ 30             │ NO_TRADE     │
    └─────────────────┴──────────────┴──────────────────┴──────────────┘
    * Iron condor with tighter strikes when ADX elevated in SIDEWAYS
    """

    def route(
        self,
        ema: EMACloudAnalysis,
        tech: TechnicalSignals,
    ) -> RoutingDecision:

        reasons  = []
        warnings = []

        # ── Hard blocks ────────────────────────────────────────────────
        if tech.vix >= 30:
            return RoutingDecision(
                bot_type=BotType.NO_TRADE, confidence=5,
                ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                signals=tech, reasons=[f"VIX={tech.vix:.1f} ≥ 30 — panic conditions, no trade"],
            )

        if tech.vix >= 25 and ema.regime == MarketRegime.SIDEWAYS:
            warnings.append(f"VIX={tech.vix:.1f} elevated for iron condor — reducing confidence")

        # ── UNKNOWN regime → safe default (sideways bot) ───────────────
        if ema.regime == MarketRegime.UNKNOWN:
            return RoutingDecision(
                bot_type=BotType.SIDEWAYS, confidence=1,
                ema_regime=ema.regime, ema_confluence=0,
                signals=tech, reasons=["EMA regime unknown — defaulting to iron condor (caution)"],
                warnings=["Low confidence — consider skipping or reducing size"],
            )

        # ── SIDEWAYS regime ────────────────────────────────────────────
        if ema.regime == MarketRegime.SIDEWAYS:
            reasons.append("Price inside 1-hr EMA cloud (34/50)")
            if not tech.is_trending:
                reasons.append(f"ADX={tech.adx:.1f} < 25 confirms no trend")
                conf = 4
            else:
                warnings.append(f"ADX={tech.adx:.1f} elevated despite SIDEWAYS cloud — use tighter strikes")
                conf = 2
            if tech.vix_ok_neutral:
                reasons.append(f"VIX={tech.vix:.1f} benign")
                conf = min(conf + 1, 5)

            return RoutingDecision(
                bot_type=BotType.SIDEWAYS, confidence=conf,
                ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                signals=tech, reasons=reasons, warnings=warnings,
            )

        # ── BULLISH regime ─────────────────────────────────────────────
        if ema.regime == MarketRegime.BULLISH:
            # Confluence now 0-5; require at least 3
            if ema.confluence_score < 3:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=2,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=[f"Bullish EMA but confluence too low ({ema.confluence_score}/5)"],
                )

            if not tech.vix_ok_directional:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=3,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=[f"VIX={tech.vix:.1f} too high for bullish spread"],
                )

            if tech.is_bullish_trend:
                # Scale confidence: EMA confluence (0-5) + tech confirmation
                conf = min(5, round(ema.confluence_score * 0.6 + 2))
                reasons.append(f"EMA BULLISH {ema.confluence_score}/5 + ADX={tech.adx:.1f} DI+={tech.plus_di:.1f} RSI={tech.rsi:.1f}")
                # Bonus: fresh bullish trend label crossover
                if hasattr(ema, 'trend_label') and ema.trend_label == TrendLabel.BULLISH_CROSS:
                    reasons.append(f"Ripster Trend Label: BULLISH CROSS ({ema.bars_since_cross} bars ago)")
                    conf = min(5, conf + 1)
                return RoutingDecision(
                    bot_type=BotType.BULLISH, confidence=conf,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=reasons, warnings=warnings,
                )
            else:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=2,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech,
                    reasons=["Bullish EMA but ADX/DI/RSI don't confirm — skip to avoid whipsaw"],
                )

        # ── BEARISH regime ─────────────────────────────────────────────
        if ema.regime == MarketRegime.BEARISH:
            if ema.confluence_score < 3:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=2,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=[f"Bearish EMA but confluence too low ({ema.confluence_score}/5)"],
                )

            if not tech.vix_ok_directional:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=3,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=[f"VIX={tech.vix:.1f} too high — panic selling, skip bear spread"],
                )

            if tech.is_bearish_trend:
                conf = min(5, round(ema.confluence_score * 0.6 + 2))
                reasons.append(f"EMA BEARISH {ema.confluence_score}/5 + ADX={tech.adx:.1f} DI-={tech.minus_di:.1f} RSI={tech.rsi:.1f}")
                if hasattr(ema, 'trend_label') and ema.trend_label == TrendLabel.BEARISH_CROSS:
                    reasons.append(f"Ripster Trend Label: BEARISH CROSS ({ema.bars_since_cross} bars ago)")
                    conf = min(5, conf + 1)
                return RoutingDecision(
                    bot_type=BotType.BEARISH, confidence=conf,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech, reasons=reasons, warnings=warnings,
                )
            else:
                return RoutingDecision(
                    bot_type=BotType.NO_TRADE, confidence=2,
                    ema_regime=ema.regime, ema_confluence=ema.confluence_score,
                    signals=tech,
                    reasons=["Bearish EMA but ADX/DI/RSI don't confirm — skip to avoid whipsaw"],
                )

        # Fallback
        return RoutingDecision(
            bot_type=BotType.NO_TRADE, confidence=1,
            ema_regime=ema.regime, ema_confluence=ema.confluence_score,
            signals=tech, reasons=["Unhandled regime combination"],
        )


# ============================================================================
# STRIKE SELECTORS
# ============================================================================

class BullishStrikeSelector:
    """
    Bull Call Spread strikes:
    - Buy  30-35 delta call (near ATM, captures upside)
    - Sell 10-15 delta call (OTM hedge, caps max profit)
    Width: $5-10 depending on confidence
    """

    @staticmethod
    def select(spx_price: float, expiration: str, confidence: int = 3) -> Dict:
        # Approx delta-to-strike mapping using rough ATM IV assumption
        # ATM ~ 0.50 delta; each $5 further OTM reduces delta ~0.03-0.05
        # For 0DTE with ~15% IV, 1 std dev ≈ 0.5% per hour

        spread_width = 10 if confidence >= 4 else 5

        # 30-35 delta ≈ ATM or 1 strike OTM
        buy_strike  = int(round(spx_price / 5) * 5)           # round to nearest $5
        sell_strike = buy_strike + spread_width

        # Rough credit/debit estimate (actual will come from market)
        # 0DTE ATM call ~$2-3, OTM call ~$0.50-1
        est_buy_premium  = 2.00
        est_sell_premium = 0.60
        est_net_debit    = est_buy_premium - est_sell_premium   # ~$1.40

        max_profit_per_contract = (spread_width - est_net_debit) * 100
        max_loss_per_contract   = est_net_debit * 100

        return {
            "bot_type":    BotType.BULLISH,
            "buy_strike":  buy_strike,
            "sell_strike": sell_strike,
            "spread_width": spread_width,
            "est_net_debit": est_net_debit,
            "max_profit":  max_profit_per_contract,
            "max_loss":    max_loss_per_contract,
            "expiration":  expiration,
            "spx_price":   spx_price,
            # Profit target: 60% of max profit
            "profit_target": max_profit_per_contract * 0.60,
            # Stop: 50% of max loss
            "stop_loss": -max_loss_per_contract * 0.50,
        }


class BearishStrikeSelector:
    """
    Bear Put Spread strikes:
    - Buy  30-35 delta put (near ATM, captures downside)
    - Sell 10-15 delta put (OTM hedge)
    Width: $5-10 depending on confidence
    This is a net debit structure (buy ITM put, sell OTM put).
    """

    @staticmethod
    def select(spx_price: float, expiration: str, confidence: int = 3) -> Dict:
        spread_width = 10 if confidence >= 4 else 5

        # 30-35 delta put ≈ ATM
        buy_strike  = int(round(spx_price / 5) * 5)
        sell_strike = buy_strike - spread_width   # OTM put is lower strike

        est_buy_premium  = 2.00
        est_sell_premium = 0.60
        est_net_debit    = est_buy_premium - est_sell_premium

        max_profit_per_contract = (spread_width - est_net_debit) * 100
        max_loss_per_contract   = est_net_debit * 100

        return {
            "bot_type":    BotType.BEARISH,
            "buy_strike":  buy_strike,
            "sell_strike": sell_strike,
            "spread_width": spread_width,
            "est_net_debit": est_net_debit,
            "max_profit":  max_profit_per_contract,
            "max_loss":    max_loss_per_contract,
            "expiration":  expiration,
            "spx_price":   spx_price,
            "profit_target": max_profit_per_contract * 0.60,
            "stop_loss": -max_loss_per_contract * 0.50,
        }


class SidewaysStrikeSelector:
    """Iron condor — sell 20-delta both sides"""

    @staticmethod
    def select(spx_price: float, expiration: str, tight: bool = False) -> Dict:
        # 20-delta ≈ 0.75% OTM for typical 0DTE IV
        offset_pct = 0.006 if tight else 0.0075
        spread_width = 5

        call_sell = int(round(spx_price * (1 + offset_pct) / 5) * 5)
        call_buy  = call_sell + spread_width
        put_sell  = int(round(spx_price * (1 - offset_pct) / 5) * 5)
        put_buy   = put_sell - spread_width

        est_credit_per_side = 1.50
        total_credit = est_credit_per_side * 2
        max_loss     = (spread_width - total_credit) * 100

        return {
            "bot_type":   BotType.SIDEWAYS,
            "call_sell":  call_sell,
            "call_buy":   call_buy,
            "put_sell":   put_sell,
            "put_buy":    put_buy,
            "spread_width": spread_width,
            "est_total_credit": total_credit,
            "max_loss":   max_loss,
            "expiration": expiration,
            "spx_price":  spx_price,
            "profit_target": total_credit * 100 * 0.50,   # 50% of credit
            "tight": tight,
        }


# ============================================================================
# INTRADAY EXIT MANAGERS
# ============================================================================

class BullishExitManager:
    """Exit logic for Bull Call Spread"""

    @staticmethod
    def check(
        entry_spx: float,
        current_spx: float,
        current_pnl: float,
        entry_long_delta: float,
        current_long_delta: float,
        hours_held: float,
        hours_to_close: float,
        strikes: Dict,
    ) -> ExitSignal:

        move_pct = (current_spx - entry_spx) / entry_spx

        # ── Mandatory close ────────────────────────────────────────────
        if hours_to_close <= 0.5:
            return ExitSignal(True, "TIME_STOP", "IMMEDIATE", current_pnl, "3:30 PM mandatory close")

        # ── Profit target ──────────────────────────────────────────────
        if current_pnl >= strikes["profit_target"]:
            return ExitSignal(True, "TAKE_PROFIT", "NEXT_CYCLE", current_pnl,
                              f"Profit target hit: ${current_pnl:.0f} ≥ ${strikes['profit_target']:.0f}")

        # ── Delta stop (primary): long call lost >50% of delta ─────────
        if entry_long_delta > 0 and current_long_delta <= entry_long_delta * 0.50:
            return ExitSignal(True, "DELTA_STOP", "IMMEDIATE", current_pnl,
                              f"Long call delta dropped >50%: {entry_long_delta:.2f}→{current_long_delta:.2f} — momentum gone")

        # ── Hard dollar stop ───────────────────────────────────────────
        if current_pnl <= strikes["stop_loss"]:
            return ExitSignal(True, "STOP_LOSS", "IMMEDIATE", current_pnl,
                              f"Hard stop: P&L ${current_pnl:.0f} ≤ stop ${strikes['stop_loss']:.0f}")

        # ── Time-decay stop: no movement after 90 min ─────────────────
        if hours_held >= 1.5 and abs(move_pct) < 0.002:
            return ExitSignal(True, "TIME_STOP", "NEXT_CYCLE", current_pnl,
                              f"No movement after 90 min (move={move_pct*100:.2f}%) — theta bleeding")

        # ── Reversal stop: market went the wrong way ───────────────────
        if move_pct <= -0.005:
            return ExitSignal(True, "STOP_LOSS", "IMMEDIATE", current_pnl,
                              f"SPX reversed {move_pct*100:.2f}% — trend failed")

        return ExitSignal(False, "HOLD", "NONE", 0, "No exit signal")


class BearishExitManager:
    """Exit logic for Bear Put Spread"""

    @staticmethod
    def check(
        entry_spx: float,
        current_spx: float,
        current_pnl: float,
        entry_short_delta: float,
        current_short_delta: float,
        hours_held: float,
        hours_to_close: float,
        strikes: Dict,
    ) -> ExitSignal:

        move_pct = (current_spx - entry_spx) / entry_spx   # negative = down

        if hours_to_close <= 0.5:
            return ExitSignal(True, "TIME_STOP", "IMMEDIATE", current_pnl, "3:30 PM mandatory close")

        if current_pnl >= strikes["profit_target"]:
            return ExitSignal(True, "TAKE_PROFIT", "NEXT_CYCLE", current_pnl,
                              f"Profit target hit: ${current_pnl:.0f}")

        # Delta stop: short put delta rising means losses accelerating
        if entry_short_delta > 0 and current_short_delta >= entry_short_delta * 2.0:
            return ExitSignal(True, "DELTA_STOP", "IMMEDIATE", current_pnl,
                              f"Short put delta doubled: {entry_short_delta:.2f}→{current_short_delta:.2f} — exit to prevent blowout")

        if current_pnl <= strikes["stop_loss"]:
            return ExitSignal(True, "STOP_LOSS", "IMMEDIATE", current_pnl,
                              f"Hard stop: P&L ${current_pnl:.0f}")

        if hours_held >= 1.5 and abs(move_pct) < 0.002:
            return ExitSignal(True, "TIME_STOP", "NEXT_CYCLE", current_pnl,
                              f"No movement after 90 min — theta working against us")

        # Reversal: market bounced hard against position
        if move_pct >= 0.005:
            return ExitSignal(True, "STOP_LOSS", "IMMEDIATE", current_pnl,
                              f"SPX reversed up {move_pct*100:.2f}% — trend failed")

        return ExitSignal(False, "HOLD", "NONE", 0, "No exit signal")


class SidewaysExitManager:
    """Exit logic for Iron Condor"""

    @staticmethod
    def check(
        current_pnl: float,
        current_delta: float,
        hours_to_close: float,
        strikes: Dict,
        iv_spiked: bool = False,
    ) -> ExitSignal:

        if hours_to_close <= 0.5:
            return ExitSignal(True, "TIME_STOP", "IMMEDIATE", current_pnl, "3:30 PM mandatory close")

        if current_pnl >= strikes["profit_target"]:
            return ExitSignal(True, "TAKE_PROFIT", "NEXT_CYCLE", current_pnl,
                              f"50% credit captured: ${current_pnl:.0f}")

        if abs(current_delta) > 20:
            return ExitSignal(True, "DELTA_STOP", "IMMEDIATE", current_pnl,
                              f"Position delta={current_delta:.1f} > ±20 — one side threatened")

        if current_pnl <= -strikes["max_loss"] * 0.50:
            return ExitSignal(True, "STOP_LOSS", "IMMEDIATE", current_pnl,
                              f"Loss > 50% of max — cutting position")

        if iv_spiked:
            return ExitSignal(True, "STOP_LOSS", "NEXT_CYCLE", current_pnl,
                              "IV spiked — closing to avoid vol expansion blowout")

        return ExitSignal(False, "HOLD", "NONE", 0, "No exit signal")


# ============================================================================
# MAIN MULTI-BOT ENGINE
# ============================================================================

class MultiBotEngine:
    """
    Main entry point for the multi-bot 0DTE SPX trading engine.

    Orchestrates:
    1. Fetch EMA cloud regime (EMACloudsFilter)
    2. Fetch technical confirmation signals (TechnicalIndicators)
    3. Route to appropriate bot (BotRouter)
    4. Select strikes for the chosen bot
    5. Return fully prepared TradeSetup ready for execution

    Usage:
        engine = MultiBotEngine()
        setup = engine.analyze()

        if setup and setup["bot_type"] != BotType.NO_TRADE:
            # Pass to TastytradeOrderExecutor for execution
            executor.submit_trade(setup)
    """

    def __init__(self, account_size: float = 25000, risk_pct: float = 0.01):
        self.account_size   = account_size
        self.risk_pct       = risk_pct
        self.ema_filter     = EMACloudsFilter()
        self.router         = BotRouter()

    def analyze(self, expiration: Optional[str] = None) -> Optional[Dict]:
        """
        Run full analysis pipeline and return trade setup or None.

        Args:
            expiration: 0DTE expiration string (YYYY-MM-DD). If None, uses today.

        Returns:
            Dict with full trade setup, or None if no trade.
        """
        logger.info("=" * 70)
        logger.info(f"MultiBotEngine.analyze() — {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("=" * 70)

        # ── Market hours guard ─────────────────────────────────────────
        now  = datetime.now()
        hour = now.hour + now.minute / 60
        if not (9.5 <= hour <= 15.5):
            logger.info(f"Outside trading hours ({hour:.2f}h) — skipping")
            return None

        # ── Step 1: EMA Cloud Regime ───────────────────────────────────
        logger.info("Step 1 — Fetching EMA cloud regime...")
        ema = self.ema_filter.get_regime()
        logger.info(f"  {ema.summary()}")

        # ── Step 2: Technical Indicators ──────────────────────────────
        logger.info("Step 2 — Computing technical indicators...")
        tech = TechnicalIndicators.fetch_and_compute()
        if tech is None:
            logger.warning("Technical indicators unavailable — using defaults")
            tech = TechnicalSignals(adx=20, plus_di=20, minus_di=20,
                                    rsi=50, vix=18, spx_price=ema.spx_price)
        logger.info(f"  {tech.summary()}")

        # ── Step 3: Route ─────────────────────────────────────────────
        logger.info("Step 3 — Routing...")
        decision = self.router.route(ema, tech)
        logger.info(f"  {decision.summary()}")

        if decision.warnings:
            for w in decision.warnings:
                logger.warning(f"  ⚠ {w}")

        if decision.bot_type == BotType.NO_TRADE:
            logger.info(f"  → NO TRADE: {' | '.join(decision.reasons)}")
            return None

        # ── Step 4: Select Strikes ─────────────────────────────────────
        if expiration is None:
            expiration = now.strftime("%Y-%m-%d")

        spx_price = tech.spx_price
        logger.info(f"Step 4 — Selecting strikes (SPX=${spx_price:,.2f}, exp={expiration})...")

        if decision.bot_type == BotType.BULLISH:
            strikes = BullishStrikeSelector.select(spx_price, expiration, decision.confidence)
            logger.info(f"  BULL CALL: Buy {strikes['buy_strike']}C / Sell {strikes['sell_strike']}C")
            logger.info(f"  Est. debit: ${strikes['est_net_debit']:.2f} | "
                        f"Max profit: ${strikes['max_profit']:.0f} | Max loss: ${strikes['max_loss']:.0f}")

        elif decision.bot_type == BotType.BEARISH:
            strikes = BearishStrikeSelector.select(spx_price, expiration, decision.confidence)
            logger.info(f"  BEAR PUT: Buy {strikes['buy_strike']}P / Sell {strikes['sell_strike']}P")
            logger.info(f"  Est. debit: ${strikes['est_net_debit']:.2f} | "
                        f"Max profit: ${strikes['max_profit']:.0f} | Max loss: ${strikes['max_loss']:.0f}")

        else:  # SIDEWAYS
            tight = decision.confidence < 3
            strikes = SidewaysStrikeSelector.select(spx_price, expiration, tight=tight)
            logger.info(f"  IRON CONDOR: "
                        f"Calls {strikes['call_sell']}/{strikes['call_buy']} | "
                        f"Puts {strikes['put_sell']}/{strikes['put_buy']}"
                        + (" [TIGHT]" if tight else ""))
            logger.info(f"  Est. credit: ${strikes['est_total_credit']:.2f} | Max loss: ${strikes['max_loss']:.0f}")

        # ── Step 5: Position Sizing ─────────────────────────────────────
        max_risk_dollars = self.account_size * self.risk_pct

        # Directional bots use half the normal risk (higher single-direction risk)
        if decision.bot_type in (BotType.BULLISH, BotType.BEARISH):
            max_risk_dollars *= 0.75

        contracts = max(1, int(max_risk_dollars / strikes["max_loss"])) if strikes["max_loss"] > 0 else 1
        strikes["contracts"] = contracts

        total_risk = strikes["max_loss"] * contracts
        logger.info(f"Step 5 — Sizing: {contracts} contract(s) | Total max risk: ${total_risk:.0f}")

        # ── Final package ──────────────────────────────────────────────
        setup = {
            "bot_type":   decision.bot_type,
            "confidence": decision.confidence,
            "spx_price":  spx_price,
            "expiration": expiration,
            "strikes":    strikes,
            "ema_regime": ema.regime.value,
            "ema_confluence": ema.confluence_score,
            "adx":        tech.adx,
            "rsi":        tech.rsi,
            "vix":        tech.vix,
            "dtr_consumed": ema.dtr_consumed_pct,
            "timestamp":  now.isoformat(),
            "reasons":    decision.reasons,
            "warnings":   decision.warnings,
        }

        logger.info("=" * 70)
        logger.info(f"✅ Trade setup ready: {decision.bot_type.value} | "
                    f"Confidence {decision.confidence}/5 | {contracts} contract(s)")
        logger.info("=" * 70)

        return setup

    def get_exit_signal(
        self,
        setup: Dict,
        current_spx: float,
        current_pnl: float,
        hours_held: float,
        hours_to_close: float,
        current_delta: float = 0.0,
        entry_delta: float = 0.0,
        iv_spiked: bool = False,
    ) -> ExitSignal:
        """
        Intraday position monitoring.
        Call this on each monitoring cycle to get hold/exit decision.
        """
        bot_type = setup["bot_type"]
        strikes  = setup["strikes"]
        entry_spx = setup["spx_price"]

        if bot_type == BotType.BULLISH:
            return BullishExitManager.check(
                entry_spx, current_spx, current_pnl,
                entry_delta, current_delta,
                hours_held, hours_to_close, strikes
            )
        elif bot_type == BotType.BEARISH:
            return BearishExitManager.check(
                entry_spx, current_spx, current_pnl,
                entry_delta, current_delta,
                hours_held, hours_to_close, strikes
            )
        else:
            return SidewaysExitManager.check(
                current_pnl, current_delta,
                hours_to_close, strikes, iv_spiked
            )


# ============================================================================
# STANDALONE TEST / DEMO
# ============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s"
    )

    print("\n" + "=" * 70)
    print("  Multi-Bot 0DTE SPX Engine — Live Analysis")
    print("=" * 70 + "\n")

    engine = MultiBotEngine(account_size=25000, risk_pct=0.01)
    setup  = engine.analyze()

    if setup is None:
        print("→ NO TRADE (outside hours or filters blocked)")
        sys.exit(0)

    bot  = setup["bot_type"]
    s    = setup["strikes"]
    conf = setup["confidence"]
    conf_bar = "█" * conf + "░" * (5 - conf)

    print(f"\n{'='*70}")
    print(f"  RESULT: {bot.value} BOT  [{conf_bar}] {conf}/5 confidence")
    print(f"{'='*70}")
    print(f"  SPX Price      : ${setup['spx_price']:,.2f}")
    print(f"  Expiration     : {setup['expiration']}")
    print(f"  EMA Regime     : {setup['ema_regime']} ({setup['ema_confluence']}/3 confluence)")
    print(f"  ADX            : {setup['adx']:.1f}")
    print(f"  RSI            : {setup['rsi']:.1f}")
    print(f"  VIX            : {setup['vix']:.1f}")
    print(f"  DTR Consumed   : {setup['dtr_consumed']:.0f}%")
    print()

    if bot == BotType.BULLISH:
        print(f"  Trade          : BUY  {s['buy_strike']} CALL")
        print(f"                   SELL {s['sell_strike']} CALL")
        print(f"  Spread Width   : ${s['spread_width']}")
        print(f"  Est. Net Debit : ${s['est_net_debit']:.2f} per contract")
        print(f"  Max Profit     : ${s['max_profit']:.0f} per contract")
        print(f"  Max Loss       : ${s['max_loss']:.0f} per contract")
        print(f"  Profit Target  : ${s['profit_target']:.0f} (60% of max)")
        print(f"  Stop Loss      : ${s['stop_loss']:.0f} (50% of max loss)")

    elif bot == BotType.BEARISH:
        print(f"  Trade          : BUY  {s['buy_strike']} PUT")
        print(f"                   SELL {s['sell_strike']} PUT")
        print(f"  Spread Width   : ${s['spread_width']}")
        print(f"  Est. Net Debit : ${s['est_net_debit']:.2f} per contract")
        print(f"  Max Profit     : ${s['max_profit']:.0f} per contract")
        print(f"  Max Loss       : ${s['max_loss']:.0f} per contract")
        print(f"  Profit Target  : ${s['profit_target']:.0f} (60% of max)")
        print(f"  Stop Loss      : ${s['stop_loss']:.0f} (50% of max loss)")

    else:
        tight_label = " [TIGHT STRIKES]" if s.get("tight") else ""
        print(f"  Trade          : SELL {s['call_sell']} CALL / BUY {s['call_buy']} CALL")
        print(f"                   SELL {s['put_sell']}  PUT  / BUY {s['put_buy']}  PUT")
        print(f"  Spread Width   : ${s['spread_width']}{tight_label}")
        print(f"  Est. Credit    : ${s['est_total_credit']:.2f} per spread")
        print(f"  Max Loss       : ${s['max_loss']:.0f} per contract")
        print(f"  Profit Target  : ${s['profit_target']:.0f} (50% of credit)")

    print()
    print(f"  Contracts      : {s['contracts']}")
    print(f"  Total Max Risk : ${s['max_loss'] * s['contracts']:.0f}")
    print()
    print(f"  Signal Rationale:")
    for r in setup["reasons"]:
        print(f"    ✓ {r}")
    if setup["warnings"]:
        for w in setup["warnings"]:
            print(f"    ⚠ {w}")

    print()

    # ── Demo exit signal simulation ────────────────────────────────
    print(f"{'─'*70}")
    print(f"  Exit Signal Simulation (45 min in, P&L +$120, unchanged SPX):")
    exit_sig = engine.get_exit_signal(
        setup=setup,
        current_spx=setup["spx_price"],
        current_pnl=120,
        hours_held=0.75,
        hours_to_close=4.0,
        current_delta=0.10,
        entry_delta=0.30,
    )
    action_icon = "🔴" if exit_sig.should_exit else "🟢"
    print(f"  {action_icon} Action: {exit_sig.action} | Urgency: {exit_sig.urgency}")
    print(f"    Reason: {exit_sig.reason}")
    print("=" * 70 + "\n")
