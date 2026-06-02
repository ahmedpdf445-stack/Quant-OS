# Performance Optimization Guide

## Latency Budget Analysis

Target: **<500 microseconds** end-to-end

```
Order Flow    :  [market tick] → [regime detection]
                  Time: 50 μs

Decision      :  [regime output] → [agent decision]
                  Time: 75 μs (MM logic) or 100 μs (DIR logic)

Routing       :  [agent signal] → [MT5 order send]
                  Time: 200 μs (network + API)

Feedback      :  [fill confirmation] → [position update]
                  Time: 125 μs

─────────────────────────────────────────────────────────────
Total         :  ~500 microseconds
```

---

## Numba JIT Optimization

### 1. Profile Bottlenecks

```python
from numba import jit, config
import time

# Enable profiling
config.DISABLE_JIT = False

@njit(parallel=True, fastmath=True, cache=True)
def compute_rolling_statistics(prices, window):
    # Function auto-timed by @njit
    ...

# First call: JIT compilation (slow)
start = time.perf_counter()
result = compute_rolling_statistics(prices, 50)
compile_time = (time.perf_counter() - start) * 1e6
print(f"JIT compilation: {compile_time} μs")

# Second call: Compiled code (fast)
start = time.perf_counter()
result = compute_rolling_statistics(prices, 50)
exec_time = (time.perf_counter() - start) * 1e6
print(f"Execution time: {exec_time} μs")
```

### 2. Enable Parallel Execution

```python
from numba import njit, prange

# Parallel GOOD for:
# - Independent loop iterations
# - Large data arrays
# - CPU-bound operations

@njit(parallel=True, fastmath=True)
def parallel_computation(data):
    result = np.zeros_like(data)
    for i in prange(len(data)):  # Parallel loop
        result[i] = expensive_calculation(data[i])
    return result

# NOT parallel for:
# - Small arrays (<1000 elements)
# - Data dependencies between iterations
# - I/O operations
```

### 3. Configure Numba for Trading

```python
# In main.py
os.environ['NUMBA_DEFAULT_NUM_THREADS'] = '8'
os.environ['NUMBA_FASTMATH'] = '1'
os.environ['NUMBA_CACHE_DIR'] = './numba_cache'

# Warmup compilation at startup
import numba
from core.regime_detector import compute_rolling_statistics
# Call function with test data to trigger JIT compilation
compute_rolling_statistics(np.random.uniform(1900, 2100, 200), 50)
```

---

## NumPy Array Optimization

### 1. Data Types

```python
# GOOD: Explicit dtype
prices = np.array([2000.1, 2000.2, 2000.3], dtype=np.float64)
times = np.array([1, 2, 3], dtype=np.int64)

# BAD: Python floats (slower)
prices = np.array([2000.1, 2000.2, 2000.3])  # Defaults to float64 but creation slower
```

### 2. Memory Layout

```python
import numpy as np

# C-contiguous (fast row iteration)
prices_c = np.ascontiguousarray(prices)

# Fortran-contiguous (fast column iteration)
prices_f = np.asfortranarray(prices)

# Check layout
print(f"C-contiguous: {prices_c.flags['C_CONTIGUOUS']}")
print(f"F-contiguous: {prices_c.flags['F_CONTIGUOUS']}")
```

### 3. Vector Operations (No Loops)

```python
# SLOW: Python loops
returns = []
for i in range(len(prices) - 1):
    returns.append(np.log(prices[i+1] / prices[i]))

# FAST: Vectorized NumPy
returns = np.log(prices[1:] / prices[:-1])  # 10-100x faster
```

### 4. In-Place Operations

```python
import numpy as np

# Creates new array (memory allocation)
result = data * 2 + 1

# In-place operations (no allocation)
result = np.zeros_like(data)
np.multiply(data, 2, out=result)
np.add(result, 1, out=result)
```

---

## Redis Optimization

### 1. Pipeline Multiple Commands

```python
import redis

r = redis.Redis()

# SLOW: Individual commands
r.hset('key1', 'field', 'value')
r.hset('key2', 'field', 'value')
r.hset('key3', 'field', 'value')

# FAST: Pipelined
pipe = r.pipeline()
pipe.hset('key1', 'field', 'value')
pipe.hset('key2', 'field', 'value')
pipe.hset('key3', 'field', 'value')
pipe.execute()  # Single round-trip
```

### 2. Use Streams Instead of Lists

```python
import redis

r = redis.Redis()

# Better for time-series data
r.xadd('market_ticks', {
    'symbol': 'XAUUSD',
    'bid': '2000.10',
    'ask': '2000.12'
})

# Consume efficiently
messages = r.xread({'market_ticks': '0'}, count=100)
```

### 3. Connection Pooling

```python
import redis

# Create connection pool (thread-safe)
pool = redis.ConnectionPool(
    host='127.0.0.1',
    port=6379,
    max_connections=10
)

r = redis.Redis(connection_pool=pool)

# Reuse connections across threads
```

---

## Algorithm Tuning

### 1. Regime Detector

```python
from config.settings import Settings

# Tradeoff: Window size vs. Responsiveness
Settings.regime_detector.window_bars = 50  # Default
# Decrease: 30 → More responsive but noisier
# Increase: 100 → Smoother but delayed

# Transition smoothing
Settings.regime_detector.transition_smoothing = 0.8  # Default
# Increase: 0.95 → Stable states, slow transitions
# Decrease: 0.5 → Rapid transitions, sensitive
```

