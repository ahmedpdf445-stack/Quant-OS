# Production Deployment Guide for Sovereign-X Core OS

## Pre-Flight Checklist

### Security
- [ ] All credentials moved to `.env` file
- [ ] `.env` added to `.gitignore`
- [ ] No hardcoded passwords in source code
- [ ] SSH keys rotated
- [ ] VPN/firewall configured for API access

### Configuration
- [ ] `ENABLE_LIVE_TRADING=False` for first deployment
- [ ] `MAX_LEVERAGE` set to conservative value (5-10)
- [ ] `MAX_TRAILING_DRAWDOWN` set to 15% or lower
- [ ] `CIRCUIT_BREAKER_THRESHOLD` set to 20%
- [ ] All asset symbols verified against broker

### Infrastructure
- [ ] Redis configured with persistent storage (`appendonly.aof`)
- [ ] Redis backups scheduled daily
- [ ] Monitoring agent installed (Prometheus/Datadog)
- [ ] Alerting configured for drawdown events
- [ ] Logging to external service (CloudWatch/ELK)

### Testing
- [ ] Ran `test_bench.py` successfully
- [ ] Walked through Sharpe ratio, Drawdown, Win Rate metrics
- [ ] Verified Numba JIT compilation on target hardware
- [ ] Tested emergency liquidation procedure

---

## Docker Deployment

### Quick Start (Docker Compose)

```bash
# 1. Create docker-compose.yml in project root
cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  redis:
    image: redis:latest
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  sovereign-x:
    build: .
    depends_on:
      - redis
    environment:
      - REDIS_HOST=redis
      - ENABLE_LIVE_TRADING=False
    volumes:
      - ./logs:/app/logs
      - ./.env:/app/.env:ro
    network_mode: host
    restart: unless-stopped

volumes:
  redis_data:
EOF

# 2. Build and run
docker-compose up -d

# 3. Check logs
docker-compose logs -f sovereign-x
```

### Kubernetes Deployment

```yaml
# sovereign-x-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sovereign-x-trading
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sovereign-x
  template:
    metadata:
      labels:
        app: sovereign-x
    spec:
      containers:
      - name: sovereign-x
        image: sovereign-x:latest
        env:
        - name: REDIS_HOST
          value: "redis-service"
        - name: MT5_LOGIN
          valueFrom:
            secretKeyRef:
              name: mt5-credentials
              key: login
        - name: MT5_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mt5-credentials
              key: password
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
        livenessProbe:
          exec:
            command: ["python", "-c", "import redis; redis.Redis().ping()"]
          initialDelaySeconds: 30
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: redis-service
spec:
  selector:
    app: redis
  ports:
  - protocol: TCP
    port: 6379
    targetPort: 6379
  type: ClusterIP
```

Deploy:
```bash
kubectl apply -f sovereign-x-deployment.yaml
kubectl logs -f deployment/sovereign-x-trading
```

---

## Monitoring Setup

### Prometheus Metrics Export

Add to `main.py`:
```python
from prometheus_client import Counter, Histogram, start_http_server

# Metrics
orders_executed = Counter('sovereign_x_orders_total', 'Total orders executed')
order_latency = Histogram('sovereign_x_order_latency_us', 'Order latency in microseconds')
pnl_gauge = Gauge('sovereign_x_pnl_usd', 'Current P&L in USD')
drawdown_gauge = Gauge('sovereign_x_drawdown_pct', 'Current drawdown percentage')

# Start Prometheus endpoint
start_http_server(8000)
```

Query metrics:
```bash
curl http://localhost:8000/metrics | grep sovereign_x
```

### Datadog Integration

```python
from datadog import initialize, api
import time

options = {
    'api_key': os.getenv('DD_API_KEY'),
    'app_key': os.getenv('DD_APP_KEY')
}
initialize(**options)

# Log metrics
def log_to_datadog(metric_name, value):
    api.Metric.send(
        metric=f'sovereign_x.{metric_name}',
        points=value,
        host='trading-server-01'
    )
```

---

## Alert Configuration (CloudWatch)

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

# Create circuit breaker alarm
cloudwatch.put_metric_alarm(
    AlarmName='SovereignX-CircuitBreaker',
    ComparisonOperator='GreaterThanThreshold',
    EvaluationPeriods=1,
    MetricName='Drawdown',
    Namespace='SovereignX',
    Period=60,
    Statistic='Maximum',
    Threshold=20.0,
    ActionsEnabled=True,
    AlarmActions=['arn:aws:sns:us-east-1:123456789:emergency-alerts'],
    AlarmDescription='Alert if drawdown exceeds 20%'
)
```

---

## Performance Tuning

### CPU Optimization

```bash
# Set thread affinity for Numba
export OMP_NUM_THREADS=8
export NUMBA_NUM_THREADS=8

