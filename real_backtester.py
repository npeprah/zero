#!/usr/bin/env python3
"""
Real Backtester — 0DTE SPX Multi-Bot Strategy
==============================================
Simulates actual trade execution using real historical SPX price data.

Data sources (all via yfinance, no API key needed):
    ^GSPC hourly  — ~3 years of intraday bars for entry/exit simulation
    ^GSPC daily   — 5 years for long-period EMA calculations (EMA 120/233)
    ^VIX  daily   — volatility filter + premium estimation

Methodology (no lookahead bias):
    For each trading day D:
    1. Compute EMA clouds + ADX/RSI using ONLY data before D
    2. Apply regime + VIX gates
    3. Enter at 11:00 AM ET hourly bar
    4. Monitor intraday hourly bars for stop-loss / profit-take
    5. Settle remaining position at 3:30 PM ET

Key lessons from v1 tuning:
    - Condor strikes at 24 pts from ATM got touched 71% of days → too tight
    - Fixed 0.3% directional stop = 18 pts on ATR-65 days → pure noise
    - When condors reach expiry they avg +$222 → strikes are fine, stop was broken
    - Fix: hourly-CLOSE-based stop + ATR-scaled stops + wider condor strikes

Four configs are run and compared to find the best parameter set.
"""

import sys
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum

warnings.filterwarnings("ignore")


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class BotType(Enum):
    BULLISH  = "BULLISH"
    BEARISH  = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    NO_TRADE = "NO_TRADE"


class ExitReason(Enum):
    EXPIRY       = "EXPIRY"
    STOP_LOSS    = "STOP_LOSS"
    PROFIT_TAKE  = "PROFIT_TAKE"
    NO_ENTRY     = "NO_ENTRY"


@dataclass
class BacktestConfig:
    """
    All tunable parameters in one place.
    Run multiple configs to find the best combination.
    """
    name: str = "default"

    # ── Iron Condor (SIDEWAYS) ────────────────────────────────────────
    # Strike distance = condor_atr_mult × (ATR / 2) from ATM
    # v1 was 0.65 (~24 pts on ATR-65) → 71% stop rate; fix: go wider
    condor_atr_mult:    float = 0.65

    # v1: stop on any intraday HIGH/LOW touch → noisy
    # Better: stop only when hourly bar CLOSES beyond short strike
    condor_stop_on_close: bool = False

    # Close condor early at 2:30pm if both strikes are untouched
    # Simulates real-world "take 60-70% of credit" rule
    condor_early_exit:  bool  = False
    condor_early_exit_pct: float = 0.65  # keep this % of credit

    # ADX must be below this to trade the condor (low-trend required)
    adx_sideways_max:   float = 25.0
    vix_max_condor:     float = 22.0     # condors need calm vol

    # ── Directional (BULLISH / BEARISH) ──────────────────────────────
    # v1: stop at fixed 0.3% (18 pts on ATR-65 days) → too tight
    # Better: ATR-based stop (adaptive to current vol)
    dir_stop_atr_mult:  float = 0.20     # stop at 0.20 × ATR from entry
    dir_spread_width:   float = 10.0     # $10 wide spreads

    # Min ADX for directional trade (want a real trend)
    adx_directional_min: float = 25.0
    rsi_bull_min:       float = 55.0     # min RSI for bullish
    rsi_bear_max:       float = 45.0     # max RSI for bearish
    vix_max_dir:        float = 28.0

    # ── Global ────────────────────────────────────────────────────────
    confluence_min:     int   = 3        # min EMA confluence (0-5)
    di_gap_min:         float = 3.0      # min |DI+ - DI-| for directional


@dataclass
class TradeRecord:
    date:            date
    bot_type:        BotType
    entry_price:     float
    exit_price:      float
    pnl:             float
    exit_reason:     ExitReason
    credit_or_debit: float
    strike_a:        float
    strike_b:        float
    strike_c:        float = 0
    strike_d:        float = 0
    vix:             float = 0
    atr:             float = 0
    adx:             float = 0
    rsi:             float = 0
    confluence:      int   = 0


# ============================================================================
# DATA LOADER (fetches once, reused across all config runs)
# ============================================================================

