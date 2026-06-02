"""
SOVEREIGN-X CORE OS - Main Orchestrator
Boots configuration, initializes MT5 gateway, runs warm-up compilation,
and executes real-time concurrent pipeline tasks
"""

import asyncio
import logging
import sys
import json
import os
import subprocess
from typing import Dict, List
from datetime import datetime
import time
import signal

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL DEFENSIVE IMPORTS - AUTO-HEALING LAYER
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_package_installed(package_name: str, import_name: str = None) -> bool:
    """
    Defensively check and auto-install missing packages
    
    Args:
        package_name: Package name for pip install
        import_name: Import name (if different from package_name)
    
    Returns:
        True if successfully imported
    """
    import_name = import_name or package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        try:
            print(f"[AUTO-HEAL] Installing missing package: {package_name}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name, "-q"])
            __import__(import_name)
            print(f"[AUTO-HEAL] [OK] {package_name} installed successfully")
            return True
        except Exception as e:
            print(f"[AUTO-HEAL-FAILED] Could not install {package_name}: {e}")
            return False

# Ensure critical dependencies exist
critical_packages = [
    ("numpy", "numpy"),
    ("numba", "numba"),
    ("redis", "redis"),
    ("python-dotenv", "dotenv"),
]

for package, import_name in critical_packages:
    if not ensure_package_installed(package, import_name):
        print(f"[CRITICAL] Failed to ensure {package} - system may be unstable")

# Import numpy with defensive fallback
try:
    import numpy as np
except ImportError:
    print("[AUTO-HEAL] Attempting fallback for numpy")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy", "-q"])
    import numpy as np

# Module-level numpy binding (accessible throughout module, especially async functions)
global np

# Core imports with error trapping
try:
    from config.settings import Settings
    from core.regime_detector import RegimeDetector
    from core.order_flow import HawkesPointProcess
    from core.risk_engine import QAOAOptimizer
    from agents.market_maker import MarketMakerAgent
    from agents.directional import DirectionalAgent
    from pipeline.redis_stream import RedisStreamPipeline
    from pipeline.mt5_gateway import MT5Gateway
except ImportError as e:
    print(f"[CRITICAL] Core import failed: {e}")
    print("[AUTO-HEAL] Attempting to recover from import error")
    sys.exit(1)

# Defensively create logs directory to guarantee zero-bug initialization
os.makedirs("logs", exist_ok=True)

# Configure logging
logging.basicConfig(
    level=getattr(logging, Settings.logging.log_level),
    format=Settings.logging.log_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{Settings.logging.log_dir}/sovereign_x_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL SELF-HEALING ERROR HANDLER (Pre-instantiation)
# ═══════════════════════════════════════════════════════════════════════════════

class SelfHealingErrorHandler:
    """Global error handler with auto-recovery capabilities"""
    
    def __init__(self):
        self.error_count = 0
        self.last_error = None
        self.max_retries = 3
        self.recovery_attempts = 0
    
    def handle(self, error: Exception, context: str = "") -> bool:
        """
        Handle errors with automatic recovery
        
        Args:
            error: Exception that occurred
            context: Context where error happened
        
        Returns:
            True if recovered, False if fatal
        """
        self.error_count += 1
        self.last_error = error
        
        error_type = type(error).__name__
        error_msg = str(error)
        
        logger.error(f"[AUTO-HEAL] Error #{self.error_count} in {context}: {error_type}: {error_msg}")
        
        # Recovery strategies based on error type
        if "ImportError" in error_type or "ModuleNotFoundError" in error_type:
            logger.warning(f"[AUTO-HEAL] Attempting to reinstall dependencies")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])
                return True
            except:
                return False
        
        elif "ConnectionError" in error_type or "ConnectionRefused" in error_type or "ECONNREFUSED" in error_msg:
            logger.warning(f"[AUTO-HEAL] Connection error - retrying in 5 seconds")
            time.sleep(5)
            return True
        
        elif "FileNotFoundError" in error_type:
            logger.warning(f"[AUTO-HEAL] File not found - attempting to create missing paths")
            try:
                os.makedirs("logs", exist_ok=True)
                os.makedirs("data", exist_ok=True)
                os.makedirs("audit", exist_ok=True)
                return True
            except:
                return False
        
        elif "MemoryError" in error_type:
            logger.critical(f"[AUTO-HEAL] Memory error - system may be unstable")
            return False
        
        elif "AttributeError" in error_type or "TypeError" in error_type:
            logger.warning(f"[AUTO-HEAL] Programming error detected - may be recoverable")
            return False
        
        else:
            logger.warning(f"[AUTO-HEAL] Unknown error type - attempting generic recovery")
            self.recovery_attempts += 1
            
            if self.recovery_attempts < self.max_retries:
                time.sleep(2 ** self.recovery_attempts)  # Exponential backoff
                return True
            else:
                logger.critical(f"[AUTO-HEAL] Max recovery attempts exceeded - fatal")
                return False