# Pin process to specific cores
taskset -c 0-7 python main.py
```

### Memory Optimization

```python
# In config/settings.py
TICK_BUFFER_SIZE = 5000  # Reduce from 10000 for lower memory
```

### Network Optimization

- Place Redis on same physical machine as trading system
- Use Unix sockets instead of TCP:
  ```python
  redis.Redis(unix_socket_path='/tmp/redis.sock')
  ```
- Enable TCP_NODELAY for MT5 connection

---

## Incident Response

### Emergency Liquidation Triggered

1. **Check Logs:**
   ```bash
   tail -100 logs/sovereign_x_*.log | grep -i "emergency\|circuit"
   ```

2. **Verify Account Status in MT5:**
   - Login to account
   - Review position history
   - Confirm all positions closed

3. **Post-Mortem:**
   - Export logs to analysis
   - Review which trades caused drawdown
   - Adjust risk parameters

### Redis Connection Lost

1. **Check Redis Status:**
   ```bash
   redis-cli ping
   docker-compose logs redis
   ```

2. **System Behavior:**
   - Market maker agent pauses (falls back to demo mode)
   - Directional agent continues on cached data
   - Risk engine still operates

3. **Recovery:**
   - Restart Redis: `docker-compose restart redis`
   - System auto-reconnects within 30 seconds

---

## Backup & Recovery

### Daily Backup

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/sovereign-x"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup Redis
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb "$BACKUP_DIR/redis_$DATE.rdb"

# Backup logs
tar -czf "$BACKUP_DIR/logs_$DATE.tar.gz" ./logs

# Upload to S3
aws s3 cp "$BACKUP_DIR" s3://sovereign-x-backups/ --recursive
```

Schedule via crontab:
```crontab
0 2 * * * /path/to/backup.sh
```

### Recovery Procedure

```bash
# Restore Redis from backup
cp backups/redis_20260602_020000.rdb /var/lib/redis/dump.rdb
redis-cli shutdown
redis-server

# System auto-syncs on restart
python main.py
```

---

## Scaling Strategies

### Horizontal Scaling (Multiple Instances)

Each instance handles different asset classes:

```yaml
# Instance 1: Precious Metals
TRADING_ASSETS: XAUUSD,XAGUSD

# Instance 2: Forex
TRADING_ASSETS: EURUSD,GBPUSD

# Instance 3: Crypto
TRADING_ASSETS: BTCUSD,ETHUSD
```

Share Redis for cross-asset signals.

### Vertical Scaling (Single Server)

Increase resources:
- Memory: 16GB → 32GB
- CPU cores: 8 → 16
- Network: 1Gbps → 10Gbps

---

## Compliance & Audit

### Trade Log Format

All trades recorded to audit trail:
```json
{
  "timestamp": "2026-06-02T10:30:50.123456Z",
  "order_id": 12345678,
  "asset": "XAUUSD",
  "action": "BUY",
  "volume": 0.5,
  "price": 2000.12345,
  "agent": "market_maker",
  "regime_state": 0,
  "status": "FILLED"
}
```

### Regulatory Reporting

Export daily positions:
```python
# In pipeline/mt5_gateway.py
def export_daily_positions():
    with open(f'audit/positions_{date}.csv', 'w') as f:
        f.write('timestamp,symbol,volume,entry_price,current_price,pnl\n')
        for pos in mt5.positions_get():
            f.write(f'{timestamp},{pos.symbol},{pos.volume}...\n')
```

---

## Decommissioning

If discontinuing system:

1. **Stop Trading:**
   ```bash
   docker-compose down
   ```

2. **Archive Logs & Data:**
   ```bash
   tar -czf sovereign-x-archive-2026-06.tar.gz logs/ audit/
   aws s3 cp sovereign-x-archive-2026-06.tar.gz s3://sovereign-x-archives/
   ```

3. **Destroy Credentials:**
   ```bash
   shred -vfz .env
   aws secretsmanager delete-secret --secret-id sovereign-x-mt5-credentials
   ```

4. **Final Verification:**
   - Confirm all positions closed
   - Verify account balance matches expected total
   - Document final performance statistics

---

**Last Updated:** June 2, 2026  
**Status:** Production Ready
