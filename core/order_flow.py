"""
Hawkes Point Process - Self-Exciting Order Flow Intensity Calculator
Isolates order flow self-excitation patterns for market microstructure analysis
Compiled with Numba @njit for ultra-high-frequency execution
"""

import numpy as np
from numba import njit
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


@njit(fastmath=True, cache=True)
def hawkes_intensity_recursive(event_times: np.ndarray, current_time: float,
                               alpha: float, beta: float, lambda_0: float) -> float:
    """
    Compute Hawkes process intensity at current time
    
    λ(t) = α₀ + Σ(i: t_i < t) α · exp(-β(t - t_i))
    
    Args:
        event_times: Array of historical event timestamps
        current_time: Current time at which to evaluate intensity
        alpha: Self-excitement coefficient (0 < α < 1)
        beta: Decay rate (β > 0)
        lambda_0: Base intensity
    
    Returns:
        Hawkes intensity value at current_time
    """
    if len(event_times) == 0:
        return lambda_0
    
    intensity = lambda_0
    
    for i in range(len(event_times)):
        event_time = event_times[i]
        
        # Only sum past events
        if event_time < current_time:
            time_diff = current_time - event_time
            
            # Defensive check: prevent numerical overflow
            if time_diff < 100.0:  # Prevent exp overflow
                decay_component = alpha * np.exp(-beta * time_diff)
                intensity += decay_component
    
    return intensity


@njit(fastmath=True, cache=True)
def compute_hawkes_intensities(event_times: np.ndarray, time_grid: np.ndarray,
                               alpha: float, beta: float, lambda_0: float) -> np.ndarray:
    """
    Compute Hawkes intensities across a time grid
    
    Args:
        event_times: Array of event timestamps
        time_grid: Time points at which to evaluate intensity
        alpha: Self-excitement coefficient
        beta: Decay rate
        lambda_0: Base intensity
    
    Returns:
        Array of intensity values matching time_grid length
    """
    n = len(time_grid)
    intensities = np.zeros(n)
    
    for i in range(n):
        current_time = time_grid[i]
        intensities[i] = hawkes_intensity_recursive(event_times, current_time, 
                                                     alpha, beta, lambda_0)
    
    return intensities


@njit(fastmath=True, cache=True)
def estimate_hawkes_parameters(inter_arrival_times: np.ndarray) -> Tuple[float, float]:
    """
    Estimate Hawkes parameters from inter-arrival time data
    Uses method of moments estimation
    
    Args:
        inter_arrival_times: Array of time intervals between consecutive events
    
    Returns:
        Tuple of (alpha_estimate, beta_estimate)
    """
    if len(inter_arrival_times) < 2:
        return 0.6, 0.9
    
    # Compute mean inter-arrival time
    n = len(inter_arrival_times)
    mean_iat = 0.0
    for i in range(n):
        mean_iat += inter_arrival_times[i]
    mean_iat /= n if n > 0 else 1
    
    # Compute variance of inter-arrival times
    variance = 0.0
    for i in range(n):
        diff = inter_arrival_times[i] - mean_iat
        variance += diff * diff
    variance /= n if n > 0 else 1
    
    # Estimate alpha (branching ratio)
    # Higher variance indicates higher self-excitement
    alpha_estimate = min(0.95, (variance - mean_iat) / (variance + 1e-10)) if variance > mean_iat else 0.6
    alpha_estimate = max(0.01, alpha_estimate)  # Bound between 0.01 and 0.95
    
    # Estimate beta (decay rate)
    # Inverse of mean inter-arrival time
    beta_estimate = 1.0 / (mean_iat + 1e-10)
    beta_estimate = min(2.0, beta_estimate)  # Cap beta at 2.0
    
    return alpha_estimate, beta_estimate


@njit(fastmath=True, cache=True)
def compute_order_flow_imbalance(bid_volumes: np.ndarray, ask_volumes: np.ndarray) -> np.ndarray:
    """
    Compute order book imbalance as measure of directional pressure
    
    Args:
        bid_volumes: Array of bid-side volumes
        ask_volumes: Array of ask-side volumes
    
    Returns:
        Array of imbalance ratios normalized to [-1, 1]
    """
    n = min(len(bid_volumes), len(ask_volumes))
    imbalances = np.zeros(n)
    
    for i in range(n):
        bid_vol = bid_volumes[i]
        ask_vol = ask_volumes[i]
        total_vol = bid_vol + ask_vol
        
        if total_vol > 1e-10:
            imbalances[i] = (bid_vol - ask_vol) / total_vol
        else:
            imbalances[i] = 0.0
    
    return imbalances


