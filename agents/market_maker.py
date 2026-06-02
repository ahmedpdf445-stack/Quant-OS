"""
High-Frequency Market Making Agent
Operates on State-0 (Mean-Reverting) regimes with tight Bid/Ask spreads
Dynamically adjusts spread based on Hawkes intensity and order book skew
"""

import numpy as np
import asyncio
from typing import Dict, List, Tuple, Optional
import logging
from config.settings import Settings

logger = logging.getLogger(__name__)


class MarketMakerAgent:
    """Multi-leg market-making agent for State-0 mean-reverting regimes"""
    
    def __init__(self):
        self.base_spread_bps = Settings.market_maker.base_spread_bps
        self.max_spread_bps = Settings.market_maker.max_spread_bps
        self.min_spread_bps = Settings.market_maker.min_spread_bps
        self.volume_skew_threshold = Settings.market_maker.volume_skew_threshold
        self.hawkes_multiplier = Settings.market_maker.hawkes_intensity_multiplier
        self.rebalance_interval = Settings.market_maker.rebalance_interval_seconds
        self.max_orders_per_leg = Settings.market_maker.max_orders_per_leg
        
        # State tracking
        self.active_orders = []
        self.bid_orders = {}
        self.ask_orders = {}
        self.position = 0.0
        self.entry_prices = []
        self.pnl = 0.0
        self.last_rebalance_time = 0.0
        
        logger.info("MarketMakerAgent initialized")
    
    def compute_dynamic_spread(self, mid_price: float, hawkes_intensity: float,
                               bid_volume: float, ask_volume: float) -> Tuple[float, float]:
        """
        Dynamically compute Bid/Ask spread based on market conditions
        
        Args:
            mid_price: Current mid-price
            hawkes_intensity: Order flow self-excitation intensity
            bid_volume: Level-1 bid volume
            ask_volume: Level-1 ask volume
        
        Returns:
            Tuple of (bid_price, ask_price)
        """
        # Defensive checks
        if mid_price <= 0 or hawkes_intensity < 0:
            return mid_price - 0.01, mid_price + 0.01
        
        # Compute volume skew
        total_volume = bid_volume + ask_volume
        if total_volume > 1e-10:
            volume_skew = (bid_volume - ask_volume) / total_volume
        else:
            volume_skew = 0.0
        
        # Base spread from configuration
        spread_bps = self.base_spread_bps
        
        # Adjust spread based on Hawkes intensity
        hawkes_adjustment = self.hawkes_multiplier * hawkes_intensity
        spread_bps *= (1.0 + hawkes_adjustment)
        
        # Adjust spread based on volume imbalance
        if abs(volume_skew) > self.volume_skew_threshold:
            spread_bps *= (1.0 + abs(volume_skew) * 0.5)
        
        # Clamp spread within boundaries
        spread_bps = np.clip(spread_bps, self.min_spread_bps, self.max_spread_bps)
        
        # Convert bps to price
        spread_price = (spread_bps / 10000.0) * mid_price
        
        # Asymmetric spread if volume skewed
        bid_spread = spread_price * (1.0 - volume_skew * 0.2)
        ask_spread = spread_price * (1.0 + volume_skew * 0.2)
        
        bid_price = mid_price - bid_spread
        ask_price = mid_price + ask_spread
        
        return bid_price, ask_price
    
    def generate_orders(self, mid_price: float, hawkes_intensity: float,
                       bid_volume: float, ask_volume: float) -> List[Dict]:
        """
        Generate market-making orders for both bid and ask sides
        
        Args:
            mid_price: Current mid-price
            hawkes_intensity: Order flow intensity
            bid_volume: Bid-side volume
            ask_volume: Ask-side volume
        
        Returns:
            List of order dictionaries
        """
        if mid_price <= 0:
            logger.warning("Invalid mid-price for order generation")
            return []
        
        # Compute dynamic spread
        bid_price, ask_price = self.compute_dynamic_spread(
            mid_price, hawkes_intensity, bid_volume, ask_volume
        )
        
        # Position-based order sizing
        position_ratio = abs(self.position) / max(Settings.risk.position_size_usd, 1e-10)
        position_ratio = min(position_ratio, 1.0)
        
        # Base order size
        order_size = Settings.risk.position_size_usd * (1.0 - position_ratio * 0.5)
        
        orders = []
        
        # Generate bid orders (staircase ladder)
        for leg in range(self.max_orders_per_leg):
            bid_leg_price = bid_price - leg * 0.001  # 0.1% spacing
            bid_leg_size = order_size / self.max_orders_per_leg
            
            orders.append({
                'type': 'BUY',
                'price': bid_leg_price,
                'volume': bid_leg_size,
                'side': 'BID',
                'leg': leg,
                'hawkes_intensity': hawkes_intensity,
            })
        
        # Generate ask orders
        for leg in range(self.max_orders_per_leg):
            ask_leg_price = ask_price + leg * 0.001
            ask_leg_size = order_size / self.max_orders_per_leg
            
            orders.append({
                'type': 'SELL',
                'price': ask_leg_price,
                'volume': ask_leg_size,
                'side': 'ASK',
                'leg': leg,
                'hawkes_intensity': hawkes_intensity,
            })
        
        logger.debug(f"Generated {len(orders)} MM orders: bid={bid_price:.6f}, ask={ask_price:.6f}")
        return orders
    
    def update_position(self, fill_data: Dict) -> None:
        """Update position tracking from fill data"""
        if not fill_data or 'volume' not in fill_data or 'price' not in fill_data:
            return
        
        volume = fill_data['volume']
        price = fill_data['price']
        order_type = fill_data.get('type', 'BUY')
        
        if order_type == 'BUY':
            self.position += volume
            self.entry_prices.append(price)
        elif order_type == 'SELL':
            self.position -= volume
            if self.position < 0:
                self.entry_prices.append(-price)
        
        # Calculate unrealized PnL
        if len(self.entry_prices) > 0:
            avg_entry = np.mean(np.abs(self.entry_prices))
            if self.position != 0:
                current_value = self.position * avg_entry
                self.pnl = current_value - (abs(self.position) * avg_entry)
    
    def should_rebalance(self, current_time: float, regime_state: int) -> bool:
        """Check if position rebalancing is needed"""
        # Only MM in State-0
        if regime_state != 0:
            return True
        
        time_elapsed = current_time - self.last_rebalance_time
        return time_elapsed >= self.rebalance_interval
    
    def cancel_orders(self) -> List[int]:
        """Cancel existing orders for rebalancing"""
        cancelled_ids = [oid for oid in self.active_orders]
        self.active_orders.clear()
        self.bid_orders.clear()
        self.ask_orders.clear()
        logger.debug(f"Cancelled {len(cancelled_ids)} orders")
        return cancelled_ids
    
    def get_risk_metrics(self) -> Dict:
        """Compute risk metrics for market maker position"""
        metrics = {
            'current_position': float(self.position),
            'position_size_usd': float(abs(self.position)),
            'unrealized_pnl': float(self.pnl),
            'max_orders_active': len(self.active_orders),
            'bid_orders_count': len(self.bid_orders),
            'ask_orders_count': len(self.ask_orders),
        }
        
        # Position limit check
        metrics['position_limit_exceeded'] = (
            abs(self.position) > Settings.risk.position_size_usd * Settings.risk.max_position_size_percentage
        )
        
        return metrics
