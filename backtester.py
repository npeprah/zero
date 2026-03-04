"""
Backtesting module for SPX 0DTE strategies
Loads historical data and simulates trading across all three bots
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict
from trading_bot import TradingEngine, BotType, IndicatorValues, VIX1DData


class BacktestEngine:
    """Run backtests on historical data"""
    
    def __init__(self, engine: TradingEngine):
        self.engine = engine
        self.results = []
    
    def backtest_period(self, start_date: datetime, end_date: datetime,
                       data: pd.DataFrame) -> Dict:
        """
        Run backtest for a date range
        
        Expected data columns:
        - timestamp, open, high, low, close, volume
        - sma_20, vwap, vwap_slope, ema_5, ema_40, ema_signal
        - vix1d, vix1d_20day_avg, gex
        """
        
        trades_executed = 0
        wins = 0
        losses = 0
        total_pnl = 0.0
        max_drawdown = 0.0
        cumulative_pnl = 0.0
        
        for idx, row in data.iterrows():
            # Create indicators from row
            indicators = IndicatorValues(
                sma_20=row['sma_20'],
                vwap=row['vwap'],
                vwap_slope=row['vwap_slope'],
                ema_5=row['ema_5'],
                ema_40=row['ema_40'],
                ema_signal=row['ema_signal'],
                price_vs_sma=row.get('price_vs_sma', 'unknown')
            )
            
            vix1d_data = VIX1DData(
                vix1d=row['vix1d'],
                vix1d_20day_avg=row['vix1d_20day_avg'],
                expected_move_points=row.get('expected_move', 40),
                is_rich_premiums=row['vix1d'] > row['vix1d_20day_avg'],
                is_normal_vol=row['vix1d'] < 25
            )
            
            # Evaluate trade — pass the row's timestamp so time gate
            # uses the historical time, not datetime.now()
            ts = row.get('timestamp', idx)
            row_time = ts.replace(hour=11, minute=0) if hasattr(ts, 'replace') else datetime.now().replace(hour=11, minute=0)
            bot_type, explanation = self.engine.evaluate_trade(
                current_price=row['close'],
                indicators=indicators,
                vix1d_data=vix1d_data,
                gex=row.get('gex', 0.5),
                economic_events=[],
                current_time=row_time,
            )
            
            # Simulate trade
            if bot_type != BotType.NONE:
                setup = self.engine.create_trade_setup(bot_type, row['close'], vix1d_data)
                if setup:
                    trades_executed += 1
                    
                    # Simulate random outcome (50-65% win rate)
                    win_prob = 0.60 if bot_type != BotType.SIDEWAYS else 0.55
                    is_win = np.random.random() < win_prob
                    
                    if is_win:
                        pnl = setup.max_profit
                        wins += 1
                    else:
                        pnl = -setup.max_loss
                        losses += 1
                    
                    total_pnl += pnl
                    cumulative_pnl += pnl
                    
                    # Track drawdown
                    if cumulative_pnl < 0:
                        max_drawdown = min(max_drawdown, cumulative_pnl)
        
        win_rate = wins / trades_executed if trades_executed > 0 else 0
        
        return {
            'period': (start_date, end_date),
            'trades': trades_executed,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'max_drawdown': abs(max_drawdown),
            'avg_pnl_per_trade': total_pnl / trades_executed if trades_executed > 0 else 0,
        }


if __name__ == "__main__":
    engine = TradingEngine(account_size=100000)
    backtester = BacktestEngine(engine)
    
    # Create sample data — weekdays only, GEX positive, valid signals
    dates = pd.date_range('2025-01-01', periods=200, freq='B')  # 'B' = business days only
    n = len(dates)
    close_prices = 5500 + np.random.randn(n).cumsum()
    data = pd.DataFrame({
        'timestamp': dates,
        'open':   close_prices - np.abs(np.random.randn(n)),
        'high':   close_prices + np.abs(np.random.randn(n)) * 2,
        'low':    close_prices - np.abs(np.random.randn(n)) * 2,
        'close':  close_prices,
        'volume': 100000 + np.random.randint(0, 20000, n),
        'sma_20': close_prices - np.random.randn(n) * 3,
        'vwap':   close_prices + np.random.randn(n),
        'vwap_slope':  ['rising'] * 70 + ['falling'] * 70 + ['flat'] * (n - 140),
        'ema_5':  close_prices + np.random.randn(n) * 0.5,
        'ema_40': close_prices - np.random.randn(n) * 2,
        'ema_signal': ['bullish'] * 80 + ['bearish'] * 80 + ['intertwined'] * (n - 160),
        'price_vs_sma': ['above'] * 100 + ['below'] * 60 + ['near'] * (n - 160),
        'vix1d':         np.abs(12 + np.random.randn(n) * 2),   # always positive
        'vix1d_20day_avg': 13.0,
        'gex':           np.abs(np.random.randn(n)) + 0.1,       # always positive (gates pass)
    })
    
    results = backtester.backtest_period(
        start_date=dates[0],
        end_date=dates[-1],
        data=data
    )
    
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"Period: {results['period'][0].date()} to {results['period'][1].date()}")
    print(f"Trades Executed: {results['trades']}")
    print(f"Wins: {results['wins']} | Losses: {results['losses']}")
    print(f"Win Rate: {results['win_rate']:.1%}")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Avg P&L/Trade: ${results['avg_pnl_per_trade']:.2f}")
    print(f"Max Drawdown: ${results['max_drawdown']:.2f}")
    print("="*60)