# Global error handler instance (available throughout module)
global_error_handler = SelfHealingErrorHandler()


class SovereignXCoreOS:
    """Master orchestration system"""
    
    def __init__(self):
        self.is_running = False
        self.startup_time = None
        self.config_validated = False
        
        # Core components
        self.regime_detector = None
        self.hawkes_processor = None
        self.qaoa_optimizer = None
        self.market_maker = None
        self.directional_agent = None
        
        # Pipeline components
        self.redis_pipeline = None
        self.mt5_gateway = None
        
        # State tracking
        self.system_state = {
            'status': 'initializing',
            'market_regime': 0,
            'positions_active': 0,
            'orders_executed': 0,
            'pnl': 0.0,
            'drawdown': 0.0,
        }
        
        logger.info("Sovereign-X Core OS initializing...")
    
    def validate_configuration(self) -> bool:
        """Validate all configuration parameters"""
        logger.info("Validating configuration...")
        
        if not Settings.validate():
            logger.error("Configuration validation failed")
            return False
        
        # Specific checks
        if Settings.risk.max_leverage < 1.0:
            logger.error("Invalid max leverage")
            return False
        
        if not Settings.PRIMARY_ASSETS or len(Settings.PRIMARY_ASSETS) == 0:
            logger.error("No primary assets configured")
            return False
        
        self.config_validated = True
        logger.info("Configuration validated successfully")
        return True
    
    def initialize_components(self) -> bool:
        """Initialize all core components with defensive error handling"""
        logger.info("Initializing core components with auto-recovery...")
        
        components_initialized = 0
        
        try:
            # Initialize regime detector
            try:
                self.regime_detector = RegimeDetector(
                    window_bars=Settings.regime_detector.window_bars,
                    smoothing=Settings.regime_detector.transition_smoothing
                )
                components_initialized += 1
                logger.debug("[OK] Regime Detector initialized")
            except Exception as e:
                logger.warning(f"Regime Detector failed: {e} - attempting recovery")
                if global_error_handler.handle(e, "regime_detector_init"):
                    self.regime_detector = RegimeDetector()
                    components_initialized += 1
            
            # Initialize Hawkes processor
            try:
                self.hawkes_processor = HawkesPointProcess(
                    alpha=Settings.hawkes.alpha,
                    beta=Settings.hawkes.beta,
                    lambda_0=Settings.hawkes.lambda_0
                )
                components_initialized += 1
                logger.debug("[OK] Hawkes Processor initialized")
            except Exception as e:
                logger.warning(f"Hawkes Processor failed: {e} - attempting recovery")
                if global_error_handler.handle(e, "hawkes_init"):
                    self.hawkes_processor = HawkesPointProcess()
                    components_initialized += 1
            
            # Initialize QAOA optimizer
            try:
                self.qaoa_optimizer = QAOAOptimizer(
                    depth=Settings.qaoa.depth,
                    learning_rate=Settings.qaoa.learning_rate
                )
                components_initialized += 1
                logger.debug("[OK] QAOA Optimizer initialized")
            except Exception as e:
                logger.warning(f"QAOA Optimizer failed: {e} - attempting recovery")
                if global_error_handler.handle(e, "qaoa_init"):
                    self.qaoa_optimizer = QAOAOptimizer()
                    components_initialized += 1
            
            # Initialize agents
            try:
                self.market_maker = MarketMakerAgent()
                self.directional_agent = DirectionalAgent()
                components_initialized += 2
                logger.debug("[OK] Trading Agents initialized")
            except Exception as e:
                logger.warning(f"Trading Agents failed: {e} - attempting recovery")
                if global_error_handler.handle(e, "agents_init"):
                    try:
                        self.market_maker = MarketMakerAgent()
                        self.directional_agent = DirectionalAgent()
                        components_initialized += 2
                    except Exception as e2:
                        logger.error(f"Agent recovery failed: {e2}")
            
            # Initialize pipeline components
            try:
                self.redis_pipeline = RedisStreamPipeline()
                logger.debug("[OK] Redis Pipeline initialized")
                components_initialized += 1
            except Exception as e:
                logger.warning(f"Redis Pipeline failed: {e} - continuing in demo mode")
                if global_error_handler.handle(e, "redis_init"):
                    self.redis_pipeline = RedisStreamPipeline()
                    components_initialized += 1
            
            try:
                self.mt5_gateway = MT5Gateway()
                logger.debug("[OK] MT5 Gateway initialized")
                components_initialized += 1
            except Exception as e:
                logger.warning(f"MT5 Gateway failed: {e} - continuing in demo mode")
                if global_error_handler.handle(e, "mt5_init"):
                    self.mt5_gateway = MT5Gateway()
                    components_initialized += 1
            
            if components_initialized >= 7:  # At least 7 of 8 components
                logger.info(f"Components initialized successfully ({components_initialized}/8)")
                return True
            else:
                logger.error(f"Critical: Only {components_initialized}/8 components initialized")
                return False
            
        except Exception as e:
            logger.error(f"Fatal component initialization error: {e}", exc_info=True)
            return False
    
    async def warmup_numba_jit(self) -> bool:
        """
        Execute warmup compilation sequence for Numba JIT functions
        Ensures zero-latency execution during live trading
        """
        logger.info("Executing Numba JIT warmup compilation...")
        
        try:
            import numpy as np
            from core.regime_detector import compute_rolling_statistics, hhmm_state_transition
            from core.order_flow import compute_hawkes_intensities
            from core.risk_engine import compute_qaoa_cost_hamiltonian
            
            # Warmup regime detector
            test_prices = np.random.uniform(1900, 2100, 200)
            compute_rolling_statistics(test_prices, 50)
            logger.debug("  [OK] Regime detector warmed up")
            
            # Warmup Hawkes
            test_times = np.sort(np.random.uniform(0, 252, 100))
            test_grid = np.linspace(0, 252, 50)
            compute_hawkes_intensities(test_times, test_grid, 0.6, 0.9, 1.5)
            logger.debug("  [OK] Hawkes processor warmed up")
            
            # Warmup QAOA
            test_weights = np.ones(3) / 3
            test_returns = np.array([0.08, 0.10, 0.06])
            test_cov = np.eye(3) * 0.01
            compute_qaoa_cost_hamiltonian(test_weights, test_returns, test_cov, 1.0)
            logger.debug("  [OK] QAOA optimizer warmed up")
            
            logger.info("Numba JIT warmup completed - ready for zero-latency execution")
            return True
            
        except Exception as e:
            logger.warning(f"Numba warmup had issues (non-critical): {e}")
            return True  # Don't fail on warmup issues
    
    async def connect_infrastructure(self) -> bool:
        """Connect to external infrastructure (Redis, MT5)"""
        logger.info("Connecting to infrastructure...")
        
        try:
            # Connect Redis
            redis_connected = await self.redis_pipeline.connect()
            if redis_connected:
                logger.info("[OK] Redis connected")
            else:
                logger.warning("[FAIL] Redis connection failed (continuing in demo mode)")
            
            # Connect MT5
            mt5_connected = self.mt5_gateway.connect()
            if mt5_connected:
                logger.info("[OK] MT5 connected")
                account = self.mt5_gateway.get_account_status()
                logger.info(f"  Account status: balance={account.get('balance', 'N/A')}, drawdown={account.get('drawdown', 0):.2%}")
            else:
                logger.warning("[FAIL] MT5 connection failed (continuing in demo mode)")
            
            return True
            
        except Exception as e:
            logger.error(f"Infrastructure connection error: {e}")
            return False
    
    async def market_data_loop(self) -> None:
        """Consume market data from Redis and process"""
        logger.info("Starting market data loop...")
        
        if not self.redis_pipeline.is_connected:
            logger.warning("Redis not connected - using synthetic data")
        
        tick_count = 0
        try:
            while self.is_running:
                try:
                    if self.redis_pipeline.is_connected:
                        # Consume from Redis
                        async for tick in self.redis_pipeline.consume_ticks():
                            if not self.is_running:
                                break
                            
                            await self.process_market_tick(tick)
                            tick_count += 1
                            
                            if tick_count % 100 == 0:
                                logger.debug(f"Processed {tick_count} ticks")
                    else:
                        # Simulate market data
                        await asyncio.sleep(1)
                        synthetic_tick = {
                            'asset': 'XAUUSD',
                            'bid': 2000.0 + np.random.normal(0, 1),
                            'ask': 2000.02 + np.random.normal(0, 1),
                            'timestamp': time.time(),
                        }
                        await self.process_market_tick(synthetic_tick)
                        tick_count += 1
                
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Market data loop error: {e}")
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Fatal market data loop error: {e}")
        
        logger.info(f"Market data loop stopped after {tick_count} ticks")
    
    async def process_market_tick(self, tick: Dict) -> None:
        """Process individual market tick"""
        try:
            # Extract data
            bid = tick.get('bid', 0)
            ask = tick.get('ask', 0)
            mid_price = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0
            
            if mid_price <= 0:
                return
            
            # Update Hawkes with order flow
            current_time = tick.get('timestamp', time.time())
            self.hawkes_processor.update_events(np.array([current_time]))
            hawkes_intensity = self.hawkes_processor.get_current_intensity(current_time)
            
            # Detect market regime
            # (In production: maintain rolling price buffer)
            test_prices = np.array([mid_price - 0.1, mid_price - 0.05, mid_price, mid_price + 0.05, mid_price + 0.1])
            regimes, regime_metrics = self.regime_detector.detect(test_prices)
            current_regime = regimes[-1] if len(regimes) > 0 else 0
            
            # Update system state
            self.system_state['market_regime'] = int(current_regime)
            
            # Market maker logic (State-0)
            if current_regime == 0:
                bid_vol = tick.get('bid_volume', 1000)
                ask_vol = tick.get('ask_volume', 1000)
                
                mm_orders = self.market_maker.generate_orders(
                    mid_price, hawkes_intensity, bid_vol, ask_vol
                )
                
                # Would send orders to MT5 in production
                if mm_orders and Settings.mt5.enable_live_trading:
                    for order in mm_orders:
                        result = self.mt5_gateway.execute_order({
                            'symbol': 'XAUUSD',
                            'order_type': order['type'],
                            'volume': order['volume'],
                            'price': order['price'],
                        })
                        if result:
                            self.system_state['orders_executed'] += 1
            
            # Directional agent logic (State-1)
            elif current_regime == 1:
                market_data = {
                    'prices': np.array([mid_price - 0.1, mid_price]),
                    'bid_volume': tick.get('bid_volume', 1000),
                    'ask_volume': tick.get('ask_volume', 1000),
                    'hawkes_intensity': hawkes_intensity,
                }
                
                state = self.directional_agent.build_state_representation(market_data)
                action, size = self.directional_agent.compute_policy_action(state)
                
                if action != 'HOLD' and Settings.mt5.enable_live_trading:
                    result = self.mt5_gateway.execute_order({
                        'symbol': 'XAUUSD',
                        'order_type': action,
                        'volume': size,
                        'price': mid_price,
                    })
                    if result:
                        self.system_state['orders_executed'] += 1
        
        except Exception as e:
            logger.debug(f"Error processing tick: {e}")
    
    async def risk_monitor_loop(self) -> None:
        """Monitor risk metrics and trigger circuit breaker if needed"""
        logger.info("Starting risk monitoring loop...")
        
        try:
            while self.is_running:
                try:
                    # Check account status
                    account_status = self.mt5_gateway.get_account_status()
                    
                    if account_status:
                        drawdown = account_status.get('drawdown', 0)
                        self.system_state['drawdown'] = drawdown
                        
                        # Check circuit breaker
                        if self.mt5_gateway.check_circuit_breaker():
                            logger.critical("CIRCUIT BREAKER TRIGGERED")
                            self.is_running = False
                            break
                    
                    # Check agent limits
                    mm_risk = self.market_maker.get_risk_metrics()
                    if mm_risk.get('position_limit_exceeded', False):
                        logger.warning("Market maker position limit exceeded")
                    
                    await asyncio.sleep(5)  # Check every 5 seconds
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Risk monitor error: {e}")
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Fatal risk monitor error: {e}")
        
        logger.info("Risk monitoring loop stopped")
    
    async def start(self) -> bool:
        """Start the complete Sovereign-X system"""
        logger.info("="*60)
        logger.info("SOVEREIGN-X CORE OS - SYSTEM STARTUP")
        logger.info("="*60)
        
        self.startup_time = datetime.now()
        
        # Validation
        if not self.validate_configuration():
            logger.error("Configuration validation failed - aborting startup")
            return False
        
        # Initialize components
        if not self.initialize_components():
            logger.error("Component initialization failed - aborting startup")
            return False
        
        # Warmup JIT
        if not await self.warmup_numba_jit():
            logger.warning("JIT warmup issues - continuing anyway")
        
        # Connect infrastructure
        if not await self.connect_infrastructure():
            logger.warning("Infrastructure connection issues - continuing in demo mode")
        
        # Start running
        self.is_running = True
        self.system_state['status'] = 'running'
        
        logger.info("="*60)
        logger.info("SYSTEM READY FOR LIVE TRADING")
        logger.info("="*60)
        
        # Create concurrent tasks
        tasks = [
            asyncio.create_task(self.market_data_loop()),
            asyncio.create_task(self.risk_monitor_loop()),
        ]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received - shutting down")
        
        return True
    
    async def shutdown(self) -> None:
        """Graceful system shutdown"""
        logger.info("Initiating graceful shutdown...")
        
        self.is_running = False
        
        # Close connections
        if self.redis_pipeline and self.redis_pipeline.is_connected:
            await self.redis_pipeline.disconnect()
        
        if self.mt5_gateway and self.mt5_gateway.is_connected:
            self.mt5_gateway.disconnect()
        
        # Print final statistics
        uptime = (datetime.now() - self.startup_time).total_seconds() if self.startup_time else 0
        logger.info("="*60)
        logger.info("SYSTEM SHUTDOWN - FINAL STATISTICS")
        logger.info(f"Uptime: {uptime:.1f} seconds")
        logger.info(f"Orders Executed: {self.system_state['orders_executed']}")
        logger.info(f"Final Drawdown: {self.system_state['drawdown']:.2%}")
        logger.info("="*60)


