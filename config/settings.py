"""
Sovereign-X Core OS - Institutional Configuration Matrix
Consolidated hyperparameters, quantum gates, and connection configurations
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple
from dotenv import load_dotenv
import numpy as np

# Load environment variables from .env file
load_dotenv()


@dataclass(frozen=True)
class HawkesParameters:
    """Hawkes Point Process configuration parameters"""
    alpha: float = float(os.getenv('HAWKES_ALPHA', 0.6))  # Self-excitement coefficient
    beta: float = float(os.getenv('HAWKES_BETA', 0.9))    # Decay rate
    lambda_0: float = 1.5  # Base intensity
    decay_constant: float = float(os.getenv('REGIME_WINDOW_BARS', 0.95))  # Exponential decay


@dataclass(frozen=True)
class QAOAParameters:
    """Quantum Approximate Optimization Algorithm configuration"""
    depth: int = int(os.getenv('QAOA_DEPTH', 5))  # Number of phase-shifting layers
    max_iterations: int = 100
    gamma_init: float = 0.5  # Initial phase angle
    beta_init: float = 0.5   # Initial mixer angle
    learning_rate: float = 0.01


@dataclass(frozen=True)
class PPOConfiguration:
    """Proximal Policy Optimization hyperparameters"""
    learning_rate: float = float(os.getenv('PPO_LEARNING_RATE', 3e-4))
    clip_range: float = 0.2
    entropy_coefficient: float = float(os.getenv('ENTROPY_COEFFICIENT', 0.01))
    value_loss_coefficient: float = 1.0
    max_grad_norm: float = 0.5
    n_epochs: int = 10
    batch_size: int = 64
    gamma: float = 0.99  # Discount factor
    gae_lambda: float = 0.95  # Generalized Advantage Estimation lambda


@dataclass(frozen=True)
class SACConfiguration:
    """Soft Actor-Critic hyperparameters"""
    learning_rate: float = float(os.getenv('SAC_LEARNING_RATE', 1e-3))
    gamma: float = 0.99
    tau: float = 0.005  # Target network update rate
    alpha: float = 0.2  # Temperature parameter
    target_entropy: float = None  # Auto-computed based on action space
    buffer_size: int = 1000000
    batch_size: int = 256


@dataclass(frozen=True)
class RiskManagementBoundaries:
    """Global strict infrastructure guardrails"""
    max_leverage: float = float(os.getenv('MAX_LEVERAGE', 10.0))
    max_trailing_drawdown: float = float(os.getenv('MAX_TRAILING_DRAWDOWN', 0.15))
    min_profit_threshold: float = float(os.getenv('MIN_PROFIT_THRESHOLD', 100.0))
    position_size_usd: float = float(os.getenv('POSITION_SIZE_USD', 10000.0))
    circuit_breaker_threshold: float = float(os.getenv('CIRCUIT_BREAKER_THRESHOLD', 0.20))
    max_position_size_percentage: float = 0.25
    risk_reward_ratio: float = 1.5


@dataclass(frozen=True)
class MetaTrader5Configuration:
    """MT5 connection and execution parameters"""
    login: int = int(os.getenv('MT5_LOGIN', 123456789))
    password: str = os.getenv('MT5_PASSWORD', 'password')
    server: str = os.getenv('MT5_SERVER', 'MetaQuotes-Demo')
    timeout: int = 10000  # milliseconds
    enable_live_trading: bool = os.getenv('ENABLE_LIVE_TRADING', 'False').lower() == 'true'
    deviation: int = 10  # Slippage tolerance in points
    order_filling: str = 'ORDER_FILLING_IOC'  # Immediate or Cancel
    enable_emergency_liquidation: bool = os.getenv('ENABLE_EMERGENCY_LIQUIDATION', 'True').lower() == 'true'


@dataclass(frozen=True)
class RedisConfiguration:
    """Redis Stream configuration for data pipeline"""
    host: str = os.getenv('REDIS_HOST', '127.0.0.1')
    port: int = int(os.getenv('REDIS_PORT', 6379))
    db: int = int(os.getenv('REDIS_DB', 0))
    password: str = os.getenv('REDIS_PASSWORD', None)
    tick_stream_key: str = 'market_ticks'
    order_flow_stream_key: str = 'order_flow'
    signal_stream_key: str = 'trading_signals'
    batch_size: int = 100
    max_retries: int = 5
    retry_delay: float = 1.0
    demo_mode: bool = os.getenv('REDIS_DEMO_MODE', 'False').lower() == 'true'  # Fallback to synthetic data


@dataclass(frozen=True)
class RegimeDetectorParameters:
    """HHMM regime detector configuration"""
    window_bars: int = int(os.getenv('REGIME_WINDOW_BARS', 50))
    n_states: int = 3  # Mean-Reverting, Trending, Crisis
    hidden_layer_size: int = 64
    transition_smoothing: float = 0.8
    kurtosis_threshold: float = 3.0
    skewness_threshold: float = 1.0
    merton_jump_sensitivity: float = 0.5


@dataclass(frozen=True)
class MarketMakerParameters:
    """Market maker agent configuration"""
    base_spread_bps: float = 5.0  # Base spread in basis points
    max_spread_bps: float = 50.0
    min_spread_bps: float = 1.0
    volume_skew_threshold: float = 0.3
    hawkes_intensity_multiplier: float = 2.0
    rebalance_interval_seconds: float = 1.0
    max_orders_per_leg: int = 5


@dataclass(frozen=True)
class DirectionalAgentParameters:
    """Directional taker agent configuration"""
    order_imbalance_threshold: float = 0.7
    momentum_window: int = 20
    max_position_holdtime_seconds: float = 300.0
    ppo_update_frequency: int = 100
    rolling_memory_buffer_size: int = 500


@dataclass(frozen=True)
class LoggingConfiguration:
    """Logging system configuration"""
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')
    log_dir: str = os.getenv('LOG_DIR', './logs')
    log_format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    max_file_size: int = 10485760  # 10 MB
    backup_count: int = 5
    debug_mode: bool = os.getenv('DEBUG_MODE', 'False').lower() == 'true'


class Settings:
    """Master configuration singleton"""
    
    hawkes = HawkesParameters()
    qaoa = QAOAParameters()
    ppo = PPOConfiguration()
    sac = SACConfiguration()
    risk = RiskManagementBoundaries()
    mt5 = MetaTrader5Configuration()
    redis = RedisConfiguration()
    regime_detector = RegimeDetectorParameters()
    market_maker = MarketMakerParameters()
    directional = DirectionalAgentParameters()
    logging = LoggingConfiguration()
    
    # Asset configuration
    PRIMARY_ASSETS: List[str] = os.getenv('PRIMARY_ASSETS', 'XAUUSD,BTCUSD,EURUSD').split(',')
    TRADING_HOURS_START: str = os.getenv('TRADING_HOURS_START', '09:00')
    TRADING_HOURS_END: str = os.getenv('TRADING_HOURS_END', '17:00')
    
    # System buffers
    TICK_BUFFER_SIZE: int = int(os.getenv('TICK_BUFFER_SIZE', 10000))
    
    @staticmethod
    def validate() -> bool:
        """Validate all configuration parameters for consistency"""
        errors = []
        
        if Settings.risk.max_leverage <= 1.0:
            errors.append("MAX_LEVERAGE must be > 1.0")
        
        if Settings.risk.max_trailing_drawdown <= 0 or Settings.risk.max_trailing_drawdown >= 1.0:
            errors.append("MAX_TRAILING_DRAWDOWN must be between 0 and 1")
        
        if Settings.qaoa.depth <= 0:
            errors.append("QAOA_DEPTH must be positive")
        
        if Settings.ppo.learning_rate <= 0:
            errors.append("PPO_LEARNING_RATE must be positive")
        
        if Settings.hawkes.alpha <= 0 or Settings.hawkes.alpha >= 1.0:
            errors.append("HAWKES_ALPHA must be between 0 and 1")
        
        if Settings.hawkes.beta <= 0 or Settings.hawkes.beta >= 1.0:
            errors.append("HAWKES_BETA must be between 0 and 1")
        
        if Settings.regime_detector.window_bars <= 0:
            errors.append("REGIME_WINDOW_BARS must be positive")
        
        if len(Settings.PRIMARY_ASSETS) == 0:
            errors.append("PRIMARY_ASSETS list is empty")
        
        if errors:
            for error in errors:
                print(f"Configuration Error: {error}")
            return False
        
        return True
    
    @staticmethod
    def get_asset_config(asset: str) -> Dict:
        """Get asset-specific configuration"""
        asset_configs = {
            'XAUUSD': {'pip_value': 0.01, 'min_lot': 0.01, 'tick_size': 0.01},
            'BTCUSD': {'pip_value': 0.01, 'min_lot': 0.01, 'tick_size': 0.01},
            'EURUSD': {'pip_value': 0.0001, 'min_lot': 0.01, 'tick_size': 0.0001},
        }
        return asset_configs.get(asset, {'pip_value': 0.0001, 'min_lot': 0.01, 'tick_size': 0.0001})


# Verify configuration on import
if not Settings.validate():
    raise ValueError("Configuration validation failed. Check .env file and parameters.")
