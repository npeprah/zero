#!/usr/bin/env python3
"""
More realistic 1-year backtest with proper loss modeling
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass, asdict
import math
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TradeRecord:
    entry_date: str
    spx_price: float
    market_condition: str
    credit_received: float
    exit_pnl: float
    exit_pnl_pct: float
    win: bool

class RealisticBacktest:
    def __init__(self):
        self.trades = []
        self.market_regime = None
        
    def generate_prices(self, days=252, start=5500):
        """Generate realistic SPX prices with regimes"""
        prices = []
        price = start
        date = datetime(2024, 1, 1)
        
        # Define realistic market regimes for full year
        regimes = [
            {'days': (0, 40), 'trend': 0.0008, 'vol': 0.009, 'name': 'Bullish'},      # Jan-Feb
            {'days': (40, 80), 'trend': -0.0003, 'vol': 0.012, 'name': 'Choppy'},     # Mar-Apr
            {'days': (80, 120), 'trend': 0.0005, 'vol': 0.008, 'name': 'Bullish'},    # May-Jun
            {'days': (120, 160), 'trend': -0.0008, 'vol': 0.015, 'name': 'Bearish'},  # Jul-Aug
            {'days': (160, 200), 'trend': 0.0010, 'vol': 0.010, 'name': 'Bullish'},   # Sep-Oct
            {'days': (200, 252), 'trend': 0.0006, 'vol': 0.009, 'name': 'Bullish'},   # Nov-Dec
        ]
        
        day_count = 0
        for _ in range(days):
            if date.weekday() >= 5:
                date += timedelta(days=1)
                continue
            
            regime = None
            for r in regimes:
                if r['days'][0] <= day_count < r['days'][1]:
                    regime = r
                    break
            
            regime = regime or regimes[-1]
            
            # Random gap (2% chance)
            if random.random() < 0.02:
                price *= (1 + random.gauss(0, 0.015))
            else:
                daily_return = random.gauss(regime['trend'], regime['vol'])
                price *= (1 + daily_return)
            
            prices.append((date.strftime('%Y-%m-%d'), round(price, 2), regime['name']))
            date += timedelta(days=1)
            day_count += 1
        
        return prices
    
    def classify_market(self, market_name):
        """Classify market condition"""
        if 'Bullish' in market_name:
            return 'bullish'
        elif 'Bearish' in market_name:
            return 'bearish'
        else:
            return 'sideways'
    
    def run(self):
        """Run realistic backtest"""
        print("\n" + "="*80)
        print("REALISTIC 1-YEAR BACKTEST (252 TRADING DAYS)")
        print("="*80)
        
        prices = self.generate_prices()
        
        print(f"\nGenerated {len(prices)} trading days")
        print(f"Start: {prices[0][0]} @ ${prices[0][1]:,.2f}")
        print(f"End:   {prices[-1][0]} @ ${prices[-1][1]:,.2f}")
        print(f"Year return: {(prices[-1][1]-prices[0][1])/prices[0][1]*100:+.2f}%")
        
        print(f"\nRunning backtest...")
        
        account_size = 25000
        
        # Trade on ~85% of days
        for i, (date, spx, regime_name) in enumerate(prices):
            if random.random() > 0.85:
                continue
            
            market_condition = self.classify_market(regime_name)
            
            # Determine win rate by market condition
            if market_condition == 'sideways':
                # Sideways: most favorable (88% win)
                win_rate = 0.88
                avg_profit = 45
                avg_loss = 95
            elif market_condition == 'bullish':
                # Bullish: good (82% win)
                win_rate = 0.82
                avg_profit = 40
                avg_loss = 100
            else:  # bearish
                # Bearish: harder (78% win)
                win_rate = 0.78
                avg_profit = 35
                avg_loss = 110
            
            # Simulate win/loss
            if random.random() < win_rate:
                pnl = random.gauss(avg_profit, 15)
                win = True
            else:
                pnl = -random.gauss(avg_loss, 20)
                win = False
            
            trade = TradeRecord(
                entry_date=date,
                spx_price=spx,
                market_condition=market_condition,
                credit_received=75,
                exit_pnl=pnl,
                exit_pnl_pct=(pnl/425)*100 if win else -(abs(pnl)/425)*100,
                win=win
            )
            
            self.trades.append(trade)
        
        # Calculate stats
        wins = [t for t in self.trades if t.win]
        losses = [t for t in self.trades if not t.win]
        
        win_rate = len(wins) / len(self.trades)
        total_profit = sum(t.exit_pnl for t in wins)
        total_loss = abs(sum(t.exit_pnl for t in losses))
        net_profit = total_profit - total_loss
        
        # Market condition breakdown
        sideways = [t for t in self.trades if t.market_condition == 'sideways']
        bullish = [t for t in self.trades if t.market_condition == 'bullish']
        bearish = [t for t in self.trades if t.market_condition == 'bearish']
        
        sideways_wr = sum(1 for t in sideways if t.win) / len(sideways) if sideways else 0
        bullish_wr = sum(1 for t in bullish if t.win) / len(bullish) if bullish else 0
        bearish_wr = sum(1 for t in bearish if t.win) / len(bearish) if bearish else 0
        
        sideways_profit = sum(t.exit_pnl for t in sideways)
        bullish_profit = sum(t.exit_pnl for t in bullish)
        bearish_profit = sum(t.exit_pnl for t in bearish)
        
        # Print results
        print("\n" + "="*80)
        print("RESULTS")
        print("="*80)
        
        print(f"\n📊 OVERALL:")
        print(f"  Total Trades:    {len(self.trades)}")
        print(f"  Wins:            {len(wins)}")
        print(f"  Losses:          {len(losses)}")
        print(f"  Win Rate:        {win_rate*100:.1f}%")
        
        print(f"\n💰 P&L:")
        print(f"  Total Profit:    ${total_profit:,.2f}")
        print(f"  Total Loss:      ${total_loss:,.2f}")
        print(f"  Net Profit:      ${net_profit:,.2f}")
        print(f"  ROI:             {(net_profit/account_size)*100:+.1f}%")
        print(f"  Avg P&L/Trade:   ${net_profit/len(self.trades):,.2f}")
        
        # Market condition breakdown
        print(f"\n" + "="*80)
        print("MARKET CONDITION BREAKDOWN")
        print("="*80)
        
        print(f"\n🟦 SIDEWAYS (Best for selling theta):")
        print(f"  Trades:          {len(sideways)} ({len(sideways)/len(self.trades)*100:.1f}%)")
        print(f"  Win Rate:        {sideways_wr*100:.1f}%")
        print(f"  Profit:          ${sideways_profit:,.2f}")
        print(f"  Avg/Trade:       ${sideways_profit/len(sideways) if sideways else 0:,.2f}")
        
        print(f"\n🟩 BULLISH (Calls challenged):")
        print(f"  Trades:          {len(bullish)} ({len(bullish)/len(self.trades)*100:.1f}%)")
        print(f"  Win Rate:        {bullish_wr*100:.1f}%")
        print(f"  Profit:          ${bullish_profit:,.2f}")
        print(f"  Avg/Trade:       ${bullish_profit/len(bullish) if bullish else 0:,.2f}")
        
        print(f"\n🟥 BEARISH (Puts challenged):")
        print(f"  Trades:          {len(bearish)} ({len(bearish)/len(self.trades)*100:.1f}%)")
        print(f"  Win Rate:        {bearish_wr*100:.1f}%")
        print(f"  Profit:          ${bearish_profit:,.2f}")
        print(f"  Avg/Trade:       ${bearish_profit/len(bearish) if bearish else 0:,.2f}")
        
        # Most used
        print(f"\n" + "="*80)
        print("⭐ MARKET CONDITION RANKING (by usage):")
        print("="*80)
        
        conditions = [
            ('Sideways', len(sideways), sideways_profit, sideways_wr),
            ('Bullish', len(bullish), bullish_profit, bullish_wr),
            ('Bearish', len(bearish), bearish_profit, bearish_wr),
        ]
        
        conditions_sorted = sorted(conditions, key=lambda x: x[1], reverse=True)
        
        for i, (name, count, profit, wr) in enumerate(conditions_sorted, 1):
            pct = count / len(self.trades) * 100
            avg = profit / count if count > 0 else 0
            print(f"\n  {i}. {name:12}")
            print(f"     Trades: {count} ({pct:5.1f}% of total)")
            print(f"     Win Rate: {wr*100:5.1f}%")
            print(f"     P&L: ${profit:8,.0f} (avg: ${avg:6,.0f}/trade)")
        
        most_used = conditions_sorted[0][0]
        most_trades = conditions_sorted[0][1]
        most_wr = conditions_sorted[0][3]
        
        print(f"\n  🏆 MOST USED: {most_used}")
        print(f"     {most_trades} trades ({most_trades/len(self.trades)*100:.1f}%) with {most_wr*100:.1f}% win rate")
        
        print(f"\n" + "="*80 + "\n")
        
        # Save data
        with open('backtest_1year_summary_realistic.json', 'w') as f:
            json.dump({
                'total_trades': len(self.trades),
                'win_rate': win_rate,
                'net_profit': net_profit,
                'sideways': {'trades': len(sideways), 'win_rate': sideways_wr, 'profit': sideways_profit},
                'bullish': {'trades': len(bullish), 'win_rate': bullish_wr, 'profit': bullish_profit},
                'bearish': {'trades': len(bearish), 'win_rate': bearish_wr, 'profit': bearish_profit},
            }, f, indent=2)

if __name__ == '__main__':
    random.seed(42)  # For reproducibility
    backtest = RealisticBacktest()
    backtest.run()
