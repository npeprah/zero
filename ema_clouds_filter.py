#!/usr/bin/env python3
"""
Ripster EMA Clouds Filter — Multi-Timeframe Regime Detection
for 0DTE SPX Trading

Inspired by the Ripster EMA Clouds TradingView indicator suite.
Uses 3 timeframes to determine market regime before entering trades:

    1-Hour Cloud  (EMA 34 / EMA 50)  → Primary trend signal
    Daily Fast    (EMA 20 / EMA 21)  → Short-term daily bias
    Daily Slow    (EMA 50 / EMA 55)  → Long-term daily bias

Regime Rules:
    BULLISH  = price ABOVE 1hr cloud  + daily clouds confirm
    BEARISH  = price BELOW 1hr cloud  + daily clouds confirm
    SIDEWAYS = price INSIDE 1hr cloud, or daily/hourly conflict
    UNKNOWN  = data unavailable (fail-safe, neutral)

DTR Guard (Daily True Range):
    If > 80% of ATR consumed after 2pm ET → force SIDEWAYS
    (prevents chasing exhausted moves late in the session)
"""

import logging
import pandas as pd
import yfinance as yf
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class MarketRegime(Enum):
    BULLISH  = "BULLISH"
    BEARISH  = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN  = "UNKNOWN"


@dataclass
class CloudPosition:
    """
    Position of price relative to a single EMA cloud.
    Cloud = the band between two EMAs.
    """
    price:        float
    ema_top:      float   # Higher of the two EMAs
    ema_bottom:   float   # Lower of the two EMAs
    cloud_width:  float   # Spread between EMAs (wider = stronger trend)

    @property
    def above(self) -> bool:
        return self.price > self.ema_top

    @property
    def below(self) -> bool:
        return self.price < self.ema_bottom

    @property
    def inside(self) -> bool:
        return self.ema_bottom <= self.price <= self.ema_top

    @property
    def position(self) -> str:
        if self.above:  return "ABOVE"
        if self.below:  return "BELOW"
        return "INSIDE"

    @property
    def clearance_pts(self) -> float:
        """How many points price is clear of the cloud (+ = above, - = below, 0 = inside)"""
        if self.above:  return self.price - self.ema_top
        if self.below:  return self.price - self.ema_bottom
        return 0.0


@dataclass
class EMACloudAnalysis:
    """
    Complete multi-timeframe EMA cloud analysis result.
    """
    regime:           MarketRegime

    # 1-Hour Cloud (EMA 34 / EMA 50) — primary signal
    hourly_cloud:     CloudPosition
    hourly_ema34:     float
    hourly_ema50:     float

    # Daily Fast Cloud (EMA 20 / EMA 21)
    daily_fast_cloud: CloudPosition
    daily_ema20:      float
    daily_ema21:      float

    # Daily Slow Cloud (EMA 50 / EMA 55)
    daily_slow_cloud: CloudPosition
    daily_ema50:      float
    daily_ema55:      float

    # DTR metrics
    current_range:    float   # Today's High - Low so far
    atr_14:           float   # 14-period ATR on daily
    dtr_consumed_pct: float   # % of typical daily range consumed

    # Meta
    spx_price:        float
    timestamp:        str
    confluence_score: int     # 0-3 (how many timeframes agree)
    is_high_confidence: bool  # True if confluence >= 2

    def summary(self) -> str:
        """Human-readable one-liner"""
        dtr = f"{self.dtr_consumed_pct:.0f}%"
        conf = "★" * self.confluence_score + "☆" * (3 - self.confluence_score)
        return (
            f"Regime: {self.regime.value} [{conf}] | "
            f"1Hr: {self.hourly_cloud.position} cloud | "
            f"Daily fast: {self.daily_fast_cloud.position} | "
            f"Daily slow: {self.daily_slow_cloud.position} | "
            f"DTR consumed: {dtr} | "
            f"SPX: ${self.spx_price:,.2f}"
        )


# ============================================================================
# MAIN FILTER CLASS
# ============================================================================

