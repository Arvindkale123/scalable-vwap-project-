# System Architecture and Design

## Overview

This document describes the technical architecture of the data engineering pipeline, including component design, data flow, and design decisions for scalability and reliability.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│              DOCKER NETWORK                         │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌────────┐ │
│  │ FastAPI API  │   │ ETL Pipeline │   │Postgres│ │
│  │  (port 8000) │──→│  (processor) │──→│(5432)  │ │
│  └──────────────┘   └──────────────┘   └────────┘ │
│                                                     │
│  • Generates data    • Validates      • Stores     │
│  • 5% faults        • Transforms      • Indexes    │
│  • Stateless        • Quality checks  • ACID       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## Component Details

### 1. API Server (src/api_server.py)

**Purpose**: Simulate a production financial data API

**Functionality**:
- FastAPI application serving REST endpoints
- Generates synthetic market data for 5 instruments
- Implements health check for monitoring
- Injects faults intentionally for testing

**Endpoints**:
- `GET /health` - Health status check
- `GET /v1/market-data` - Market data endpoint

**Fault Injection**:
- 5% of requests return HTTP 500 error
- 5% of requests return malformed data (validation test)
- Tests pipeline resilience

**Key Code Sections**:
```python
# API response generation
- Instruments: AAPL, GOOGL, BTC-USD, ETH-USD, MSFT
- Data format: {instrument_id, price, volume, timestamp}
- 5% error injection with random selection
```

### 2. ETL Pipeline (src/etl_pipeline.py)

**Purpose**: Process raw data through transformation pipeline

**Pipeline Stages**:

#### Extraction
- Polls API at configured URL
- Handles network timeouts (10 second timeout)
- Catches connection errors gracefully
- Retry logic for transient failures

#### Validation
- Pydantic schema validation
- Type checking: instrument_id (str), price (float), volume (float), timestamp (ISO string)
- Rejects malformed records
- Logs validation failures

#### Transformation
- **VWAP Calculation**: 
  - Formula: VWAP = Σ(price × volume) / Σ(volume)
  - Computed per instrument across batch
  - Example: If AAPL has price=$150 with volume 1M, and price=$155 with volume 2M:
    - VWAP = (150×1M + 155×2M) / (1M + 2M) = $153.33

- **Outlier Detection**:
  - Flags records where price deviates >15% from VWAP
  - Formula: deviation = |price - vwap| / vwap
  - Example: VWAP=$100, price=$120 → deviation=20% → OUTLIER

#### Loading
- Inserts into PostgreSQL
- Uses UNIQUE constraint on (instrument_id, timestamp)
- ON CONFLICT DO NOTHING for duplicate prevention
- Atomic transaction for data consistency

**Quality Control Metrics**:
- Records Processed: Total input records
- Records Dropped: Failed validation
- Records Loaded: Successfully inserted
- Outliers Detected: >15% deviation count
- Execution Time: Pipeline duration in seconds

### 3. PostgreSQL Database

**Purpose**: Persistent data storage with query capabilities

**Schema**:
```sql
CREATE TABLE market_data (
    id SERIAL PRIMARY KEY,
    instrument_id VARCHAR(50) NOT NULL,
    price FLOAT NOT NULL,
    volume FLOAT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    vwap FLOAT,
    is_outlier BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instrument_id, timestamp)
);

CREATE INDEX idx_instrument_timestamp 
ON market_data(instrument_id, timestamp);
```

**Constraints**:
- UNIQUE (instrument_id, timestamp): Prevents duplicates
- Foreign key integrity (if future relations added)
- NOT NULL for critical fields

**Indexes**:
- Composite index on (instrument_id, timestamp) for query optimization

## Data Flow

### Complete Processing Pipeline