### 2. Hawkes Process

```python
# Self-excitement coefficient
alpha = 0.6  # Default (moderate clustering)
# Increase: 0.8 → Strong clustering, wider spreads
# Decrease: 0.3 → Weak clustering, tighter spreads

# Decay rate
beta = 0.9  # Default (slower decay, longer memory)
# Increase: 1.5 → Fast decay, recent events matter
# Decrease: 0.5 → Slow decay, historical events matter
```

### 3. QAOA Depth

```python
# Circuit depth (optimization complexity)
depth = 5  # Default

# More depth = better optimization but slower
# Depth 3: Fast (~50ms), ~80% optimal
# Depth 5: Medium (~100ms), ~90% optimal
# Depth 7: Slow (~200ms), ~95% optimal

# For real-time: Use depth 3-5
```

---

## Memory Management

### 1. Monitor Memory Usage

```python
import psutil
import os

process = psutil.Process(os.getpid())
mem_info = process.memory_info()

print(f"RSS: {mem_info.rss / 1024 / 1024:.1f} MB")  # Working set
print(f"VMS: {mem_info.vms / 1024 / 1024:.1f} MB")  # Virtual memory

# Memory percent
mem_percent = process.memory_percent()
print(f"Memory: {mem_percent:.1f}%")
```

### 2. Limit Buffer Sizes

```python
from collections import deque

# Before: Unbounded list (memory leak!)
prices = []
for i in range(1000000):
    prices.append(get_price())

# After: Bounded deque
prices = deque(maxlen=10000)
for i in range(1000000):
    prices.append(get_price())  # Auto-discards old values
```

### 3. Profile Memory Allocations

```python
# Install memory_profiler
# pip install memory-profiler

# Mark function for profiling
from memory_profiler import profile

@profile
def my_trading_function():
    data = np.random.random((10000, 100))
    return np.sum(data, axis=1)

# Run with profiler
# python -m memory_profiler my_script.py
```

---

## Network Optimization

### 1. Reduce API Calls

```python
# SLOW: Query account status every tick
for tick in market_data:
    account = mt5.account_info()  # Network call
    process_tick(tick, account)

# FAST: Cache account status, update periodically
account = mt5.account_info()
for tick in market_data:
    process_tick(tick, account)
    
if tick_count % 100 == 0:  # Update every 100 ticks
    account = mt5.account_info()
```

### 2. Batch Order Submissions

```python
# SLOW: Individual orders
for order in orders:
    mt5.order_send(order)  # Each: 200 μs

# FASTER: Batch if possible, or async
import asyncio
tasks = [submit_order_async(order) for order in orders]
results = asyncio.gather(*tasks)
```

### 3. Use Unix Sockets for Local Redis

```python
import redis

# TCP (default)
r = redis.Redis(host='127.0.0.1', port=6379)  # ~1 ms latency

# Unix socket (faster)
r = redis.Redis(unix_socket_path='/tmp/redis.sock')  # ~10 μs latency
```

---

## System-Level Tuning

### 1. CPU Affinity

```bash
# Pin process to specific CPU cores
taskset -c 0-7 python main.py

# View current affinity
taskset -pc $$
```

### 2. Process Priority

```bash
# Set high priority (nice level -5)
nice -n -5 python main.py

# Or dynamically
import os
os.nice(-5)
```

### 3. Network Tuning

```bash
# Disable Nagle's algorithm (reduce latency)
sudo sysctl -w net.ipv4.tcp_nodelay=1

# Increase network buffer
sudo sysctl -w net.core.rmem_max=134217728
```

---

## Benchmarking

### Measure End-to-End Latency

```python
import time
import numpy as np

latencies = []

for _ in range(1000):
    start = time.perf_counter_ns()
    
    # Process single market tick
    tick = get_market_tick()
    regimes, metrics = detector.detect(prices)
    hawkes_intensity = hawkes.get_current_intensity(time.time())
    orders = market_maker.generate_orders(mid_price, hawkes_intensity, 1000, 1000)
    
    end = time.perf_counter_ns()
    latency_us = (end - start) / 1000  # Microseconds
    latencies.append(latency_us)

print(f"Mean latency: {np.mean(latencies):.1f} μs")
print(f"P50 latency:  {np.percentile(latencies, 50):.1f} μs")
print(f"P99 latency:  {np.percentile(latencies, 99):.1f} μs")
print(f"Max latency:  {np.max(latencies):.1f} μs")
```

### Profile CPU Usage

```bash
# Install cProfile
python -m cProfile -s cumulative main.py 2>&1 | head -30

# Or use py-spy for continuous monitoring
py-spy record -o profile.svg python main.py
```

---

## Production Checklist

- [ ] Numba JIT warmup executed at startup
- [ ] All functions use @njit(cache=True)
- [ ] Buffer sizes limited (deque with maxlen)
- [ ] No Python loops over large arrays
- [ ] Redis pipeline used for batch operations
- [ ] Network calls cached where possible
- [ ] Memory usage <50% of available
- [ ] Latencies measured and logged
- [ ] CPU usage optimized (taskset/nice)
- [ ] Load tested with realistic data volume

---

**Expected Performance:** <500 μs latency, <10% CPU, <5GB memory