@njit(fastmath=True, cache=True)
def compute_self_excitation_intensity(hawkes_intensities: np.ndarray,
                                      order_imbalances: np.ndarray) -> np.ndarray:
    """
    Combine Hawkes intensity with order book imbalance for directional signal
    
    Args:
        hawkes_intensities: Hawkes process intensity values
        order_imbalances: Order book imbalance ratios
    
    Returns:
        Combined self-excitation signals
    """
    n = min(len(hawkes_intensities), len(order_imbalances))
    signals = np.zeros(n)
    
    for i in range(n):
        intensity = hawkes_intensities[i]
        imbalance = order_imbalances[i]
        
        # Combine signals: intensity amplifies imbalance signal
        signals[i] = intensity * imbalance
    
    return signals


class HawkesPointProcess:
    """Hawkes process for order flow microstructure analysis"""
    
    def __init__(self, alpha: float = 0.6, beta: float = 0.9, lambda_0: float = 1.5):
        self.alpha = alpha
        self.beta = beta
        self.lambda_0 = lambda_0
        self.event_times = np.array([], dtype=np.float64)
        self.intensities_cache = None
        logger.info(f"HawkesPointProcess initialized: alpha={alpha}, beta={beta}, lambda_0={lambda_0}")
    
    def update_events(self, new_event_times: np.ndarray) -> None:
        """Update event times array"""
        if new_event_times is not None and len(new_event_times) > 0:
            self.event_times = np.concatenate([self.event_times, new_event_times])
            # Keep only recent events (last 10000 to prevent memory bloat)
            if len(self.event_times) > 10000:
                self.event_times = self.event_times[-10000:]
    
    def compute_intensity(self, time_grid: np.ndarray) -> np.ndarray:
        """
        Compute Hawkes intensities at specified times
        
        Args:
            time_grid: Array of time points
        
        Returns:
            Array of intensity values
        """
        if time_grid is None or len(time_grid) == 0:
            logger.warning("Empty time grid provided")
            return np.array([self.lambda_0])
        
        intensities = compute_hawkes_intensities(self.event_times, time_grid,
                                                 self.alpha, self.beta, self.lambda_0)
        self.intensities_cache = intensities
        return intensities
    
    def adapt_parameters(self, inter_arrival_times: np.ndarray) -> None:
        """Adaptively estimate Hawkes parameters from data"""
        if inter_arrival_times is None or len(inter_arrival_times) < 2:
            return
        
        alpha_new, beta_new = estimate_hawkes_parameters(inter_arrival_times)
        self.alpha = alpha_new
        self.beta = beta_new
        logger.debug(f"Parameters adapted: α={alpha_new:.4f}, β={beta_new:.4f}")
    
    def get_current_intensity(self, current_time: float) -> float:
        """Get current Hawkes intensity"""
        if len(self.event_times) == 0:
            return self.lambda_0
        
        return hawkes_intensity_recursive(self.event_times, current_time,
                                         self.alpha, self.beta, self.lambda_0)
    
    def analyze_order_flow(self, bid_volumes: np.ndarray, ask_volumes: np.ndarray,
                          hawkes_intensities: np.ndarray) -> dict:
        """
        Analyze order flow microstructure using Hawkes-weighted imbalance
        
        Args:
            bid_volumes: Bid-side volumes
            ask_volumes: Ask-side volumes
            hawkes_intensities: Hawkes process intensities
        
        Returns:
            Dictionary of order flow metrics
        """
        if bid_volumes is None or ask_volumes is None or len(bid_volumes) == 0:
            logger.warning("Invalid volume data for order flow analysis")
            return {}
        
        imbalances = compute_order_flow_imbalance(bid_volumes, ask_volumes)
        
        # Ensure arrays are aligned
        n = min(len(imbalances), len(hawkes_intensities))
        imbalances = imbalances[:n]
        hawkes_intensities = hawkes_intensities[:n]
        
        signals = compute_self_excitation_intensity(hawkes_intensities, imbalances)
        
        metrics = {
            'avg_intensity': float(np.mean(hawkes_intensities)) if len(hawkes_intensities) > 0 else 0,
            'max_intensity': float(np.max(hawkes_intensities)) if len(hawkes_intensities) > 0 else 0,
            'avg_imbalance': float(np.mean(imbalances)) if len(imbalances) > 0 else 0,
            'max_signal': float(np.max(np.abs(signals))) if len(signals) > 0 else 0,
            'signal_direction': float(signals[-1]) if len(signals) > 0 else 0,
        }
        
        return metrics
