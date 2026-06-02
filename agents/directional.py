"""
Directional Momentum Taker Agent
Activates during State-1 (Trending) regimes
Uses recurrent memory buffers and PPO-inspired reinforcement learning logic
"""

import numpy as np
import asyncio
from typing import Dict, List, Tuple, Optional
import logging
from collections import deque
from config.settings import Settings

logger = logging.getLogger(__name__)


class DirectionalAgent:
    """Directional taker agent for State-1 trending regimes"""
    
    def __init__(self, state_size: int = 20):
        self.state_size = state_size
        self.order_imbalance_threshold = Settings.directional.order_imbalance_threshold
        self.momentum_window = Settings.directional.momentum_window
        self.max_holdtime_seconds = Settings.directional.max_position_holdtime_seconds
        self.ppo_update_freq = Settings.directional.ppo_update_frequency
        self.memory_buffer_size = Settings.directional.rolling_memory_buffer_size
        
        # Recurrent memory buffer (stateful tracking)
        self.rolling_state_buffer = deque(maxlen=state_size)
        self.action_history = deque(maxlen=100)
        self.reward_history = deque(maxlen=100)
        self.state_history = deque(maxlen=self.memory_buffer_size)
        
        # PPO-inspired state tracking
        self.policy_gradient_accumulator = 0.0
        self.value_baseline = 0.0
        self.cumulative_advantage = 0.0
        self.update_counter = 0
        
        # Position tracking
        self.position = 0.0
        self.entry_price = 0.0
        self.entry_time = 0.0
        self.max_pnl = 0.0
        self.min_pnl = 0.0
        
        logger.info(f"DirectionalAgent initialized with state_size={state_size}")
    
    def compute_order_imbalance(self, bid_volume: float, ask_volume: float) -> float:
        """
        Compute normalized order book imbalance
        
        Args:
            bid_volume: Bid-side volume
            ask_volume: Ask-side volume
        
        Returns:
            Imbalance ratio in range [-1, 1]
        """
        total = bid_volume + ask_volume
        if total < 1e-10:
            return 0.0
        
        imbalance = (bid_volume - ask_volume) / total
        return np.clip(imbalance, -1.0, 1.0)
    
    def compute_momentum(self, prices: np.ndarray) -> float:
        """
        Compute momentum signal from recent price action
        
        Args:
            prices: Array of recent prices
        
        Returns:
            Momentum value
        """
        if prices is None or len(prices) < 2:
            return 0.0
        
        # Use last N bars for momentum
        window = min(self.momentum_window, len(prices))
        if window < 2:
            return 0.0
        
        recent_prices = prices[-window:]
        returns = np.diff(recent_prices) / recent_prices[:-1]
        
        # Momentum = sum of returns (trend strength)
        momentum = np.sum(returns)
        
        return np.clip(momentum, -1.0, 1.0)
    
    def build_state_representation(self, market_data: Dict) -> np.ndarray:
        """
        Build recurrent state from market data
        
        Args:
            market_data: Dictionary with market information
        
        Returns:
            State vector for policy network
        """
        state = np.zeros(self.state_size)
        
        # Price momentum (slot 0-4)
        if 'prices' in market_data:
            momentum = self.compute_momentum(market_data['prices'])
            state[0] = momentum
        
        # Order imbalance (slot 5-9)
        if 'bid_volume' in market_data and 'ask_volume' in market_data:
            imbalance = self.compute_order_imbalance(
                market_data['bid_volume'],
                market_data['ask_volume']
            )
            state[1] = imbalance
        
        # Hawkes intensity (slot 10-14)
        if 'hawkes_intensity' in market_data:
            hawkes = market_data['hawkes_intensity']
            hawkes_normalized = np.tanh(hawkes)  # Normalize to [-1, 1]
            state[2] = hawkes_normalized
        
        # Position tracking (slot 15-19)
        state[3] = np.tanh(self.position)  # Normalized position
        state[4] = np.tanh(self.cumulative_advantage)  # Advantage estimate
        
        # Pad remaining slots if needed
        for i in range(min(5, self.state_size - 5)):
            if i < len(self.rolling_state_buffer):
                state[5 + i] = self.rolling_state_buffer[-i-1]
        
        return state
    
    def compute_policy_action(self, state: np.ndarray) -> Tuple[str, float]:
        """
        Compute action using PPO-inspired policy
        
        Args:
            state: Current state vector
        
        Returns:
            Tuple of (action_type, action_size)
        """
        if state is None or len(state) == 0:
            return 'HOLD', 0.0
        
        # Extract key signals
        momentum = state[0]
        imbalance = state[1]
        hawkes = state[2]
        position = state[3]
        
        # Policy decision logic
        # Buy condition: positive momentum + buy imbalance + no excessive position
        buy_score = (
            max(0, momentum * 0.4) +
            max(0, imbalance * 0.3) +
            max(0, hawkes * 0.2) -
            max(0, position * 0.5)  # Penalize long positions
        )
        
        # Sell condition: negative momentum + sell imbalance
        sell_score = (
            max(0, -momentum * 0.4) +
            max(0, -imbalance * 0.3) +
            max(0, hawkes * 0.2) +
            max(0, position * 0.5)  # Penalize short positions
        )
        
        # Hold condition
        hold_threshold = 0.1
        
        if buy_score > hold_threshold and buy_score > sell_score:
            action_size = min(buy_score * Settings.risk.position_size_usd, 
                            Settings.risk.position_size_usd * 0.5)
            return 'BUY', action_size
        
        elif sell_score > hold_threshold and sell_score > buy_score:
            action_size = min(sell_score * Settings.risk.position_size_usd,
                            Settings.risk.position_size_usd * 0.5)
            return 'SELL', action_size
        
        else:
            return 'HOLD', 0.0
    
    def should_take_action(self, regime_state: int, current_time: float) -> bool:
        """Check if conditions warrant directional trading"""
        # Only trade in State-1 trending regime
        if regime_state != 1:
            return False
        
        # Close positions if held too long
        if self.position != 0 and (current_time - self.entry_time) > self.max_holdtime_seconds:
            return True
        
        return True
    
    def update_position(self, action: str, size: float, price: float, current_time: float) -> None:
        """Update position from executed action"""
        if action == 'BUY':
            self.position += size
            if self.entry_price == 0:
                self.entry_price = price
            self.entry_time = current_time
        
        elif action == 'SELL':
            self.position -= size
            if self.entry_price == 0:
                self.entry_price = price
            self.entry_time = current_time
        
        elif action == 'HOLD':
            pass
    
    def compute_reward(self, current_price: float, realized_pnl: float) -> float:
        """
        Compute reward signal for PPO update
        Based on Sharpe ratio and drawdown penalty
        
        Args:
            current_price: Current asset price
            realized_pnl: Realized profit/loss from closed positions
        
        Returns:
            Reward signal
        """
        if self.position == 0:
            return realized_pnl
        
        # Unrealized P&L
        unrealized_pnl = self.position * (current_price - self.entry_price)
        
        # Track max/min for drawdown
        self.max_pnl = max(self.max_pnl, unrealized_pnl)
        self.min_pnl = min(self.min_pnl, unrealized_pnl)
        
        # Drawdown penalty
        if self.max_pnl > 0:
            drawdown = (self.max_pnl - unrealized_pnl) / self.max_pnl
        else:
            drawdown = 0.0
        
        # Reward = P&L - drawdown penalty
        reward = realized_pnl + unrealized_pnl - (drawdown ** 2) * Settings.risk.position_size_usd
        
        return reward
    
    def ppo_update(self, states: List[np.ndarray], actions: List[str], 
                  rewards: List[float]) -> float:
        """
        Execute PPO-inspired policy update with advantage estimation
        
        Args:
            states: List of state vectors
            actions: List of actions taken
            rewards: List of rewards received
        
        Returns:
            Average policy gradient
        """
        if len(states) < 2 or len(rewards) < 2:
            return 0.0
        
        # Compute returns (cumulative discounted rewards)
        gamma = Settings.ppo.gamma
        returns = np.zeros(len(rewards))
        cumulative_return = 0.0
        
        for i in range(len(rewards) - 1, -1, -1):
            cumulative_return = rewards[i] + gamma * cumulative_return
            returns[i] = cumulative_return
        
        # Compute advantages (return - baseline)
        advantages = returns - self.value_baseline
        
        # Update value baseline
        self.value_baseline = 0.9 * self.value_baseline + 0.1 * np.mean(returns)
        
        # Compute policy gradient
        policy_gradient = np.mean(advantages)
        
        self.policy_gradient_accumulator += policy_gradient
        self.update_counter += 1
        
        logger.debug(f"PPO update: gradient={policy_gradient:.6f}, value_baseline={self.value_baseline:.6f}")
        
        return policy_gradient
    
    def close_position(self, current_price: float) -> Optional[Dict]:
        """Close current position if one exists"""
        if self.position == 0:
            return None
        
        realized_pnl = self.position * (current_price - self.entry_price)
        
        order = {
            'type': 'SELL' if self.position > 0 else 'BUY',
            'volume': abs(self.position),
            'price': current_price,
            'realized_pnl': realized_pnl,
        }
        
        self.position = 0.0
        self.entry_price = 0.0
        self.max_pnl = 0.0
        self.min_pnl = 0.0
        
        return order
    
    def get_state_metrics(self) -> Dict:
        """Get current agent state metrics"""
        return {
            'current_position': float(self.position),
            'entry_price': float(self.entry_price),
            'max_pnl': float(self.max_pnl),
            'min_pnl': float(self.min_pnl),
            'value_baseline': float(self.value_baseline),
            'policy_gradient_accum': float(self.policy_gradient_accumulator),
            'update_counter': int(self.update_counter),
        }