```
1. API Request
   ↓
2. Network Call to FastAPI
   ├─ Success: Return JSON
   ├─ Timeout: Handle and retry
   └─ Error: Log and continue

3. Schema Validation
   ├─ Valid: Extract record
   ├─ Invalid: Log and drop
   └─ Malformed: Record metric

4. Batch Processing
   ├─ Group by instrument_id
   └─ Calculate VWAP per group

5. Outlier Detection
   ├─ Compare price vs VWAP
   ├─ Mark if >15% deviation
   └─ Attach outlier flag

6. Database Insert
   ├─ Prepare INSERT statement
   ├─ ON CONFLICT DO NOTHING
   ├─ Transaction commit
   └─ Log success/failure

7. Metrics Reporting
   ├─ Records processed
   ├─ Records dropped
   ├─ Records loaded
   ├─ Outliers found
   └─ Execution time
```

## Error Handling Strategy

### At Each Stage

**Extraction**:
- Network timeout: Log warning, return None
- Connection error: Log error, abort pipeline
- Invalid JSON: Log error, skip record

**Validation**:
- Type mismatch: Log validation error, drop record
- Missing fields: Log error, drop record
- Value out of range: Log warning, include record

**Transformation**:
- Division by zero (VWAP): Handle gracefully
- Missing data: Use safe defaults
- Calculation error: Log and skip

**Loading**:
- Duplicate detected: Silently ignore (ON CONFLICT DO NOTHING)
- Database error: Rollback transaction, retry
- Connection lost: Log error, fail gracefully

### Logging

All events logged with timestamps:
```
2024-05-18 10:31:02,123 - INFO - Extracting data from API...
2024-05-18 10:31:02,456 - INFO - Successfully extracted 5 records
2024-05-18 10:31:02,789 - WARNING - Record 2 failed validation: value is not a valid float
2024-05-18 10:31:03,012 - INFO - Validation complete: 4 valid, 1 invalid
...
```

## Design Questions

### Question 1: Scaling to 1 Billion Events Per Day

**Current Bottleneck**: 
- Single pipeline polling sequentially
- 1B events/day = ~11,500 events/second
- Current throughput: ~100 events/second

**Recommended Architecture for 1B/day**:

```
API Source
    ↓
Kafka Cluster (message queue)
├─ 100 partitions
├─ 24-hour retention
└─ High throughput ingestion
    ↓
Apache Spark Cluster
├─ Structured Streaming mode
├─ 50+ executor nodes
├─ Micro-batch processing (1-5 sec intervals)
└─ Parallel processing: 40K-100K events/sec
    ↓
Delta Lake (ACID data warehouse)
├─ Medallion architecture
│  ├─ Bronze: Raw data
│  ├─ Silver: Validated, deduplicated
│  └─ Gold: Aggregated, analytics-ready
├─ Schema enforcement
├─ Time travel capability
└─ Data versioning
    ↓
Analytics & BI Tools
├─ ClickHouse (real-time analytics)
├─ Databricks (data science)
└─ Tableau/Grafana (dashboards)
```

**Key Components**:
- **Kafka**: Decouples ingestion from processing, enables replay
- **Spark**: Distributed processing with fault tolerance
- **Delta Lake**: ACID transactions, schema governance
- **Cloud Infrastructure**: Auto-scaling, cost optimization

**Expected Performance**:
- Throughput: 100K+ events/second
- Latency: 5-30 seconds end-to-end
- Scalability: Add executors for increased load
- Cost: $500-2000/day on cloud

**Implementation Timeline**: 2-3 weeks for production setup

### Question 2: Health Check Implementation

**Production Monitoring Strategy**:

#### Level 1: Container Health
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3
CMD curl -f http://localhost:8000/health || exit 1
```

#### Level 2: Application Metrics
```python
from prometheus_client import Counter, Histogram

records_processed = Counter(
    'etl_records_processed_total',
    'Total records processed'
)

processing_time = Histogram(
    'etl_processing_seconds',
    'Processing time in seconds'
)
```

#### Level 3: Data Quality Checks
```sql
-- Data freshness
SELECT MAX(timestamp) as latest_time FROM market_data;
-- Alert if > 5 minutes old

-- Duplicate detection  
SELECT COUNT(*) - COUNT(DISTINCT instrument_id, timestamp) 
FROM market_data;
-- Alert if > 0

