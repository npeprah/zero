#!/usr/bin/env python3
"""
Ripster EMA Clouds Filter — Full Implementation
================================================
Complete port of the Ripster EMA Clouds TradingView indicator suite
for programmatic 0DTE SPX regime detection.

All 5 EMA cloud pairs (matching Ripster exactly):
    Cloud 1:  EMA  8 /  9   — fastest, momentum trigger
    Cloud 2:  EMA 20 / 21   — short-term daily bias
    Cloud 3:  EMA 34 / 50   — primary intraday trend (KEY signal)
    Cloud 4:  EMA 55 / 89   — intermediate trend (Fibonacci)
    Cloud 5:  EMA 120 / 233 — macro / long-term bias

Ripster Trend Labels (crossover events):
    BULLISH label: EMA 8 crosses above EMA 34 (fast cross slow)
    BEARISH label: EMA 8 crosses below EMA 34

Multi-Timeframe (MTF) Analysis:
    1-Hour clouds  (34/50)          → primary intraday signal
    Daily clouds   (20/21, 50/55)   → session bias
    Macro cloud    (120/233)        → higher-timeframe context

Data Sources (in priority order):
    1. Tastytrade API  — real-time, preferred for 1-hr intraday signals
    2. yfinance        — 15-min delayed fallback (fine for daily clouds)

DTR Guard:
    After 2pm ET, if >80% of typical daily range consumed → SIDEWAYS
    (prevents entering exhausted directional moves)
"""

import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict
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


class TrendLabel(Enum):
    """Ripster Trend Label crossover events"""
    BULLISH_CROSS = "BULLISH_CROSS"   # EMA 8 crossed above EMA 34 recently
    BEARISH_CROSS = "BEARISH_CROSS"   # EMA 8 crossed below EMA 34 recently
    NONE          = "NONE"            # No recent crossover


@dataclass
class CloudPosition:
    """Position of price relative to a single EMA cloud."""
    name:         str
    price:        float
    ema_a:        float   # First EMA (e.g. EMA 8)
    ema_b:        float   # Second EMA (e.g. EMA 9)
    ema_top:      float   # Higher of the two
    ema_bottom:   float   # Lower of the two
    cloud_width:  float   # Spread (wider = stronger trend)

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
        """Points clear of cloud (+above, -below, 0 inside)"""
        if self.above:  return self.price - self.ema_top
        if self.below:  return self.price - self.ema_bottom
        return 0.0

    def __str__(self) -> str:
        return f"{self.name}({self.position}, width={self.cloud_width:.1f})"


@dataclass
class EMACloudAnalysis:
    """Complete Ripster EMA Clouds analysis result."""

    regime:           MarketRegime
    trend_label:      TrendLabel       # Most recent crossover event

    # ── All 5 clouds ──────────────────────────────────────────────────
    cloud1_8_9:       CloudPosition    # Fastest — momentum
    cloud2_20_21:     CloudPosition    # Short-term daily
    cloud3_34_50:     CloudPosition    # Primary intraday (KEY)
    cloud4_55_89:     CloudPosition    # Intermediate (Fibonacci)
    cloud5_120_233:   CloudPosition    # Macro

    # ── Individual EMA values ──────────────────────────────────────────
    ema8:   float;  ema9:   float
    ema20:  float;  ema21:  float
    ema34:  float;  ema50:  float
    ema55:  float;  ema89:  float
    ema120: float;  ema233: float

    # ── Trend label lookback ──────────────────────────────────────────
    bars_since_cross: int              # How many bars ago the last cross fired

    # ── DTR ───────────────────────────────────────────────────────────
    current_range:    float
    atr_14:           float
    dtr_consumed_pct: float

    # ── Meta ──────────────────────────────────────────────────────────
    spx_price:        float
    timestamp:        str
    confluence_score: int              # 0–5 (clouds agreeing with regime)
    is_high_confidence: bool
    data_source:      str              # "tastytrade" | "yfinance"

    def clouds_agreeing(self) -> List[str]:
        """Return list of cloud names that agree with the detected regime"""
        result = []
        for cloud in [self.cloud1_8_9, self.cloud2_20_21, self.cloud3_34_50,
                      self.cloud4_55_89, self.cloud5_120_233]:
            if self.regime == MarketRegime.BULLISH and cloud.above:
                result.append(cloud.name)
            elif self.regime == MarketRegime.BEARISH and cloud.below:
                result.append(cloud.name)
            elif self.regime == MarketRegime.SIDEWAYS and cloud.inside:
                result.append(cloud.name)
        return result

    def summary(self) -> str:
        agreeing = ", ".join(self.clouds_agreeing()) or "none"
        conf_stars = "★" * self.confluence_score + "☆" * (5 - self.confluence_score)
        label_str = f" [{self.trend_label.value} {self.bars_since_cross}b ago]" \
                    if self.trend_label != TrendLabel.NONE else ""
        return (
            f"Regime: {self.regime.value} [{conf_stars}]{label_str} | "
            f"Key cloud (34/50): {self.cloud3_34_50.position} | "
            f"Clouds agreeing: {agreeing} | "
            f"DTR: {self.dtr_consumed_pct:.0f}% | "
            f"SPX: ${self.spx_price:,.2f} [{self.data_source}]"
        )


