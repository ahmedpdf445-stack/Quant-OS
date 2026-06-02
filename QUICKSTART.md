# Quick Start Guide - Sovereign-X Core OS

## 5-Minute Setup

### Prerequisites Check
```bash
python --version  # Must be 3.10+
pip --version
```

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Configure
```bash
# Edit .env with your settings
cp .env.example .env  # If provided
nano .env

# Key settings:
# MT5_LOGIN=your_account
# MT5_PASSWORD=your_password
# REDIS_HOST=127.0.0.1
```

### 3. Start Redis
```bash
# Option A: Docker (recommended)
docker run -d -p 6379:6379 redis

# Option B: Local Redis
redis-server
```

### 4. Validate Configuration
```bash
python -c "from config.settings import Settings; Settings.validate()"
```

### 5. Run Benchmark
```bash
python test_bench.py
# Takes ~2-3 minutes
# Outputs: benchmark_results.json
```

### 6. Start System (Demo Mode)
```bash
# Ensure ENABLE_LIVE_TRADING=False in .env
python main.py

# Expected output:
# ✓ Configuration validated
# ✓ Components initialized
# ✓ Numba JIT warmed up
# ✓ Redis connected
# System ready for trading
```

---

## Understanding the Output

### Regime Detection
```
Current State: 0 (Mean-Reverting)
Probability Distribution:
  - State-0: 45.2% ← Market maker active
  - State-1: 38.7% ← Directional agent active
  - State-2: 16.1% ← Risk rebalancing
```

### Order Execution (Demo Mode)
```
[Market Maker] Generated 10 orders: bid=2000.05, ask=2000.15
[Directional]  Signal: BUY 0.5 XAUUSD @ momentum=+0.35
[Risk Engine]  Portfolio rebalance: weights=[0.40, 0.35, 0.25]
```

### System Status
```
Account Balance:  $50,000.00
Active Positions: 2
Unrealized P&L:   +$234.56
Drawdown:         2.1%
Orders Today:     47
```

---

## Common Tasks

### View System Logs
```bash
tail -100 logs/sovereign_x_*.log
grep ERROR logs/*.log
```

### Check Redis Connection
```bash
redis-cli ping
# Expected: PONG

redis-cli INFO
# System statistics
```

### Query Latest Prices
```python
import redis
r = redis.Redis()
latest_tick = r.hgetall('sovereign_x:latest_tick:XAUUSD')
print(f"Bid: {latest_tick[b'bid']}, Ask: {latest_tick[b'ask']}")
```

### Reset System State
```bash
# Clear Redis cache
redis-cli FLUSHALL

# Clear logs (caution!)
rm logs/*.log

# System will rebuild state on next start
python main.py
```

### Enable Live Trading
```bash
# Edit .env
ENABLE_LIVE_TRADING=True

# Verify your risk settings first!
# MAX_LEVERAGE=5.0
# MAX_TRAILING_DRAWDOWN=0.10  (10%)

# Restart
python main.py
```

---

## Troubleshooting

### "ImportError: No module named 'MetaTrader5'"
```bash
pip install MetaTrader5
# If Windows: may require 64-bit Python
```

### "Connection refused" (Redis)
```bash
# Start Redis
redis-server

# Or Docker
docker run -d -p 6379:6379 redis

# Verify
redis-cli ping
```

### "MT5 initialization failed"
```bash
# Check MetaTrader 5 is running on your machine
# Verify credentials in .env
# Ensure server name matches: "MetaQuotes-Demo" or your broker
```

### Slow initial startup
```bash
# First run: Numba JIT compilation (~30 seconds)
# This is normal!
# Subsequent runs: <5 seconds
```

---

## Next Steps

1. **Review Configuration** → `config/settings.py`
2. **Study Architecture** → `README.md` Section II
3. **Run Benchmarks** → `python test_bench.py`
4. **Examine Core Algorithms** → `core/*.py`
5. **Deploy to Production** → See `DEPLOYMENT.md`

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | System orchestrator (start here) |
| `config/settings.py` | All configuration parameters |
| `.env` | Credentials (YOUR FILE - keep secret!) |
| `test_bench.py` | Performance benchmark |
| `core/regime_detector.py` | Market regime analysis |
| `agents/market_maker.py` | Spread harvesting |
| `agents/directional.py` | Momentum capture |

---

## Performance Indicators

Once running, watch for:

✓ **Good:**
- Regime state transitions 3-5 times per hour
- Market maker spread: 1-5 basis points
- Directional agent capture wins: >55%
- Latency: <500 microseconds end-to-end

⚠ **Warning:**
- No regime changes for >4 hours (check market)
- Spreads widening >50 bps (market stress)
- Win rate <50% (recalibrate)
- Latency >1ms (network/system issue)

🛑 **Critical:**
- Drawdown >15% → Emergency liquidation triggered
- Redis disconnected for >30s → Demo mode fallback
- Repeated MT5 connection errors → Account issue

---

## Support

**Status Page:** https://status.sovereign-x.com  
**Docs:** https://docs.sovereign-x.com  
**Email:** support@sovereign-x.com  

---

**Remember:** Always test thoroughly in demo mode before enabling live trading!

For production deployment, see `DEPLOYMENT.md`.