-- Null values
SELECT COUNT(*) FROM market_data WHERE price IS NULL;
-- Alert if > 0
```

#### Level 4: Database Integrity
```sql
-- Check constraint violations
SELECT * FROM market_data 
WHERE price <= 0 OR volume <= 0;
-- Alert if records found
```

**Kubernetes Probes** (for production):
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  
readinessProbe:
  exec:
    command: ["python", "-c", "import psycopg2; psycopg2.connect(...)"]
  initialDelaySeconds: 5
  periodSeconds: 5
```

**Alerting Rules**:
- CPU usage > 80%
- Memory usage > 90%
- Data lag > 5 minutes
- Error rate > 1%
- Database connections > 8/10

### Question 3: Idempotency and Recovery

**Design Principle**: Safe retry with no duplicate or partial data

**Mechanism 1: Database Constraints**
```sql
UNIQUE(instrument_id, timestamp)
INSERT ... ON CONFLICT DO NOTHING
```

**Example Scenario**:
```
Run 1: Insert AAPL@2024-05-18T10:30:45Z
   └─ Success: 1 row inserted

Retry (same input):
   └─ UNIQUE constraint triggers
   └─ ON CONFLICT DO NOTHING
   └─ 0 rows inserted
   └─ No duplicate created

Result: IDEMPOTENT - safe to retry ✓
```

**Mechanism 2: Transactional Atomicity**
```python
try:
    cursor.execute(insert_sql)
    db_conn.commit()  # All or nothing
except Exception:
    db_conn.rollback()  # Entire batch reverted
    retry_with_backoff()
```

**Mechanism 3: Checkpoint-Based Recovery** (Advanced)
```python
class Checkpoint:
    def save(self, last_offset, processed_ids):
        # Save state to disk
        json.dump({
            'offset': last_offset,
            'processed': processed_ids,
            'timestamp': datetime.now().isoformat()
        }, checkpoint_file)
    
    def load(self):
        # Resume from last checkpoint
        return json.load(checkpoint_file)
```

**Recovery Process**:
1. Detect failure at any stage
2. Identify last successfully processed record
3. Retry failed batch
4. Database rejects duplicates automatically
5. Resume processing from checkpoint
6. No partial data ever visible

## Deployment Considerations

### Development (Current)
- Single Docker Compose file
- All services on local network
- SQLite or local PostgreSQL
- Manual scaling

### Production
- Kubernetes clusters
- Multiple replicas of each service
- Managed database services
- Auto-scaling policies
- Load balancing
- Monitoring and alerting

### Performance Targets

Current implementation (local):
- Records processed: 5-10/second
- API latency: <20ms
- Database insert: ~50 records/second
- Full pipeline: <1 second

Production targets (distributed):
- Records processed: 100K/second
- API latency: <50ms
- Database insert: 10K+/second
- End-to-end latency: 5-30 seconds

## Future Enhancements

1. **Real-time Streaming**: Kafka + Spark Streaming
2. **Machine Learning**: Anomaly detection models
3. **Data Warehouse**: Star schema with fact/dimension tables
4. **Visualization**: Grafana dashboards
5. **Data Lineage**: Tracking full data provenance
6. **Version Control**: Dataset versioning capability
7. **Cost Optimization**: Reserved instances, spot pricing
8. **Disaster Recovery**: Multi-region replication

## Technology Choices Rationale

| Component | Choice | Reason |
|-----------|--------|--------|
| API Framework | FastAPI | Modern, fast, async support |
| Validation | Pydantic | Type safety, error clarity |
| Database | PostgreSQL | ACID, reliability, mature |
| Containerization | Docker | Portability, reproducibility |
| Orchestration | Docker Compose | Simple, single-machine deployment |

## References

- Docker Documentation: https://docs.docker.com/
- PostgreSQL Best Practices: https://wiki.postgresql.org/wiki/Performance_Optimization
- FastAPI Design: https://fastapi.tiangolo.com/deployment/
- ETL Patterns: https://www.talend.com/resources/ebook/top-etl-patterns/