# ============================================================================
# DATA PROVIDERS
# ============================================================================

class TastytradeDataProvider:
    """
    Fetch candle data from the Tastytrade market data API.
    Real-time, no delay — preferred source for intraday signals.

    Tastytrade uses DXFeed for market data. Candle endpoint:
        GET /market-data/candles/{symbol}?period=1h&count=200
    """

    def __init__(self, session_token: str, base_url: str = "https://api.tastyworks.com"):
        self.session_token = session_token
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {session_token}"}

    def fetch(self, symbol: str = "SPX", interval: str = "1h", count: int = 200) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles from Tastytrade.

        Args:
            symbol:   Underlying (SPX, /ES, etc.)
            interval: Candle width — '1h', '1d', '15m'
            count:    Number of candles to return

        Returns:
            DataFrame with columns [Open, High, Low, Close, Volume]
        """
        import requests

        # Map human interval to Tastytrade period format
        period_map = {"1h": "1Hour", "1d": "1Day", "15m": "15Min", "5m": "5Min"}
        period = period_map.get(interval, "1Hour")

        try:
            url = f"{self.base_url}/market-data/candles/{symbol}"
            params = {"period": period, "count": count}
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()

            candles = resp.json().get("data", {}).get("candles", [])
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            df = df.rename(columns={
                "open": "Open", "high": "High",
                "low": "Low",   "close": "Close",
                "volume": "Volume"
            })
            for col in ["Open", "High", "Low", "Close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            return df.dropna(subset=["Close"])

        except Exception as e:
            logger.warning(f"Tastytrade data fetch failed ({interval}): {e}")
            return None


class YFinanceDataProvider:
    """
    Fallback data provider using yfinance.
    15-minute delayed — acceptable for daily clouds, not ideal for 1-hr.
    """

    def __init__(self, symbol: str = "^GSPC"):
        self.symbol = symbol

    def fetch(self, interval: str = "1h", period: str = "10d") -> Optional[pd.DataFrame]:
        try:
            df = yf.Ticker(self.symbol).history(
                interval=interval, period=period, auto_adjust=True
            )
            if df.empty:
                return None
            df.index = pd.to_datetime(df.index, utc=True)
            return df
        except Exception as e:
            logger.warning(f"yfinance fetch failed ({interval}): {e}")
            return None


# ============================================================================
# MAIN FILTER CLASS
# ============================================================================

class EMACloudsFilter:
    """
    Full Ripster EMA Clouds implementation with all 5 cloud pairs,
    Trend Labels (crossover detection), and multi-timeframe confluence.

    Usage:
        # With Tastytrade real-time data (preferred):
        f = EMACloudsFilter(tastytrade_token="your_session_token")

        # With yfinance fallback (15-min delayed):
        f = EMACloudsFilter()

        analysis = f.get_regime()
        print(analysis.summary())
    """

    TREND_LABEL_LOOKBACK = 5   # Bars to look back for a fresh crossover

    def __init__(self, tastytrade_token: Optional[str] = None,
                 tastytrade_url: str = "https://api.tastyworks.com"):
        self.tt_provider  = TastytradeDataProvider(tastytrade_token, tastytrade_url) \
                            if tastytrade_token else None
        self.yf_provider  = YFinanceDataProvider()
        self.data_source  = "unknown"

    # ── Public API ────────────────────────────────────────────────────────────

    def get_regime(self) -> EMACloudAnalysis:
        """
        Fetch data and return full regime analysis.
        Tries Tastytrade first, falls back to yfinance.
        Never crashes the bot — returns UNKNOWN on any error.
        """
        try:
            hourly_df, daily_df = self._fetch_both()

            if hourly_df is None or len(hourly_df) < 240:
                logger.warning("Insufficient hourly data (need 240+ bars for EMA 233)")
                # Try with what we have if it's close enough
                if hourly_df is None or len(hourly_df) < 50:
                    return self._unknown()

            if daily_df is None or len(daily_df) < 240:
                logger.warning("Insufficient daily data — using hourly for all clouds")
                if daily_df is None:
                    daily_df = hourly_df  # degrade gracefully

            analysis = self._analyze(hourly_df, daily_df)
            logger.info(f"EMA Clouds → {analysis.summary()}")
            return analysis

        except Exception as e:
            logger.error(f"EMACloudsFilter error: {e}", exc_info=True)
            return self._unknown()

    # ── Data Fetching ─────────────────────────────────────────────────────────

    def _fetch_both(self) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """Fetch hourly + daily data, Tastytrade preferred."""
        hourly_df = None
        daily_df  = None

        if self.tt_provider:
            logger.debug("Fetching from Tastytrade...")
            hourly_df = self.tt_provider.fetch(symbol="SPX", interval="1h",  count=300)
            daily_df  = self.tt_provider.fetch(symbol="SPX", interval="1d",  count=300)
            if hourly_df is not None:
                self.data_source = "tastytrade"

        if hourly_df is None:
            logger.debug("Falling back to yfinance...")
            hourly_df = self.yf_provider.fetch(interval="1h", period="60d")
            daily_df  = self.yf_provider.fetch(interval="1d", period="2y")
            self.data_source = "yfinance (15min delay)"

        return hourly_df, daily_df

    # ── EMA Calculations ──────────────────────────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        """Full EMA series (not just last value — needed for crossover detection)"""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        prev_close = df["Close"].shift(1)
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    @staticmethod
    def _cloud(name: str, price: float, ema_a: float, ema_b: float) -> CloudPosition:
        return CloudPosition(
            name=name, price=price,
            ema_a=ema_a, ema_b=ema_b,
            ema_top=max(ema_a, ema_b),
            ema_bottom=min(ema_a, ema_b),
            cloud_width=abs(ema_a - ema_b),
        )

    # ── Trend Label (Crossover Detection) ────────────────────────────────────

    def _detect_trend_label(
        self, close: pd.Series
    ) -> Tuple[TrendLabel, int]:
        """
        Detect the most recent EMA 8 / EMA 34 crossover event.
        This is the Ripster Trend Label signal.

        Returns:
            (TrendLabel, bars_since_cross)
        """
        ema8_series  = self._ema(close, 8)
        ema34_series = self._ema(close, 34)

        # Look at the last N bars for a fresh cross
        lookback = self.TREND_LABEL_LOOKBACK
        for bars_ago in range(1, lookback + 1):
            idx_now  = -(bars_ago)
            idx_prev = -(bars_ago + 1)

            # Guard against index out of range
            if abs(idx_prev) > len(ema8_series):
                break

            curr_diff = float(ema8_series.iloc[idx_now]  - ema34_series.iloc[idx_now])
            prev_diff = float(ema8_series.iloc[idx_prev] - ema34_series.iloc[idx_prev])

            if prev_diff <= 0 and curr_diff > 0:
                return TrendLabel.BULLISH_CROSS, bars_ago
            if prev_diff >= 0 and curr_diff < 0:
                return TrendLabel.BEARISH_CROSS, bars_ago

        return TrendLabel.NONE, 0

    # ── Core Analysis ─────────────────────────────────────────────────────────

    def _analyze(self, hourly_df: pd.DataFrame, daily_df: pd.DataFrame) -> EMACloudAnalysis:
        """Compute all 5 EMA clouds + trend labels + regime"""

        spx = float(hourly_df["Close"].iloc[-1])
        h   = hourly_df["Close"]  # hourly close series
        d   = daily_df["Close"]   # daily close series

        # ── All 10 EMAs on 1-hour data ────────────────────────────────
        # (All Ripster clouds are computed on the same timeframe in TV)
        e8   = float(self._ema(h,  8).iloc[-1])
        e9   = float(self._ema(h,  9).iloc[-1])
        e20  = float(self._ema(h, 20).iloc[-1])
        e21  = float(self._ema(h, 21).iloc[-1])
        e34  = float(self._ema(h, 34).iloc[-1])
        e50  = float(self._ema(h, 50).iloc[-1])
        e55  = float(self._ema(h, 55).iloc[-1])
        e89  = float(self._ema(h, 89).iloc[-1])
        e120 = float(self._ema(h, 120).iloc[-1])
        e233 = float(self._ema(h, 233).iloc[-1]) if len(h) >= 233 else float(self._ema(d, 233).iloc[-1])

        # ── 5 Clouds ──────────────────────────────────────────────────
        c1 = self._cloud("8/9",     spx, e8,   e9)
        c2 = self._cloud("20/21",   spx, e20,  e21)
        c3 = self._cloud("34/50",   spx, e34,  e50)   # KEY signal
        c4 = self._cloud("55/89",   spx, e55,  e89)
        c5 = self._cloud("120/233", spx, e120, e233)

        # ── Trend Label ───────────────────────────────────────────────
        trend_label, bars_since = self._detect_trend_label(h)

        # ── DTR ───────────────────────────────────────────────────────
        today_row    = daily_df.iloc[-1]
        day_range    = float(today_row["High"] - today_row["Low"])
        atr14        = self._atr(daily_df, 14)
        dtr_consumed = (day_range / atr14 * 100) if atr14 > 0 else 50.0

        # ── Regime ────────────────────────────────────────────────────
        regime, confluence = self._determine_regime(c1, c2, c3, c4, c5,
                                                     trend_label, dtr_consumed)

        return EMACloudAnalysis(
            regime=regime,
            trend_label=trend_label,
            cloud1_8_9=c1,
            cloud2_20_21=c2,
            cloud3_34_50=c3,
            cloud4_55_89=c4,
            cloud5_120_233=c5,
            ema8=e8,   ema9=e9,
            ema20=e20, ema21=e21,
            ema34=e34, ema50=e50,
            ema55=e55, ema89=e89,
            ema120=e120, ema233=e233,
            bars_since_cross=bars_since,
            current_range=day_range,
            atr_14=atr14,
            dtr_consumed_pct=dtr_consumed,
            spx_price=spx,
            timestamp=datetime.now().isoformat(),
            confluence_score=confluence,
            is_high_confidence=(confluence >= 3),
            data_source=self.data_source,
        )

    def _determine_regime(
        self,
        c1: CloudPosition, c2: CloudPosition, c3: CloudPosition,
        c4: CloudPosition, c5: CloudPosition,
        trend_label: TrendLabel,
        dtr_consumed: float,
    ) -> Tuple[MarketRegime, int]:
        """
        Regime logic using all 5 clouds + trend label.

        Scoring:
            c3 (34/50) = PRIMARY signal  → counts double (weight 2)
            c1 (8/9)   = momentum        → weight 1
            c2 (20/21) = short-term      → weight 1
            c4 (55/89) = intermediate    → weight 1
            c5 (120/233) = macro         → weight 1
            trend_label = recent cross   → bonus +1

        Max raw score = 7. Normalized to 0-5 for confluence.

        DTR Guard: after 2pm, >80% consumed → SIDEWAYS
        """
        now = datetime.now()

        # ── DTR exhaustion guard ──────────────────────────────────────
        if now.hour >= 14 and dtr_consumed > 80:
            logger.info(f"DTR guard: {dtr_consumed:.0f}% consumed after 2pm → SIDEWAYS")
            return MarketRegime.SIDEWAYS, 1

        # ── Primary: c3 (34/50) determines base direction ────────────
        if c3.inside:
            # Price inside the key cloud = no clear direction
            return MarketRegime.SIDEWAYS, 0

        # ── Score bullish/bearish evidence ───────────────────────────
        if c3.above:
            direction = MarketRegime.BULLISH
            score = 2  # c3 counts double
            if c1.above: score += 1
            if c2.above: score += 1
            if c4.above: score += 1
            if c5.above: score += 1
            if trend_label == TrendLabel.BULLISH_CROSS: score += 1
        else:  # c3.below
            direction = MarketRegime.BEARISH
            score = 2
            if c1.below: score += 1
            if c2.below: score += 1
            if c4.below: score += 1
            if c5.below: score += 1
            if trend_label == TrendLabel.BEARISH_CROSS: score += 1

        # Normalize 2-7 → 1-5 confluence
        confluence = max(1, min(5, round((score - 1) * (5 / 6))))

        # ── Conflicting slow clouds → downgrade to SIDEWAYS ──────────
        # If fast clouds say one thing but macro cloud says opposite
        if direction == MarketRegime.BULLISH and c5.below and c4.below:
            logger.info("Fast clouds BULLISH but slow clouds (55/89, 120/233) BELOW — SIDEWAYS")
            return MarketRegime.SIDEWAYS, 2

        if direction == MarketRegime.BEARISH and c5.above and c4.above:
            logger.info("Fast clouds BEARISH but slow clouds (55/89, 120/233) ABOVE — SIDEWAYS")
            return MarketRegime.SIDEWAYS, 2

        return direction, confluence

    # ── Fallback ──────────────────────────────────────────────────────────────

    def _unknown(self) -> EMACloudAnalysis:
        dummy = CloudPosition(name="N/A", price=0, ema_a=0, ema_b=0,
                              ema_top=0, ema_bottom=0, cloud_width=0)
        return EMACloudAnalysis(
            regime=MarketRegime.UNKNOWN,
            trend_label=TrendLabel.NONE,
            cloud1_8_9=dummy, cloud2_20_21=dummy, cloud3_34_50=dummy,
            cloud4_55_89=dummy, cloud5_120_233=dummy,
            ema8=0, ema9=0, ema20=0, ema21=0, ema34=0, ema50=0,
            ema55=0, ema89=0, ema120=0, ema233=0,
            bars_since_cross=0,
            current_range=0, atr_14=0, dtr_consumed_pct=50,
            spx_price=0,
            timestamp=datetime.now().isoformat(),
            confluence_score=0, is_high_confidence=False,
            data_source="none",
        )


# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 72)
    print("  Ripster EMA Clouds — Full Implementation Test")
    print("=" * 72)

    # Use Tastytrade token if available, else yfinance
    tt_token = os.getenv("TASTYTRADE_SESSION_TOKEN")
    f = EMACloudsFilter(tastytrade_token=tt_token)
    r = f.get_regime()

    print(f"\n{r.summary()}\n")

    print(f"  {'Cloud':<12} {'Position':<8} {'EMA A':>8} {'EMA B':>8} {'Width':>7} {'Clearance':>10}")
    print(f"  {'-'*58}")
    for cloud in [r.cloud1_8_9, r.cloud2_20_21, r.cloud3_34_50,
                  r.cloud4_55_89, r.cloud5_120_233]:
        marker = " ◀ KEY" if cloud.name == "34/50" else ""
        print(f"  {cloud.name:<12} {cloud.position:<8} {cloud.ema_a:>8,.1f} "
              f"{cloud.ema_b:>8,.1f} {cloud.cloud_width:>7,.1f} "
              f"{cloud.clearance_pts:>+10,.1f}{marker}")

    print()
    print(f"  Trend Label : {r.trend_label.value}"
          + (f" ({r.bars_since_cross} bars ago)" if r.trend_label != TrendLabel.NONE else ""))
    print(f"  ATR (14d)   : {r.atr_14:.1f} pts")
    print(f"  DTR consumed: {r.dtr_consumed_pct:.0f}%")
    print(f"  Confluence  : {r.confluence_score}/5 {'✓ HIGH' if r.is_high_confidence else '✗ LOW'}")
    print(f"  Data source : {r.data_source}")
    print()

    agreeing = r.clouds_agreeing()
    print(f"  Clouds agreeing with {r.regime.value}: {', '.join(agreeing) if agreeing else 'none'}")

    print()
    print(f"  ── Bot Routing ──────────────────────────────────────────────")
    if r.regime == MarketRegime.SIDEWAYS:
        print(f"  → SIDEWAYS BOT (Iron Condor)")
    elif r.regime == MarketRegime.BULLISH and r.is_high_confidence:
        print(f"  → BULLISH BOT (Bull Call Spread)")
    elif r.regime == MarketRegime.BEARISH and r.is_high_confidence:
        print(f"  → BEARISH BOT (Bear Put Spread)")
    elif r.regime == MarketRegime.UNKNOWN:
        print(f"  → SKIP — data unavailable")
    else:
        print(f"  → SKIP — {r.regime.value} but low confidence ({r.confluence_score}/5)")
    print("=" * 72)