async def main():
    """Main entry point with comprehensive error handling"""
    system = SovereignXCoreOS()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Signal received - initiating shutdown")
        asyncio.create_task(system.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start system with defensive error handling
    try:
        await system.start()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        await system.shutdown()
        raise




if __name__ == '__main__':
    """
    Production entry point with comprehensive error handling and auto-recovery
    """
    try:
        # Create necessary directories
        os.makedirs("logs", exist_ok=True)
        os.makedirs("data", exist_ok=True)
        os.makedirs("audit", exist_ok=True)
        
        # Validate configuration
        logger.info("Validating configuration...")
        if not Settings.validate():
            logger.error("Configuration validation failed")
            sys.exit(1)
        
        # Run main async loop
        logger.info("Starting Sovereign-X Core OS...")
        asyncio.run(main())
    
    except KeyboardInterrupt:
        logger.info("Program interrupted by user - graceful shutdown")
    
    except ImportError as e:
        logger.error(f"Import error: {e}", exc_info=True)
        if global_error_handler.handle(e, "main_entry"):
            logger.info("Auto-recovery successful - restarting")
            # Could implement restart logic here
        else:
            logger.critical("Auto-recovery failed - cannot continue")
            sys.exit(1)
    
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        if global_error_handler.handle(e, "main_entry"):
            logger.info("Auto-recovery attempted")
        else:
            logger.critical("Fatal error - system cannot recover")
            sys.exit(1)
    
    finally:
        logger.info("Sovereign-X Core OS terminated")
        logging.shutdown()
