"""
SOVEREIGN-X MT5 GATEWAY DIAGNOSTIC TOOL
Standalone verification script for live MetaTrader 5 connection
No orders opened - diagnostics only
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════════════════════
# DEFENSIVE IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from config.settings import Settings
except ImportError as e:
    print(f"[FATAL] Failed to import Settings: {e}")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[FATAL] MetaTrader5 module not installed")
    print("        Install via: pip install MetaTrader5")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# MT5 CONNECTION DIAGNOSTIC
# ═══════════════════════════════════════════════════════════════════════════════

class MT5ConnectionDiagnostic:
    """Diagnostic utility for MT5 gateway verification"""
    
    def __init__(self):
        self.connected = False
        self.account_info = None
        self.error_code = None
        self.error_message = None
    
    def verify_connection(self) -> bool:
        """
        Attempt to connect to MT5 terminal and retrieve account information
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "="*70)
        print("SOVEREIGN-X MT5 GATEWAY DIAGNOSTIC TOOL")
        print("="*70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting MT5 connection verification...\n")
        
        try:
            # Initialize MT5 connection
            print("[INIT] Initializing MetaTrader5 terminal connection...")
            
            if not mt5.initialize(
                login=Settings.mt5.login,
                password=Settings.mt5.password,
                server=Settings.mt5.server,
                timeout=Settings.mt5.timeout
            ):
                self.error_code = mt5.last_error()
                self.error_message = f"MT5 initialization failed: {self.error_code}"
                print(f"[ERROR] {self.error_message}")
                return False
            
            print("[OK] MetaTrader5 terminal initialized")
            
            # Retrieve account information
            print("[FETCH] Retrieving account information...")
            
            account_info = mt5.account_info()
            if account_info is None:
                self.error_code = mt5.last_error()
                self.error_message = f"Failed to retrieve account info: {self.error_code}"
                print(f"[ERROR] {self.error_message}")
                mt5.shutdown()
                return False
            
            print("[OK] Account information retrieved successfully")
            
            # Store account info
            self.account_info = account_info
            self.connected = True
            
            return True
            
        except Exception as e:
            self.error_code = "EXCEPTION"
            self.error_message = str(e)
            print(f"[ERROR] Exception during connection: {self.error_message}")
            return False
        
        finally:
            # Always shutdown after connection check
            try:
                mt5.shutdown()
            except:
                pass
    
    def print_health_report(self):
        """Print formatted system health report"""
        if not self.connected or self.account_info is None:
            print("\n" + "="*70)
            print("CONNECTION FAILED - SYSTEM HEALTH REPORT")
            print("="*70)
            print(f"Connectivity Status: FAILED")
            print(f"Error Code: {self.error_code}")
            print(f"Error Message: {self.error_message}")
            print("="*70 + "\n")
            return False
        
        # Extract account data
        login = self.account_info.login
        balance = self.account_info.balance
        equity = self.account_info.equity
        margin = self.account_info.margin
        margin_free = self.account_info.margin_free
        margin_level = self.account_info.margin_level if self.account_info.margin > 0 else 0
        drawdown_pct = ((balance - equity) / balance * 100) if balance > 0 else 0
        server = Settings.mt5.server
        currency = self.account_info.currency
        company = self.account_info.company
        
        # Print health report
        print("\n" + "="*70)
        print("SYSTEM HEALTH REPORT - MT5 GATEWAY DIAGNOSTIC")
        print("="*70)
        
        print(f"\n[OK] CONNECTION STATUS: ACTIVE")
        print(f"    Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        print(f"\n[ACCOUNT INFO]")
        print(f"    Account Number: {login}")
        print(f"    Account Balance: ${balance:,.2f} {currency}")
        print(f"    Account Equity: ${equity:,.2f} {currency}")
        print(f"    Current Drawdown: {drawdown_pct:.2f}%")
        
        print(f"\n[MARGIN STATUS]")
        print(f"    Margin Used: ${margin:,.2f} {currency}")
        print(f"    Margin Available: ${margin_free:,.2f} {currency}")
        print(f"    Margin Level: {margin_level:.2f}%")
        
        print(f"\n[SERVER CONFIGURATION]")
        print(f"    Server Name: {server}")
        print(f"    Broker Company: {company}")
        print(f"    Account Currency: {currency}")
        
        print(f"\n[TRADE PERMISSIONS]")
        print(f"    Trades Allowed: {'YES' if self.account_info.trade_allowed else 'NO'}")
        print(f"    Expert Advisors Allowed: {'YES' if self.account_info.trade_expert else 'NO'}")
        print(f"    Hedging Allowed: {'YES' if getattr(self.account_info, 'hedge_allowed', False) else 'NO'}")
        
        print("\n" + "="*70)
        print("Connectivity Status: ACTIVE")
        print("="*70 + "\n")
        
        return True
    
    def get_exit_code(self) -> int:
        """Return appropriate exit code"""
        return 0 if self.connected else 1


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main diagnostic routine"""
    
    print(f"\n[CONFIG] Loading credentials from config.settings...")
    print(f"[CONFIG] MT5 Server: {Settings.mt5.server}")
    print(f"[CONFIG] MT5 Login: {Settings.mt5.login}")
    print(f"[CONFIG] Live Trading Mode: {'ENABLED' if Settings.mt5.enable_live_trading else 'DISABLED'}")
    
    # Initialize diagnostic
    diagnostic = MT5ConnectionDiagnostic()
    
    # Attempt connection
    print(f"\n[CONNECT] Attempting MetaTrader 5 connection...")
    connection_success = diagnostic.verify_connection()
    
    # Print report
    diagnostic.print_health_report()
    
    # Return appropriate exit code
    exit_code = diagnostic.get_exit_code()
    
    if connection_success:
        print("[SUCCESS] MT5 Gateway connection verified successfully!")
        print("[STATUS] System is READY for capital deployment")
    else:
        print("[FAILURE] MT5 Gateway connection failed!")
        print(f"[ERROR-CODE] {diagnostic.error_code}")
        print("[STATUS] DO NOT DEPLOY CAPITAL - Connection issues detected")
    
    return exit_code


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Diagnostic interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] Unexpected error during diagnostics: {e}")
        sys.exit(1)
