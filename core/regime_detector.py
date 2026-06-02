"""
Hierarchical Hidden Markov Model (HHMM) State Switching Engine
Detects market regimes and Merton Jump Diffusion anomalies
Compiled with Numba @njit for production ultra-low latency
"""

import numpy as np
from numba import njit, prange
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


@njit(fastmath=True, parallel=True, cache=True)
def compute_rolling_statistics(prices: np.ndarray, window: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute rolling log returns, skewness, and kurtosis for regime detection
    
    Args:
        prices: Array of asset prices (1D)
        window: Rolling window size in bars
    
    Returns:
        Tuple of (returns, skewness, kurtosis) arrays
    """
    n = len(prices)
    if n < window + 1:
        return np.array([0.0]), np.array([0.0]), np.array([0.0])
    
    returns = np.zeros(n - 1)
    skewness = np.zeros(n - window)
    kurtosis = np.zeros(n - window)
    
    # Compute log returns
    for i in prange(n - 1):
        if prices[i] > 0 and prices[i + 1] > 0:
            returns[i] = np.log(prices[i + 1] / prices[i])
        else:
            returns[i] = 0.0
    
    # Compute rolling skewness and kurtosis
    for i in prange(n - window):
        window_returns = returns[i:i + window]
        mean_ret = 0.0
        for j in range(window):
            mean_ret += window_returns[j]
        mean_ret /= window
        
        # Compute variance
        variance = 0.0
        for j in range(window):
            diff = window_returns[j] - mean_ret
            variance += diff * diff
        variance /= window
        
        std_dev = np.sqrt(variance) if variance > 1e-10 else 1e-10
        
        # Compute third moment (skewness)
        third_moment = 0.0
        for j in range(window):
            diff = window_returns[j] - mean_ret
            third_moment += diff * diff * diff
        third_moment /= window
        
        skewness[i] = third_moment / (std_dev ** 3) if std_dev > 1e-10 else 0.0
        
        # Compute fourth moment (kurtosis)
        fourth_moment = 0.0
        for j in range(window):
            diff = window_returns[j] - mean_ret
            fourth_moment += diff * diff * diff * diff
        fourth_moment /= window
        
        kurtosis[i] = (fourth_moment / (variance * variance)) - 3.0 if variance > 1e-10 else 0.0
    
    return returns, skewness, kurtosis


@njit(fastmath=True, cache=True)
def detect_merton_jump_anomalies(returns: np.ndarray, kurtosis: np.ndarray, 
                                  sensitivity: float) -> np.ndarray:
    """
    Detect Merton Jump Diffusion anomalies indicating imminent volatility bursts
    
    Args:
        returns: Log returns array
        kurtosis: Rolling kurtosis array
        sensitivity: Jump sensitivity parameter (0-1)
    
    Returns:
        Array of jump probability indicators
    """
    n = len(returns)
    jump_probs = np.zeros(n)
    
    # Compute rolling volatility
    volatilities = np.zeros(n)
    window = max(20, int(n * 0.1))
    
    for i in range(window, n):
        window_returns = returns[i - window:i]
        mean_ret = 0.0
        for j in range(window):
            mean_ret += window_returns[j]
        mean_ret /= window
        
        variance = 0.0
        for j in range(window):
            diff = window_returns[j] - mean_ret
            variance += diff * diff
        variance /= window
        volatilities[i] = np.sqrt(variance)
    
    # Detect anomalies based on returns and kurtosis
    kurt_idx = 0
    for i in range(n):
        if kurt_idx < len(kurtosis):
            # High kurtosis indicates fat tails (jump risk)
            excess_kurtosis = kurtosis[kurt_idx] if kurt_idx < len(kurtosis) else 0.0
            
            # Large return magnitude relative to volatility
            if volatilities[i] > 1e-10:
                standardized_return = abs(returns[i]) / volatilities[i]
            else:
                standardized_return = 0.0
            
            # Combine signals
            jump_signal = (excess_kurtosis * sensitivity) + (standardized_return * 0.3)
            jump_probs[i] = np.tanh(jump_signal)  # Normalize to [0, 1]
            
            if i >= len(kurtosis) - 1:
                kurt_idx = len(kurtosis) - 1
            else:
                kurt_idx += 1
    
    return jump_probs


@njit(fastmath=True, parallel=True, cache=True)
def hhmm_state_transition(returns: np.ndarray, skewness: np.ndarray, 
                          kurtosis: np.ndarray, jump_probs: np.ndarray,
                          smoothing: float) -> np.ndarray:
    """
    Compute HHMM state probabilities (0=Mean-Reverting, 1=Trending, 2=Crisis)
    
    Args:
        returns: Log returns
        skewness: Rolling skewness
        kurtosis: Rolling kurtosis
        jump_probs: Merton jump probabilities
        smoothing: Transition smoothing parameter
    
    Returns:
        State array with values in {0, 1, 2}
    """
    n = len(returns)
    states = np.zeros(n, dtype=np.int32)
    state_probs = np.zeros((n, 3))
    
    # Compute state probabilities at each timestamp
    for i in prange(n):
        prob_mean_revert = 0.0
        prob_trend = 0.0
        prob_crisis = 0.0
        
        # Mean-reverting regime: low skewness, normal kurtosis
        if i < len(skewness):
            abs_skew = abs(skewness[i])
            abs_kurt = abs(kurtosis[i]) if i < len(kurtosis) else 0.0
            jump_prob = jump_probs[i] if i < len(jump_probs) else 0.0
        else:
            abs_skew = 0.0
            abs_kurt = 0.0
            jump_prob = 0.0
        
        prob_mean_revert = np.exp(-abs_skew) * (1.0 - 0.5 * abs_kurt / 5.0) * (1.0 - jump_prob)
        
        # Trending regime: high skewness, elevated returns
        abs_ret = abs(returns[i]) if i < len(returns) else 0.0
        prob_trend = (abs_skew / (abs_skew + 1.0)) * (abs_ret * 100.0) * (1.0 - jump_prob * 0.5)
        
        # Crisis regime: extreme kurtosis, jump probability
        prob_crisis = (abs_kurt / (abs_kurt + 3.0)) * jump_prob * (1.0 + abs_skew)
        
        # Normalize probabilities
        total_prob = prob_mean_revert + prob_trend + prob_crisis
        if total_prob > 1e-10:
            prob_mean_revert /= total_prob
            prob_trend /= total_prob
            prob_crisis /= total_prob
        else:
            prob_mean_revert = 1.0 / 3.0
            prob_trend = 1.0 / 3.0
            prob_crisis = 1.0 / 3.0
        
        state_probs[i, 0] = prob_mean_revert
        state_probs[i, 1] = prob_trend
        state_probs[i, 2] = prob_crisis
        
        # Determine dominant state with smoothing
        if i == 0:
            states[i] = np.argmax(np.array([prob_mean_revert, prob_trend, prob_crisis]))
        else:
            # Apply smoothing to previous state
            prev_state = int(states[i - 1])
            probs_smoothed = np.array([
                prob_mean_revert * (1.0 - smoothing) + (1.0 if prev_state == 0 else 0.0) * smoothing,
                prob_trend * (1.0 - smoothing) + (1.0 if prev_state == 1 else 0.0) * smoothing,
                prob_crisis * (1.0 - smoothing) + (1.0 if prev_state == 2 else 0.0) * smoothing
            ])
            states[i] = np.argmax(probs_smoothed)
    
    return states


class RegimeDetector:
    """High-level regime detection interface"""
    
    def __init__(self, window_bars: int = 50, smoothing: float = 0.8):
        self.window_bars = window_bars
        self.smoothing = smoothing
        self.states_cache = None
        self.jump_probs_cache = None
        logger.info(f"RegimeDetector initialized with window={window_bars}, smoothing={smoothing}")
    
    def detect(self, prices: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Detect market regimes from price data
        
        Args:
            prices: Array of asset prices
        
        Returns:
            Tuple of (state_array, metrics_dict)
        """
        if prices is None or len(prices) < self.window_bars + 1:
            logger.warning("Insufficient price data for regime detection")
            return np.array([0]), {}
        
        # Compute statistics
        returns, skewness, kurtosis = compute_rolling_statistics(prices, self.window_bars)
        
        if len(returns) < 1 or len(skewness) < 1:
            logger.error("Failed to compute rolling statistics")
            return np.array([0]), {}
        
        # Detect jump anomalies
        jump_probs = detect_merton_jump_anomalies(returns, kurtosis, sensitivity=0.5)
        self.jump_probs_cache = jump_probs
        
        # Compute HHMM states
        states = hhmm_state_transition(returns, skewness, kurtosis, jump_probs, self.smoothing)
        self.states_cache = states
        
        # Compute metrics
        metrics = {
            'current_state': int(states[-1]) if len(states) > 0 else 0,
            'mean_revert_pct': float(np.sum(states == 0) / len(states) * 100) if len(states) > 0 else 0,
            'trending_pct': float(np.sum(states == 1) / len(states) * 100) if len(states) > 0 else 0,
            'crisis_pct': float(np.sum(states == 2) / len(states) * 100) if len(states) > 0 else 0,
            'avg_jump_prob': float(np.mean(jump_probs)) if len(jump_probs) > 0 else 0,
            'max_jump_prob': float(np.max(jump_probs)) if len(jump_probs) > 0 else 0,
            'avg_kurtosis': float(np.mean(kurtosis)) if len(kurtosis) > 0 else 0,
            'avg_skewness': float(np.mean(skewness)) if len(skewness) > 0 else 0,
        }
        
        logger.debug(f"Regime detection complete: state={metrics['current_state']}")
        return states, metrics
