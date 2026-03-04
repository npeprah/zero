#!/usr/bin/env python3
"""
Simple test script to validate bot components
Run this before deploying bot to production
"""

import os
import json
from datetime import datetime
from tastytrade_bot import (
    BotConfig, TastytradeAuth, TastytradeData, GEXFilter,
    GreeksCalculator, StrikeSelector, OrderExecutor, SPX0DTEBot
)

def test_configuration():
    """Test configuration is valid"""
    print("=" * 60)
    print("TEST 1: Configuration")
    print("=" * 60)
    
    config = BotConfig()
    
    checks = {
        "Account Size": config.ACCOUNT_SIZE > 0,
        "Risk Per Trade": 0 < config.RISK_PER_TRADE < 0.05,
        "Max Loss Calculated": config.MAX_LOSS_PER_TRADE > 0,
        "Trading Hours Valid": config.TRADING_START < config.TRADING_END,
        "Target Delta Valid": 0 < config.TARGET_DELTA < 0.5,
        "Spread Width Valid": config.SPREAD_WIDTH > 0,
    }
    
    for check, result in checks.items():
        status = "✓" if result else "✗"
        print(f"{status} {check}")
    
    print(f"\nConfig Summary:")
    print(f"  Account Size: ${config.ACCOUNT_SIZE:,.0f}")
    print(f"  Risk Per Trade: {config.RISK_PER_TRADE*100:.1f}% = ${config.MAX_LOSS_PER_TRADE:,.0f}")
    print(f"  Target Delta: {config.TARGET_DELTA*100:.0f}")
    print(f"  Sandbox Mode: {config.SANDBOX_MODE}")
    
    return all(checks.values())


def test_greeks():
    """Test Greeks calculation"""
    print("\n" + "=" * 60)
    print("TEST 2: Greeks Calculation (Black-Scholes)")
    print("=" * 60)
    
    S = 5500  # SPX price
    K = 5520  # Strike (call)
    T = 6/252  # 1 day to expiration (6 hours)
    r = 0.05  # Risk-free rate
    sigma = 0.15  # Volatility (15%)
    
    delta = GreeksCalculator.calculate_delta(S, K, T, r, sigma, 'call')
    gamma = GreeksCalculator.calculate_gamma(S, K, T, r, sigma)
    theta = GreeksCalculator.calculate_theta(S, K, T, r, sigma, 'call')
    
    print(f"Input: S=${S}, K=${K}, T={T:.4f} years, sigma={sigma*100:.0f}%")
    print(f"\nOutput:")
    print(f"  Delta: {delta:.3f} (0.20 = 20 delta)")
    print(f"  Gamma: {gamma:.6f} (convexity)")
    print(f"  Theta (daily): ${theta*100:.2f} (time decay)")
    
    # Check if values are reasonable
    checks = {
        "Delta in range": 0 < delta < 1,
        "Gamma positive": gamma > 0,
        "Theta negative (decay)": theta < 0,
    }
    
    for check, result in checks.items():
        status = "✓" if result else "✗"
        print(f"{check}: {status}")
    
    return all(checks.values())


def test_strike_selection():
    """Test strike selection logic"""
    print("\n" + "=" * 60)
    print("TEST 3: Strike Selection")
    print("=" * 60)
    
    config = BotConfig()
    spx_price = 5500.00
    expiration = datetime.now().strftime('%Y-%m-%d')
    target_delta = 0.20
    
    strikes = StrikeSelector.select_strikes(spx_price, expiration, target_delta, config)
    
    if strikes:
        print(f"SPX Price: ${spx_price:,.2f}")
        print(f"Target Delta: {target_delta*100:.0f}")
        print(f"\nSelected Strikes:")
        print(f"  Call Sell: ${strikes['call_sell']}")
        print(f"  Call Buy:  ${strikes['call_buy']}")
        print(f"  Put Sell:  ${strikes['put_sell']}")
        print(f"  Put Buy:   ${strikes['put_buy']}")
        
        # Verify spreads
        call_width = strikes['call_buy'] - strikes['call_sell']
        put_width = strikes['put_sell'] - strikes['put_buy']
        
        print(f"\nSpread Widths:")
        print(f"  Call spread: ${call_width}")
        print(f"  Put spread:  ${put_width}")
        
        checks = {
            "Call spread width": call_width == config.SPREAD_WIDTH,
            "Put spread width": put_width == config.SPREAD_WIDTH,
            "Calls above SPX": strikes['call_sell'] > spx_price,
            "Puts below SPX": strikes['put_sell'] < spx_price,
        }
        
        for check, result in checks.items():
            status = "✓" if result else "✗"
            print(f"{check}: {status}")
        
        return all(checks.values())
    else:
        print("✗ Strike selection failed")
        return False