class EMACloudsFilter:
    """
    Ripster-style EMA Clouds multi-timeframe regime detector.

    Usage:
        filter = EMACloudsFilter()
        analysis = filter.get_regime()

        if analysis.regime == MarketRegime.SIDEWAYS:
            # run iron condor bot
        elif analysis.regime == MarketRegime.BULLISH and analysis.is_high_confidence:
            # run bullish bot
        elif analysis.regime == MarketRegime.BEARISH and analysis.is_high_confidence:
            # run bearish bot
        else:
            # skip — low confidence or unknown
    """

    # Yahoo Finance ticker for SPX
    DEFAULT_SYMBOL = "^GSPC"

    def __init__(self, symbol: str = DEFAULT_SYMBOL):
        self.symbol = symbol

    # ── Public API ────────────────────────────────────────────────────────────

    def get_regime(self) -> EMACloudAnalysis:
        """
        Fetch latest SPX data and return full regime analysis.
        Falls back to UNKNOWN on any data error — never crashes the bot.
        """
        try:
            hourly_df = self._fetch(interval="1h",  period="10d")
            daily_df  = self._fetch(interval="1d",  period="90d")

            if hourly_df is None or len(hourly_df) < 55:
                logger.warning("EMA clouds: insufficient 1-hour data")
                return self._unknown()

            if daily_df is None or len(daily_df) < 60:
                logger.warning("EMA clouds: insufficient daily data")
                return self._unknown()

            analysis = self._analyze(hourly_df, daily_df)
            logger.info(f"EMA Clouds → {analysis.summary()}")
            return analysis

        except Exception as e:
            logger.error(f"EMACloudsFilter.get_regime() error: {e}", exc_info=True)
            return self._unknown()

    # ── Data Fetching ─────────────────────────────────────────────────────────

    def _fetch(self, interval: str, period: str) -> Optional[pd.DataFrame]:
        """Download OHLCV history via yfinance"""
        try:
            ticker = yf.Ticker(self.symbol)
            df = ticker.history(interval=interval, period=period, auto_adjust=True)
            if df.empty:
                logger.warning(f"yfinance returned empty df ({interval}, {period})")
                return None
            df.index = pd.to_datetime(df.index, utc=True)
            return df
        except Exception as e:
            logger.error(f"yfinance fetch error ({interval}): {e}")
            return None

    # ── Indicator Calculations ────────────────────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> float:
        """EMA of a price series, return the latest value"""
        return series.ewm(span=period, adjust=False).mean().iloc[-1]

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        """Wilder ATR (EMA-style) on daily data"""
        prev_close = df["Close"].shift(1)
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().iloc[-1]

    @staticmethod
    def _cloud(price: float, ema_a: float, ema_b: float) -> CloudPosition:
        return CloudPosition(
            price=price,
            ema_top=max(ema_a, ema_b),
            ema_bottom=min(ema_a, ema_b),
            cloud_width=abs(ema_a - ema_b),
        )

    # ── Core Analysis ─────────────────────────────────────────────────────────

    def _analyze(self, hourly_df: pd.DataFrame, daily_df: pd.DataFrame) -> EMACloudAnalysis:
        """Calculate all EMAs and determine regime"""

        spx = float(hourly_df["Close"].iloc[-1])

        # ── 1-Hour Cloud (34 / 50) ─────────────────────────────────────
        h34 = self._ema(hourly_df["Close"], 34)
        h50 = self._ema(hourly_df["Close"], 50)
        hourly_cloud = self._cloud(spx, h34, h50)

        # ── Daily Fast Cloud (20 / 21) ──────────────────────────────────
        d20 = self._ema(daily_df["Close"], 20)
        d21 = self._ema(daily_df["Close"], 21)
        daily_fast = self._cloud(spx, d20, d21)

        # ── Daily Slow Cloud (50 / 55) ──────────────────────────────────
        d50 = self._ema(daily_df["Close"], 50)
        d55 = self._ema(daily_df["Close"], 55)
        daily_slow = self._cloud(spx, d50, d55)

        # ── DTR ─────────────────────────────────────────────────────────
        today_row    = daily_df.iloc[-1]
        day_range    = float(today_row["High"] - today_row["Low"])
        atr14        = self._atr(daily_df, 14)
        dtr_consumed = (day_range / atr14 * 100) if atr14 > 0 else 50.0

        # ── Regime ──────────────────────────────────────────────────────
        regime, confluence = self._determine_regime(
            hourly_cloud, daily_fast, daily_slow, dtr_consumed
        )

        return EMACloudAnalysis(
            regime=regime,
            hourly_cloud=hourly_cloud,
            hourly_ema34=h34, hourly_ema50=h50,
            daily_fast_cloud=daily_fast,
            daily_ema20=d20, daily_ema21=d21,
            daily_slow_cloud=daily_slow,
            daily_ema50=d50, daily_ema55=d55,
            current_range=day_range,
            atr_14=atr14,
            dtr_consumed_pct=dtr_consumed,
            spx_price=spx,
            timestamp=datetime.now().isoformat(),
            confluence_score=confluence,
            is_high_confidence=(confluence >= 2),
        )

    def _determine_regime(
        self,
        hourly:      CloudPosition,
        daily_fast:  CloudPosition,
        daily_slow:  CloudPosition,
        dtr_consumed: float,
    ) -> Tuple[MarketRegime, int]:
        """
        Core regime logic.

        Scoring:
            +1 if 1-hour cloud position matches direction (always — primary signal)
            +1 if daily fast cloud confirms
            +1 if daily slow cloud confirms
            Max score = 3 (full confluence)

        DTR Guard:
            After 2pm ET, if >80% of ATR consumed → SIDEWAYS regardless
            (market likely exhausted, spreads should narrow not widen)
        """
        now = datetime.now()

        # ── INSIDE hourly cloud = no clear direction ─────────────────────
        if hourly.inside:
            return MarketRegime.SIDEWAYS, 0

        # ── DTR late-day exhaustion guard ────────────────────────────────
        if now.hour >= 14 and dtr_consumed > 80:
            logger.info(
                f"DTR guard: {dtr_consumed:.0f}% consumed after 2pm — "
                "market likely exhausted, downgrading to SIDEWAYS"
            )
            return MarketRegime.SIDEWAYS, 1

        # ── BULLISH: price above 1hr cloud ───────────────────────────────
        if hourly.above:
            confluence = 1  # primary signal always counts
            if daily_fast.above or daily_fast.inside:
                confluence += 1
            if daily_slow.above or daily_slow.inside:
                confluence += 1
            return MarketRegime.BULLISH, confluence

        # ── BEARISH: price below 1hr cloud ───────────────────────────────
        else:
            confluence = 1
            if daily_fast.below or daily_fast.inside:
                confluence += 1
            if daily_slow.below or daily_slow.inside:
                confluence += 1
            return MarketRegime.BEARISH, confluence

    # ── Fallback ──────────────────────────────────────────────────────────────

    def _unknown(self) -> EMACloudAnalysis:
        """Safe fallback when data is unavailable"""
        dummy = CloudPosition(price=0, ema_top=0, ema_bottom=0, cloud_width=0)
        return EMACloudAnalysis(
            regime=MarketRegime.UNKNOWN,
            hourly_cloud=dummy, hourly_ema34=0, hourly_ema50=0,
            daily_fast_cloud=dummy, daily_ema20=0, daily_ema21=0,
            daily_slow_cloud=dummy, daily_ema50=0, daily_ema55=0,
            current_range=0, atr_14=0, dtr_consumed_pct=50,
            spx_price=0,
            timestamp=datetime.now().isoformat(),
            confluence_score=0,
            is_high_confidence=False,
        )


# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 70)
    print("  Ripster EMA Clouds Filter — Live Test")
    print("=" * 70)

    f = EMACloudsFilter()
    result = f.get_regime()

    print(f"\n{result.summary()}\n")
    print(f"  Regime          : {result.regime.value}")
    print(f"  Confidence      : {result.confluence_score}/3 {'(HIGH)' if result.is_high_confidence else '(LOW)'}")
    print(f"  SPX Price       : ${result.spx_price:,.2f}")
    print()
    print(f"  1-Hr EMA34      : {result.hourly_ema34:,.2f}")
    print(f"  1-Hr EMA50      : {result.hourly_ema50:,.2f}")
    print(f"  1-Hr Cloud      : {result.hourly_cloud.position}  "
          f"(clearance: {result.hourly_cloud.clearance_pts:+.1f} pts)")
    print()
    print(f"  Daily EMA20     : {result.daily_ema20:,.2f}")
    print(f"  Daily EMA21     : {result.daily_ema21:,.2f}")
    print(f"  Daily Fast Cloud: {result.daily_fast_cloud.position}")
    print()
    print(f"  Daily EMA50     : {result.daily_ema50:,.2f}")
    print(f"  Daily EMA55     : {result.daily_ema55:,.2f}")
    print(f"  Daily Slow Cloud: {result.daily_slow_cloud.position}")
    print()
    print(f"  ATR (14)        : {result.atr_14:.1f} pts")
    print(f"  DTR Consumed    : {result.dtr_consumed_pct:.0f}%")
    print()
    print("  ─── Bot Routing ────────────────────────────────────────────")
    if result.regime == MarketRegime.SIDEWAYS:
        print("  → Run SIDEWAYS BOT (Iron Condor)")
    elif result.regime == MarketRegime.BULLISH and result.is_high_confidence:
        print("  → Run BULLISH BOT (Bull Call Spread)")
    elif result.regime == MarketRegime.BEARISH and result.is_high_confidence:
        print("  → Run BEARISH BOT (Bear Put Spread)")
    elif result.regime == MarketRegime.UNKNOWN:
        print("  → SKIP — data unavailable")
    else:
        print(f"  → SKIP — {result.regime.value} but low confidence ({result.confluence_score}/3)")
    print("=" * 70)