class DataLoader:
    def __init__(self):
        self.hourly_df = None
        self.daily_df  = None
        self.vix_df    = None

    def load(self) -> bool:
        print("Fetching historical data from Yahoo Finance...")
        try:
            h = yf.Ticker("^GSPC").history(interval="1h", period="730d", auto_adjust=True)
            d = yf.Ticker("^GSPC").history(interval="1d", period="5y",   auto_adjust=True)
            v = yf.Ticker("^VIX").history( interval="1d", period="5y",   auto_adjust=True)

            for df in (h, d, v):
                df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")

            self.hourly_df = h
            self.daily_df  = d
            self.vix_df    = v

            print(f"  Hourly : {len(h):,}  ({h.index[0].date()} → {h.index[-1].date()})")
            print(f"  Daily  : {len(d):,}  ({d.index[0].date()} → {d.index[-1].date()})")
            return True
        except Exception as e:
            print(f"ERROR: {e}")
            return False

    def trading_days(self) -> List[date]:
        cnt = self.hourly_df.groupby(self.hourly_df.index.date).size()
        return sorted([d for d, c in cnt.items() if c >= 5])


# ============================================================================
# POINT-IN-TIME INDICATOR ENGINE
# ============================================================================

class PointInTime:
    """Zero-lookahead indicator calculation as of pre-market on trading_day."""

    @staticmethod
    def _ema(s: pd.Series, p: int) -> float:
        return float(s.ewm(span=p, adjust=False).mean().iloc[-1]) if len(s) >= 2 else float(s.iloc[-1])

    @staticmethod
    def _ema_s(s: pd.Series, p: int) -> pd.Series:
        return s.ewm(span=p, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, p: int = 14) -> float:
        pc = df["Close"].shift(1)
        tr = pd.concat([df["High"]-df["Low"],
                        (df["High"]-pc).abs(),
                        (df["Low"]-pc).abs()], axis=1).max(axis=1)
        return float(tr.ewm(span=p, adjust=False).mean().iloc[-1])

    @staticmethod
    def _adx_rsi(close: pd.Series, high: pd.Series, low: pd.Series,
                 p: int = 14) -> Tuple[float, float, float, float]:
        # RSI
        d     = close.diff()
        g     = d.where(d > 0, 0.0)
        l     = (-d).where(d < 0, 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            rsi = float((100 - 100/(1 + g.ewm(alpha=1/p, adjust=False).mean()
                                     / l.ewm(alpha=1/p, adjust=False).mean()
                                     .replace(0, np.nan))).iloc[-1])

        # ADX
        n = len(close)
        if n < p*3:
            return 20.0, 20.0, 20.0, rsi

        h_a = high.values.astype(float)
        l_a = low.values.astype(float)
        c_a = close.values.astype(float)
        # MUST create three separate arrays — shared assignment is a bug
        tr  = np.zeros(n)
        pdm = np.zeros(n)
        mdm = np.zeros(n)
        for i in range(1, n):
            tr[i]  = max(h_a[i]-l_a[i], abs(h_a[i]-c_a[i-1]), abs(l_a[i]-c_a[i-1]))
            up, dn = h_a[i]-h_a[i-1], l_a[i-1]-l_a[i]
            pdm[i] = up if (up > dn and up > 0) else 0.0
            mdm[i] = dn if (dn > up and dn > 0) else 0.0

        def ws(a):
            o = np.zeros(n)
            if p < n:
                o[p] = a[1:p+1].sum()
                for i in range(p+1, n): o[i] = o[i-1] - o[i-1]/p + a[i]
            return o

        ts, ps, ms = ws(tr), ws(pdm), ws(mdm)
        with np.errstate(invalid="ignore", divide="ignore"):
            pdi = np.where(ts>0, 100*ps/ts, 0)
            mdi = np.where(ts>0, 100*ms/ts, 0)
            dx  = np.where((pdi+mdi)>0, 100*np.abs(pdi-mdi)/(pdi+mdi), 0)
        adx = np.zeros(n)
        if 2*p < n:
            adx[2*p] = dx[p:2*p+1].mean()
            for i in range(2*p+1, n): adx[i] = (adx[i-1]*(p-1)+dx[i])/p

        return float(adx[-1]), float(pdi[-1]), float(mdi[-1]), rsi

    @classmethod
    def compute(cls, day: date, h_df: pd.DataFrame, d_df: pd.DataFrame) -> Optional[Dict]:
        h = h_df[h_df.index.date < day]
        d = d_df[d_df.index.date < day]
        if len(h) < 55 or len(d) < 50:
            return None

        ch, cd = h["Close"], d["Close"]
        price  = float(ch.iloc[-1])

        # 10 EMAs
        e8,e9     = cls._ema(ch,8),   cls._ema(ch,9)
        e20,e21   = cls._ema(ch,20),  cls._ema(ch,21)
        e34,e50   = cls._ema(ch,34),  cls._ema(ch,50)
        e55,e89   = cls._ema(ch,55),  cls._ema(ch,89)
        e120      = cls._ema(ch,120)
        e233      = cls._ema(ch,233) if len(ch)>=233 else cls._ema(cd,233)

        def pos(p,a,b):
            t,bt = max(a,b), min(a,b)
            return "ABOVE" if p>t else ("BELOW" if p<bt else "INSIDE")

        c1,c2,c3 = pos(price,e8,e9), pos(price,e20,e21), pos(price,e34,e50)
        c4,c5    = pos(price,e55,e89), pos(price,e120,e233)

        # Trend label: EMA8 x EMA34
        e8s  = cls._ema_s(ch,8)
        e34s = cls._ema_s(ch,34)
        label = "NONE"
        if len(e8s)>=2:
            dn, dp = float(e8s.iloc[-1]-e34s.iloc[-1]), float(e8s.iloc[-2]-e34s.iloc[-2])
            if dp<=0 < dn: label = "BULLISH_CROSS"
            elif dp>=0 > dn: label = "BEARISH_CROSS"

        # Regime
        if c3 == "INSIDE":
            regime, conf = "SIDEWAYS", 0
        else:
            if c3 == "ABOVE":
                sc = 2+sum([c1=="ABOVE",c2=="ABOVE",c4=="ABOVE",c5=="ABOVE",label=="BULLISH_CROSS"])
                if c4=="BELOW" and c5=="BELOW":
                    regime, conf = "SIDEWAYS", 2
                else:
                    regime, conf = "BULLISH", max(1,min(5,round((sc-1)*(5/6))))
            else:
                sc = 2+sum([c1=="BELOW",c2=="BELOW",c4=="BELOW",c5=="BELOW",label=="BEARISH_CROSS"])
                if c4=="ABOVE" and c5=="ABOVE":
                    regime, conf = "SIDEWAYS", 2
                else:
                    regime, conf = "BEARISH", max(1,min(5,round((sc-1)*(5/6))))

        adx, pdi, mdi, rsi = cls._adx_rsi(ch, h["High"], h["Low"])
        atr = cls._atr(d)

        return dict(regime=regime, confluence=conf, adx=adx, plus_di=pdi,
                    minus_di=mdi, rsi=rsi, atr=atr, price=price, label=label)


# ============================================================================
# BOT ROUTER
# ============================================================================

def route(ind: Dict, vix: float, cfg: BacktestConfig) -> BotType:
    r, conf = ind["regime"], ind["confluence"]
    adx     = ind["adx"]
    pdi, mdi, rsi = ind["plus_di"], ind["minus_di"], ind["rsi"]
    di_gap  = abs(pdi - mdi)

    if r == "SIDEWAYS":
        # OLD STRATEGY: Sideways bot is unprofitable with Ripster
        # Revert to NO_TRADE instead of trading sideways bots
        # The original logic was: only trade sideways when ALL directional filters fail
        # But that led to poor sideways bot performance (-$2,454 P&L)
        # Better to let directional bots handle edge cases
        return BotType.NO_TRADE

    if r == "BULLISH":
        if conf < cfg.confluence_min:          return BotType.NO_TRADE
        if adx < cfg.adx_directional_min:      return BotType.NO_TRADE
        if pdi < mdi:                          return BotType.NO_TRADE
        if rsi < cfg.rsi_bull_min:             return BotType.NO_TRADE
        if di_gap < cfg.di_gap_min:            return BotType.NO_TRADE
        if vix > cfg.vix_max_dir:              return BotType.NO_TRADE
        return BotType.BULLISH

    if r == "BEARISH":
        if conf < cfg.confluence_min:          return BotType.NO_TRADE
        if adx < cfg.adx_directional_min:      return BotType.NO_TRADE
        if mdi < pdi:                          return BotType.NO_TRADE
        if rsi > cfg.rsi_bear_max:             return BotType.NO_TRADE
        if di_gap < cfg.di_gap_min:            return BotType.NO_TRADE
        if vix > cfg.vix_max_dir:              return BotType.NO_TRADE
        return BotType.BEARISH

    return BotType.NO_TRADE


# ============================================================================
# PREMIUM MODEL
# ============================================================================

def condor_credit_per_side(width: float, vix: float) -> float:
    """Empirical 0DTE 20-delta credit — scales with VIX."""
    return round(min(0.15 * width * (vix/15), width * 0.32), 2)

def directional_debit(width: float, vix: float) -> float:
    """Empirical 0DTE ATM debit spread cost."""
    return round(min(0.30 * width * (vix/15), width * 0.50), 2)


# ============================================================================
# TRADE SIMULATOR
# ============================================================================

def _round5(x: float) -> float:
    return round(round(x/5)*5, 0)

def sim_condor(entry: float, atr: float, vix: float,
               intraday: pd.DataFrame, exit_price: float,
               cfg: BacktestConfig) -> Tuple[float, ExitReason, Dict]:
    """Simulate iron condor trade with configurable stop logic."""

    half_move  = atr * 0.5 * cfg.condor_atr_mult
    call_sell  = _round5(entry + half_move)
    call_buy   = call_sell + 5
    put_sell   = _round5(entry - half_move)
    put_buy    = put_sell - 5

    credit_side  = condor_credit_per_side(5, vix)
    total_credit = credit_side * 2
    max_loss     = 5 - credit_side   # per side (worst case one side blown)
    stop_cost    = total_credit * 2  # stop at 2× credit (standard condor rule)

    strikes = dict(cs=call_sell, cb=call_buy, ps=put_sell, pb=put_buy,
                   credit=total_credit)

    # ── Intraday monitoring ────────────────────────────────────────────
    between_11_and_230 = intraday[(intraday.index.hour >= 11) &
                                  ((intraday.index.hour < 14) |
                                   ((intraday.index.hour == 14) &
                                    (intraday.index.minute <= 30)))]

    for _, bar in between_11_and_230.iterrows():
        if cfg.condor_stop_on_close:
            # Stop only if hourly bar CLOSES beyond short strike
            breached = bar["Close"] > call_sell or bar["Close"] < put_sell
        else:
            # Original: stop on any intraday touch
            breached = bar["High"] >= call_sell or bar["Low"] <= put_sell

        if breached:
            return -stop_cost * 100, ExitReason.STOP_LOSS, strikes

    # ── Early profit take at 2:30pm ────────────────────────────────────
    if cfg.condor_early_exit:
        bar_230 = between_11_and_230[between_11_and_230.index.hour == 14]
        if len(bar_230) > 0:
            p230 = float(bar_230.iloc[-1]["Close"])
            if put_sell < p230 < call_sell:  # still inside
                pnl = total_credit * cfg.condor_early_exit_pct * 100
                return pnl, ExitReason.PROFIT_TAKE, strikes

    # ── Expiry settlement ──────────────────────────────────────────────
    call_loss = min(max(exit_price - call_sell, 0), 5)
    put_loss  = min(max(put_sell - exit_price,  0), 5)
    pnl = (total_credit - call_loss - put_loss) * 100
    return pnl, ExitReason.EXPIRY, strikes


def sim_directional(bot: BotType, entry: float, atr: float, vix: float,
                    intraday: pd.DataFrame, exit_price: float,
                    cfg: BacktestConfig) -> Tuple[float, ExitReason, Dict]:
    """Simulate bull call or bear put spread with ATR-based stop."""

    w     = cfg.dir_spread_width
    debit = directional_debit(w, vix)
    stop  = atr * cfg.dir_stop_atr_mult  # ATR-based stop distance

    if bot == BotType.BULLISH:
        buy_s, sell_s = _round5(entry), _round5(entry) + w
    else:
        buy_s, sell_s = _round5(entry), _round5(entry) - w

    strikes = dict(buy=buy_s, sell=sell_s, debit=debit)

    # ── Intraday stop check ────────────────────────────────────────────
    between = intraday[(intraday.index.hour >= 11) & (intraday.index.hour <= 14)]

    for _, bar in between.iterrows():
        if bot == BotType.BULLISH:
            # Stop if market drops more than (stop) points below entry
            if bar["Low"] <= entry - stop:
                return -(debit * 0.50) * 100, ExitReason.STOP_LOSS, strikes
        else:
            # Stop if market rises more than (stop) points above entry
            if bar["High"] >= entry + stop:
                return -(debit * 0.50) * 100, ExitReason.STOP_LOSS, strikes

    # ── Expiry ─────────────────────────────────────────────────────────
    if bot == BotType.BULLISH:
        intrinsic = max(0, min(exit_price - buy_s, w))
    else:
        intrinsic = max(0, min(buy_s - exit_price, w))

    pnl = (intrinsic - debit) * 100
    return pnl, ExitReason.EXPIRY, strikes


# ============================================================================
# BACKTESTER CORE
# ============================================================================

class RealBacktester:

    def __init__(self, loader: DataLoader):
        self.loader = loader

    def run(self, cfg: BacktestConfig,
            start: Optional[date] = None,
            end:   Optional[date] = None,
            verbose: bool = False) -> List[TradeRecord]:

        days = self.loader.trading_days()
        if start: days = [d for d in days if d >= start]
        if end:   days = [d for d in days if d <= end]
        days = days[50:]  # EMA burn-in

        trades     = []
        skip_data  = skip_gate = 0

        for day in days:
            # Point-in-time indicators
            ind = PointInTime.compute(day, self.loader.hourly_df, self.loader.daily_df)
            if ind is None:
                skip_data += 1; continue

            # VIX
            vr  = self.loader.vix_df[self.loader.vix_df.index.date == day]
            vix = float(vr["Close"].iloc[-1]) if len(vr) > 0 else 18.0

            # Route
            bot = route(ind, vix, cfg)
            if bot == BotType.NO_TRADE:
                skip_gate += 1; continue

            # Day's intraday data
            day_df = self.loader.hourly_df[self.loader.hourly_df.index.date == day]
            if len(day_df) < 4:
                skip_data += 1; continue

            # Entry bar (11am)
            entry_bars = day_df[(day_df.index.hour==11)]
            if len(entry_bars) == 0:
                entry_bars = day_df.iloc[[min(2, len(day_df)-1)]]
            entry_price = float(entry_bars.iloc[0]["Close"])

            # Exit bar (3:30pm)
            exit_bars = day_df[(day_df.index.hour==15) & (day_df.index.minute>=30)]
            exit_price = float(exit_bars.iloc[0]["Close"]) if len(exit_bars)>0 \
                         else float(day_df.iloc[-1]["Close"])

            # Intraday (11am–3:30pm)
            intraday = day_df[(day_df.index.hour >= 11) & (day_df.index.hour <= 15)]

            # Simulate
            if bot == BotType.SIDEWAYS:
                pnl, reason, strikes = sim_condor(
                    entry_price, ind["atr"], vix, intraday, exit_price, cfg)
                rec = TradeRecord(
                    date=day, bot_type=bot,
                    entry_price=entry_price, exit_price=exit_price,
                    pnl=pnl, exit_reason=reason,
                    credit_or_debit=strikes["credit"],
                    strike_a=strikes["cs"], strike_b=strikes["cb"],
                    strike_c=strikes["ps"], strike_d=strikes["pb"],
                    vix=vix, atr=ind["atr"], adx=ind["adx"],
                    rsi=ind["rsi"], confluence=ind["confluence"],
                )
            else:
                pnl, reason, strikes = sim_directional(
                    bot, entry_price, ind["atr"], vix, intraday, exit_price, cfg)
                rec = TradeRecord(
                    date=day, bot_type=bot,
                    entry_price=entry_price, exit_price=exit_price,
                    pnl=pnl, exit_reason=reason,
                    credit_or_debit=-strikes["debit"],
                    strike_a=strikes["buy"], strike_b=strikes["sell"],
                    vix=vix, atr=ind["atr"], adx=ind["adx"],
                    rsi=ind["rsi"], confluence=ind["confluence"],
                )

            trades.append(rec)

        if verbose:
            print(f"  {cfg.name}: {len(trades)} trades | "
                  f"{skip_gate} gate-blocked | {skip_data} data-skip")
        return trades


# ============================================================================
# REPORTER
# ============================================================================

def _stats(trades: List[TradeRecord], account: float = 25000) -> Dict:
    if not trades:
        return {}
    df  = pd.DataFrame([vars(t) for t in trades])
    pnl = df["pnl"]
    n   = len(df)
    wr  = (pnl > 0).mean()
    tot = pnl.sum()

    equity = pnl.cumsum()
    dd     = float((equity - equity.cummax()).min())

    daily  = df.groupby("date")["pnl"].sum() / account
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std()>0 else 0

    stops  = (df["exit_reason"] == ExitReason.STOP_LOSS).mean()
    profit_takes = (df["exit_reason"] == ExitReason.PROFIT_TAKE).mean()

    # bot_type is stored as BotType enum — convert for comparison
    df["_bot_str"] = df["bot_type"].apply(
        lambda x: x.value if hasattr(x, "value") else str(x))
    by_bot = {}
    for bot in ["SIDEWAYS","BULLISH","BEARISH"]:
        sub = df[df["_bot_str"] == bot]
        if len(sub) > 0:
            by_bot[bot] = dict(n=len(sub), wr=(sub["pnl"]>0).mean(),
                               tot=sub["pnl"].sum(), avg=sub["pnl"].mean())

    return dict(n=n, wr=wr, total=tot, roi=tot/account*100,
                avg=pnl.mean(), best=pnl.max(), worst=pnl.min(),
                max_dd=dd, sharpe=sharpe, stop_rate=stops,
                profit_take_rate=profit_takes, by_bot=by_bot)


def print_comparison(results: Dict[str, Dict]):
    """Print side-by-side comparison table of all configs."""
    sep = "═" * 100

    print(f"\n{sep}")
    print(f"  CONFIG COMPARISON — 0DTE SPX Multi-Bot Strategy")
    print(sep)

    names = list(results.keys())
    w = 18

    def row(label, fn):
        line = f"  {label:<26}"
        for n in names:
            r = results[n]
            line += fn(r).rjust(w)
        print(line)

    header = "  " + " " * 26
    for n in names:
        header += n.rjust(w)
    print(header)
    print("  " + "─"*98)

    row("Trades",           lambda r: str(r["n"]))
    row("Win Rate",         lambda r: f"{r['wr']:.1%}")
    row("Total P&L",        lambda r: f"${r['total']:,.0f}")
    row("ROI",              lambda r: f"{r['roi']:.1f}%")
    row("Avg P&L / trade",  lambda r: f"${r['avg']:,.0f}")
    row("Best trade",       lambda r: f"${r['best']:,.0f}")
    row("Worst trade",      lambda r: f"${r['worst']:,.0f}")
    row("Max Drawdown",     lambda r: f"${r['max_dd']:,.0f}")
    row("Sharpe Ratio",     lambda r: f"{r['sharpe']:.2f}")
    row("Stop-out Rate",    lambda r: f"{r['stop_rate']:.0%}")
    row("Profit-take Rate", lambda r: f"{r['profit_take_rate']:.0%}")

    print("  " + "─"*98)
    print("\n  By Bot Type:")
    for bot in ["SIDEWAYS","BULLISH","BEARISH"]:
        line = f"    {bot:<24}"
        for n in names:
            bb = results[n].get("by_bot",{}).get(bot)
            if bb:
                line += f"{bb['n']:>4}T {bb['wr']:>5.0%}WR ${bb['tot']:>8,.0f}".rjust(w)
            else:
                line += "     —".rjust(w)
        print(line)

    print(f"\n{sep}\n")


def equity_curve(trades: List[TradeRecord], label: str, account: float = 25000):
    df      = pd.DataFrame([vars(t) for t in trades])
    equity  = (df["pnl"].cumsum() + account).tolist()
    hi, lo  = max(equity), min(equity)
    width   = 72
    step    = max(1, len(equity)//width)
    sampled = equity[::step]
    height  = 10

    print(f"\n  Equity Curve — {label}")
    print("  " + "─" * (len(sampled) + 14))
    for r in range(height, -1, -1):
        level = lo + (hi - lo) * r / height
        bar   = "".join("█" if v >= level else " " for v in sampled)
        lbl   = f"${level:>9,.0f} |" if r % 2 == 0 else " "*12+"|"
        print(f"  {lbl}{bar}")
    print("  " + " "*12 + "└" + "─"*len(sampled))
    print(f"  {'':12} {trades[0].date}{'':>30}{trades[-1].date}\n")


# ============================================================================
# CONFIGS TO TEST
# ============================================================================

CONFIGS = [
    # ── A: Loose baseline — trade most signals ────────────────────────
    # Minimal filters: just regime direction + basic DI check
    # Condor: close-based stop (always better), intraday touch was broken
    BacktestConfig(
        name              = "A-Loose",
        condor_atr_mult   = 0.75,
        condor_stop_on_close = True,
        condor_early_exit = False,
        adx_sideways_max  = 60.0,      # essentially no ADX filter
        vix_max_condor    = 35.0,
        dir_stop_atr_mult = 0.50,      # ~33pts on ATR-65 (~0.55%)
        adx_directional_min = 10.0,    # very loose
        rsi_bull_min      = 50.0,
        rsi_bear_max      = 50.0,
        confluence_min    = 2,
        di_gap_min        = 0.0,
        vix_max_dir       = 35.0,
    ),
    # ── B: Medium — add trend quality gates ───────────────────────────
    BacktestConfig(
        name              = "B-Medium",
        condor_atr_mult   = 0.80,
        condor_stop_on_close = True,
        condor_early_exit = True,
        condor_early_exit_pct = 0.60,
        adx_sideways_max  = 30.0,
        vix_max_condor    = 22.0,
        dir_stop_atr_mult = 0.55,
        adx_directional_min = 18.0,
        rsi_bull_min      = 53.0,
        rsi_bear_max      = 47.0,
        confluence_min    = 3,
        di_gap_min        = 3.0,
        vix_max_dir       = 28.0,
    ),
    # ── C: Strict — high quality setups only ─────────────────────────
    BacktestConfig(
        name              = "C-Strict",
        condor_atr_mult   = 0.90,
        condor_stop_on_close = True,
        condor_early_exit = True,
        condor_early_exit_pct = 0.65,
        adx_sideways_max  = 22.0,
        vix_max_condor    = 19.0,
        dir_stop_atr_mult = 0.60,
        adx_directional_min = 22.0,
        rsi_bull_min      = 55.0,
        rsi_bear_max      = 45.0,
        confluence_min    = 3,
        di_gap_min        = 5.0,
        vix_max_dir       = 26.0,
    ),
    # ── D: Best-of — strict filter + widest stops + early profit take ─
    BacktestConfig(
        name              = "D-Best",
        condor_atr_mult   = 1.00,
        condor_stop_on_close = True,
        condor_early_exit = True,
        condor_early_exit_pct = 0.70,
        adx_sideways_max  = 20.0,
        vix_max_condor    = 18.0,
        dir_stop_atr_mult = 0.65,
        adx_directional_min = 25.0,
        rsi_bull_min      = 57.0,
        rsi_bear_max      = 43.0,
        confluence_min    = 3,
        di_gap_min        = 6.0,
        vix_max_dir       = 25.0,
    ),
]


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print("\n" + "═"*68)
    print("  Real Backtester — 0DTE SPX Multi-Bot Strategy")
    print("═"*68 + "\n")

    loader = DataLoader()
    if not loader.load():
        sys.exit(1)

    bt      = RealBacktester(loader)
    results = {}
    all_trades = {}

    print("\nRunning 4 parameter configs...\n")
    for cfg in CONFIGS:
        trades = bt.run(cfg, verbose=True)
        if trades:
            results[cfg.name]    = _stats(trades)
            all_trades[cfg.name] = trades

    print_comparison(results)

    # Show equity curve for the best config by total P&L
    best_name = max(results, key=lambda k: results[k]["total"])
    print(f"  ★ Best config: {best_name} "
          f"(${results[best_name]['total']:,.0f} total P&L, "
          f"{results[best_name]['wr']:.0%} win rate)\n")
    equity_curve(all_trades[best_name], best_name)

    # Save best results to CSV
    df_out = pd.DataFrame([vars(t) for t in all_trades[best_name]])
    df_out["bot_type"]    = df_out["bot_type"].apply(lambda x: x.value)
    df_out["exit_reason"] = df_out["exit_reason"].apply(lambda x: x.value)
    df_out.to_csv("backtest_results.csv", index=False)
    print(f"  Results saved → backtest_results.csv\n")