def test_gex_filter():
    """Test GEX filter"""
    print("\n" + "=" * 60)
    print("TEST 4: GEX Filter")
    print("=" * 60)
    
    print("Attempting to fetch GEX from SpotGamma...")
    gex = GEXFilter.get_gex()
    
    if gex is not None:
        print(f"✓ GEX retrieved: {gex:,.0f}")
        
        config = BotConfig()
        should_trade = GEXFilter.should_trade(config)
        
        print(f"  MIN_GEX_VALUE: {config.MIN_GEX_VALUE:,.0f}")
        print(f"  Should trade: {should_trade}")
        
        return True
    else:
        print("⚠ GEX unavailable (SpotGamma down?)")
        print("  This is OK - bot has fallback logic")
        return True  # Not a failure


def test_credentials():
    """Test if credentials are set"""
    print("\n" + "=" * 60)
    print("TEST 5: Credentials")
    print("=" * 60)
    
    email = os.getenv('TASTYTRADE_EMAIL')
    password = os.getenv('TASTYTRADE_PASSWORD')
    account_id = os.getenv('TASTYTRADE_ACCOUNT_ID')
    
    checks = {
        "TASTYTRADE_EMAIL set": email is not None,
        "TASTYTRADE_PASSWORD set": password is not None,
        "TASTYTRADE_ACCOUNT_ID set": account_id is not None,
    }
    
    for check, result in checks.items():
        status = "✓" if result else "✗"
        print(f"{check}: {status}")
    
    if not all(checks.values()):
        print("\n⚠ Credentials not set. Create .env file:")
        print("  cp .env.example .env")
        print("  nano .env  # Fill in your Tastytrade credentials")
    
    return all(checks.values())


def test_trade_logging():
    """Test trade logging system"""
    print("\n" + "=" * 60)
    print("TEST 6: Trade Logging")
    print("=" * 60)
    
    test_trade = {
        'timestamp': datetime.now().isoformat(),
        'spx_price': 5500.00,
        'call_sell': 5520,
        'call_buy': 5525,
        'put_sell': 5480,
        'put_buy': 5475,
        'contracts': 1,
        'order_id': 'TEST-ORDER-001',
        'status': 'test'
    }
    
    try:
        # Write test trade
        with open('test_trade.json', 'w') as f:
            json.dump(test_trade, f, indent=2)
        
        # Read it back
        with open('test_trade.json', 'r') as f:
            loaded = json.load(f)
        
        if loaded == test_trade:
            print("✓ Trade logging works")
            print(f"  Sample trade: {loaded['order_id']}")
            return True
        else:
            print("✗ Trade data mismatch")
            return False
    except Exception as e:
        print(f"✗ Trade logging failed: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists('test_trade.json'):
            os.remove('test_trade.json')


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("SPX 0DTE BOT - VALIDATION TESTS")
    print("=" * 60)
    
    tests = [
        ("Configuration", test_configuration),
        ("Greeks Calculation", test_greeks),
        ("Strike Selection", test_strike_selection),
        ("GEX Filter", test_gex_filter),
        ("Credentials", test_credentials),
        ("Trade Logging", test_trade_logging),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"\n✗ {test_name} failed with exception:")
            print(f"  {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! Bot is ready for deployment.")
    else:
        print("\n⚠ Some tests failed. Check configuration and credentials.")
        print("\nNext steps:")
        print("  1. Review test output above")
        print("  2. Fix any configuration issues")
        print("  3. Re-run this test: python test_bot.py")
        print("  4. When all tests pass, run: python tastytrade_bot.py")
    
    return passed == total


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
