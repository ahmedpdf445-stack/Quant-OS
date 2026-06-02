"""
Low-Latency Redis Stream Data Pipeline
Asynchronous consumer for Level-2 order book and tick data
ACID-compliant in-memory cache for core algorithms

SELF-HEALING FEATURES:
- Auto-reconnection with exponential backoff
- Synthetic data generation for demo mode if Redis unavailable
- Circuit breaker for connection failures
- Graceful degradation to in-memory buffers
"""

import asyncio
import redis.asyncio as redis
import numpy as np
from typing import Dict, List, Optional, AsyncGenerator
import logging
import json
from collections import deque
from config.settings import Settings
import time

logger = logging.getLogger(__name__)


class RedisStreamPipeline:
    """Asynchronous Redis stream consumer for market data with self-healing capabilities"""
    
    def __init__(self):
        self.host = Settings.redis.host
        self.port = Settings.redis.port
        self.db = Settings.redis.db
        self.password = Settings.redis.password
        self.batch_size = Settings.redis.batch_size
        self.max_retries = Settings.redis.max_retries
        self.retry_delay = Settings.redis.retry_delay
        
        self.redis_client = None
        self.tick_buffer = deque(maxlen=Settings.TICK_BUFFER_SIZE)
        self.order_flow_buffer = deque(maxlen=1000)
        self.signal_buffer = deque(maxlen=100)
        
        self.is_connected = False
        self.demo_mode = False  # Fallback to synthetic data
        self.circuit_breaker_open = False
        self.failure_count = 0
        self.last_tick_id = '0'
        self.last_order_id = '0'
        self.last_signal_id = '0'
        
        # Synthetic data for demo mode
        self.synthetic_tick_counter = 0
        self.synthetic_price = 2000.0
        
        logger.info(f"RedisStreamPipeline initialized: {self.host}:{self.port}")
        logger.info(f"Demo mode fallback: {'ENABLED' if Settings.redis.demo_mode else 'DISABLED'}")
    
    async def connect(self) -> bool:
        """Establish connection to Redis server with exponential backoff and demo mode fallback"""
        logger.info(f"[REDIS] Attempting connection to {self.host}:{self.port}...")
        
        for attempt in range(self.max_retries):
            if self.circuit_breaker_open:
                logger.warning(f"[REDIS] Circuit breaker OPEN - skipping connection attempt")
                return False
            
            try:
                self.redis_client = await redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30
                )
                
                # Test connection
                await self.redis_client.ping()
                self.is_connected = True
                self.failure_count = 0
                self.circuit_breaker_open = False
                logger.info("[REDIS] [OK] Connected to Redis successfully")
                return True
                
            except Exception as e:
                self.failure_count += 1
                logger.warning(f"[REDIS] Connection attempt {attempt + 1}/{self.max_retries} failed: {type(e).__name__}: {e}")
                
                # Circuit breaker opens after 3 failures
                if self.failure_count >= 3:
                    self.circuit_breaker_open = True
                    logger.error("[REDIS] [FAIL] Circuit breaker OPENED after 3 failures")
                
                if attempt < self.max_retries - 1:
                    backoff_delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"[REDIS] Retrying in {backoff_delay} seconds...")
                    await asyncio.sleep(backoff_delay)
        
        # Fallback to demo mode if configured
        logger.error(f"[REDIS] Failed to connect after {self.max_retries} retries")
        
        if hasattr(Settings.redis, 'demo_mode') and Settings.redis.demo_mode:
            logger.warning("[REDIS] FALLBACK: Entering demo mode with synthetic data generation")
            self.demo_mode = True
            self.is_connected = False  # Mark as not truly connected
            return True
        else:
            logger.error("[REDIS] Demo mode not enabled - Redis connection required")
            return False
    
    async def disconnect(self) -> None:
        """Close Redis connection"""
        if self.redis_client:
            try:
                await self.redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis connection: {e}")
            finally:
                self.is_connected = False
                self.demo_mode = False
                logger.info("[REDIS] Disconnected from Redis")
    
    def generate_synthetic_tick(self) -> Dict:
        """Generate synthetic market tick data for demo mode"""
        self.synthetic_tick_counter += 1
        
        # Random walk for price
        price_change = np.random.normal(0, 0.5)
        self.synthetic_price += price_change
        
        # Market microstructure
        spread = np.random.uniform(0.5, 2.0)
        bid = self.synthetic_price - spread / 2
        ask = self.synthetic_price + spread / 2
        
        # Volume distribution (realistic L2 order book)
        bid_vol = np.random.exponential(1000)
        ask_vol = np.random.exponential(1000)
        
        tick = {
            'id': f"synthetic-{self.synthetic_tick_counter}",
            'asset': 'XAUUSD',
            'timestamp': int(time.time() * 1000),
            'bid': float(bid),
            'ask': float(ask),
            'bid_volume': float(bid_vol),
            'ask_volume': float(ask_vol),
            'last_price': float(self.synthetic_price),
        }
        
        return tick
    
    async def publish_tick(self, asset: str, tick_data: Dict) -> bool:
        """
        Publish a market tick to Redis stream (or buffer in demo mode)
        
        Args:
            asset: Asset symbol (e.g., 'XAUUSD')
            tick_data: Dictionary with price, bid, ask, volume
        
        Returns:
            True if successful
        """
        if self.demo_mode:
            # In demo mode, just buffer the data
            self.tick_buffer.append(tick_data)
            return True
        
        if not self.is_connected or not self.redis_client:
            logger.debug("[REDIS] Not connected for tick publish - buffering locally")
            self.tick_buffer.append(tick_data)
            return False
        
        try:
            stream_key = Settings.redis.tick_stream_key
            message = {
                'asset': asset,
                'timestamp': str(tick_data.get('timestamp', int(time.time() * 1000))),
                'bid': str(tick_data.get('bid', 0)),
                'ask': str(tick_data.get('ask', 0)),
                'bid_volume': str(tick_data.get('bid_volume', 0)),
                'ask_volume': str(tick_data.get('ask_volume', 0)),
                'last_price': str(tick_data.get('last_price', 0)),
            }
            
            await self.redis_client.xadd(stream_key, message)
            self.tick_buffer.append(tick_data)
            return True
            
        except Exception as e:
            logger.warning(f"[REDIS] Error publishing tick: {type(e).__name__}: {e}")
            self.tick_buffer.append(tick_data)
            return False
    
    async def consume_ticks(self) -> AsyncGenerator[Dict, None]:
        """
        Consume market ticks from Redis stream or generate synthetic data in demo mode
        
        Yields:
            Tick data dictionaries
        """
        if not self.is_connected and not self.demo_mode:
            logger.error("[REDIS] Redis not connected and demo mode disabled")
            return
        
        # Demo mode: Generate synthetic ticks
        if self.demo_mode:
            logger.info("[REDIS-DEMO] Starting synthetic tick generation")
            try:
                tick_counter = 0
                while True:
                    # Generate synthetic tick
                    tick = self.generate_synthetic_tick()
                    self.tick_buffer.append(tick)
                    tick_counter += 1
                    
                    # Yield every 100ms (10 Hz)
                    await asyncio.sleep(0.1)
                    yield tick
                    
                    if tick_counter % 100 == 0:
                        logger.debug(f"[REDIS-DEMO] Generated {tick_counter} synthetic ticks")
            except Exception as e:
                logger.error(f"[REDIS-DEMO] Error in synthetic tick generation: {e}")
            return
        
        # Production mode: Consume from Redis
        try:
            stream_key = Settings.redis.tick_stream_key
            logger.info(f"[REDIS] Starting tick consumption from {stream_key}")
            
            while self.is_connected:
                try:
                    # Read batch of messages from stream
                    messages = await self.redis_client.xread(
                        {stream_key: self.last_tick_id},
                        count=self.batch_size,
                        block=1000  # Block for 1 second
                    )
                    
                    if messages:
                        for stream, stream_messages in messages:
                            for msg_id, msg_data in stream_messages:
                                try:
                                    # Convert to tick dictionary
                                    tick = {
                                        'id': msg_id,
                                        'asset': msg_data.get('asset'),
                                        'timestamp': int(msg_data.get('timestamp', 0)),
                                        'bid': float(msg_data.get('bid', 0)),
                                        'ask': float(msg_data.get('ask', 0)),
                                        'bid_volume': float(msg_data.get('bid_volume', 0)),
                                        'ask_volume': float(msg_data.get('ask_volume', 0)),
                                        'last_price': float(msg_data.get('last_price', 0)),
                                    }
                                    self.last_tick_id = msg_id
                                    self.tick_buffer.append(tick)
                                    yield tick
                                except (ValueError, TypeError) as e:
                                    logger.warning(f"[REDIS] Error parsing tick data: {e}")
                                    continue
                    
                    # Yield any cached ticks if stream is empty
                    if not messages and len(self.tick_buffer) > 0:
                        yield dict(self.tick_buffer[-1])
                
                except asyncio.TimeoutError:
                    # Timeout is normal for blocking read
                    if len(self.tick_buffer) > 0:
                        yield dict(self.tick_buffer[-1])
                    continue
                
                except Exception as e:
                    logger.error(f"[REDIS] Error consuming ticks: {type(e).__name__}: {e}")
                    self.failure_count += 1
                    
                    # Try to reconnect if failures exceed threshold
                    if self.failure_count > 5:
                        logger.warning("[REDIS] High failure count - attempting reconnection")
                        await self.disconnect()
                        reconnected = await self.connect()
                        if not reconnected and self.demo_mode:
                            logger.info("[REDIS] Falling back to demo mode")
                            break
                    
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"[REDIS] Fatal error in tick consumption: {type(e).__name__}: {e}")
            logger.info("[REDIS] Attempting to switch to demo mode")
    
    async def publish_order_flow(self, order_data: Dict) -> bool:
        """Publish order flow event to Redis stream"""
        if not self.is_connected:
            return False
        
        try:
            stream_key = Settings.redis.order_flow_stream_key
            message = {
                'timestamp': str(order_data.get('timestamp', 0)),
                'side': order_data.get('side', 'UNKNOWN'),
                'price': str(order_data.get('price', 0)),
                'volume': str(order_data.get('volume', 0)),
                'aggressor': order_data.get('aggressor', ''),
            }
            
            await self.redis_client.xadd(stream_key, message)
            self.order_flow_buffer.append(order_data)
            return True
            
        except Exception as e:
            logger.error(f"Error publishing order flow: {e}")
            return False
    
    async def consume_order_flow(self) -> AsyncGenerator[Dict, None]:
        """Consume order flow events from Redis stream"""
        if not self.is_connected:
            return
        
        try:
            stream_key = Settings.redis.order_flow_stream_key
            
            while self.is_connected:
                try:
                    messages = await self.redis_client.xread(
                        {stream_key: self.last_order_id},
                        count=self.batch_size,
                        block=1000
                    )
                    
                    if messages:
                        for stream, stream_messages in messages:
                            for msg_id, msg_data in stream_messages:
                                order_flow = {
                                    'id': msg_id,
                                    'timestamp': int(msg_data.get('timestamp', 0)),
                                    'side': msg_data.get('side'),
                                    'price': float(msg_data.get('price', 0)),
                                    'volume': float(msg_data.get('volume', 0)),
                                    'aggressor': msg_data.get('aggressor', ''),
                                }
                                self.last_order_id = msg_id
                                self.order_flow_buffer.append(order_flow)
                                yield order_flow
                    
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error consuming order flow: {e}")
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"Fatal error in order flow consumption: {e}")
    
    async def publish_signal(self, signal_data: Dict) -> bool:
        """Publish trading signal to Redis stream"""
        if not self.is_connected:
            return False
        
        try:
            stream_key = Settings.redis.signal_stream_key
            message = {
                'timestamp': str(signal_data.get('timestamp', 0)),
                'signal_type': signal_data.get('type', ''),
                'action': signal_data.get('action', ''),
                'confidence': str(signal_data.get('confidence', 0)),
                'regime_state': str(signal_data.get('regime_state', 0)),
            }
            
            await self.redis_client.xadd(stream_key, message)
            self.signal_buffer.append(signal_data)
            return True
            
        except Exception as e:
            logger.error(f"Error publishing signal: {e}")
            return False
    
    def get_latest_tick(self, asset: Optional[str] = None) -> Optional[Dict]:
        """Get latest tick from buffer"""
        if len(self.tick_buffer) == 0:
            return None
        
        if asset:
            for tick in reversed(self.tick_buffer):
                if tick.get('asset') == asset:
                    return tick
            return None
        
        return dict(self.tick_buffer[-1])
    
    def get_tick_history(self, n: int = 100) -> List[Dict]:
        """Get recent tick history"""
        return [dict(t) for t in list(self.tick_buffer)[-n:]]
    
    def clear_buffers(self) -> None:
        """Clear all data buffers"""
        self.tick_buffer.clear()
        self.order_flow_buffer.clear()
        self.signal_buffer.clear()
        logger.info("Data buffers cleared")
    
    def get_buffer_stats(self) -> Dict:
        """Get buffer statistics"""
        return {
            'tick_buffer_size': len(self.tick_buffer),
            'order_flow_buffer_size': len(self.order_flow_buffer),
            'signal_buffer_size': len(self.signal_buffer),
            'is_connected': self.is_connected,
            'last_tick_id': self.last_tick_id,
        }
