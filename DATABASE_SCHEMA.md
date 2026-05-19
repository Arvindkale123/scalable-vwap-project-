# Database Schema and Design

## Overview

This document describes the PostgreSQL database structure, tables, relationships, and query examples.

## Database: market_data

### Connection Details

```
Host: localhost (or 'postgres' within Docker network)
Port: 5432
Username: postgres
Password: postgres
Database: market_data
```

### Connection String

```
postgresql://postgres:postgres@postgres:5432/market_data
```

## Tables

### market_data

Stores processed financial market data with quality metrics.

#### Schema Definition

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

#### Column Descriptions

| Column | Type | Description | Constraints |
|--------|------|-------------|-------------|
| id | SERIAL | Auto-incrementing primary key | PRIMARY KEY |
| instrument_id | VARCHAR(50) | Financial instrument identifier (AAPL, GOOGL, etc.) | NOT NULL |
| price | FLOAT | Market price in USD | NOT NULL |
| volume | FLOAT | Trading volume in units | NOT NULL |
| timestamp | TIMESTAMP | Time of data point (ISO 8601) | NOT NULL |
| vwap | FLOAT | Volume Weighted Average Price | NULL allowed |
| is_outlier | BOOLEAN | Flag if price deviates >15% from VWAP | DEFAULT FALSE |
| created_at | TIMESTAMP | Record insertion time | DEFAULT CURRENT_TIMESTAMP |

#### Constraints

**Primary Key**: 
- Column: id
- Auto-incrementing integer
- Uniquely identifies each record

**Unique Constraint**:
- Columns: instrument_id, timestamp
- Prevents duplicate data for same instrument at same time
- Used with ON CONFLICT DO NOTHING for idempotency

**Default Values**:
- is_outlier: FALSE (assume normal unless flagged)
- created_at: CURRENT_TIMESTAMP (automatic insertion time)

#### Indexes

**Composite Index**:
```sql
CREATE INDEX idx_instrument_timestamp 
ON market_data(instrument_id, timestamp);
```

**Purpose**:
- Speeds up queries filtering by instrument and time
- Improves JOIN performance
- Reduces full table scans

**Size**: ~1KB per 1000 records

## Data Types

### VARCHAR(50)
- Variable length text up to 50 characters
- Used for instrument_id (AAPL, GOOGL, BTC-USD, etc.)
- Efficient for short strings

### FLOAT
- IEEE 754 double precision floating point
- Used for price and volume
- Range: ±1.7e±308 with 15 decimal digits precision
- Sufficient for financial data

### TIMESTAMP
- Date and time with timezone support
- Used for data timestamps and audit trail
- Format: YYYY-MM-DD HH:MM:SS.sss

### BOOLEAN
- True/False (1/0)
- Used for outlier flag
- Efficient storage (1 byte)

### SERIAL
- Auto-incrementing integer
- Used for primary key
- Starts at 1, increments by 1

## Relationships

Currently no foreign keys (normalized design with single table).

**Future Enhancements**:
```sql
CREATE TABLE instruments (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) UNIQUE,
    name VARCHAR(100),
    market VARCHAR(20)
);

ALTER TABLE market_data
ADD COLUMN instrument_fk INTEGER REFERENCES instruments(id);
```

## Data Dictionary

### instrument_id Values

| Code | Description |
|------|-------------|
| AAPL | Apple Inc. - Stock |
| GOOGL | Alphabet Inc. - Stock |
| BTC-USD | Bitcoin - Cryptocurrency |
| ETH-USD | Ethereum - Cryptocurrency |
| MSFT | Microsoft Corp. - Stock |

### price Range

- Stocks: $50 - $50,000
- Cryptocurrencies: $10,000 - $50,000
- Realistic market fluctuations applied

### volume Range

- Minimum: 1,000 units
- Maximum: 1,000,000 units
- Varies by instrument and market conditions

## Sample Data

### Example Record

```sql
INSERT INTO market_data 
  (instrument_id, price, volume, timestamp, vwap, is_outlier)
VALUES 
  ('AAPL', 154.32, 2500000, '2024-05-18 10:30:45', 153.33, false);
```

| Field | Value |
|-------|-------|
| id | 1 |
| instrument_id | AAPL |
| price | 154.32 |
| volume | 2500000 |
| timestamp | 2024-05-18 10:30:45+00 |
| vwap | 153.33 |
| is_outlier | false |
| created_at | 2024-05-18 10:31:02+00 |

## Querying Examples

### Basic Queries

**View all records**:
```sql
SELECT * FROM market_data;
```

**Count total records**:
```sql
SELECT COUNT(*) as total_records FROM market_data;
```

**Count by instrument**:
```sql
SELECT 
  instrument_id, 
  COUNT(*) as record_count
FROM market_data
GROUP BY instrument_id
ORDER BY record_count DESC;
```

### Analytical Queries

**VWAP Summary by Instrument**:
```sql
SELECT 
  instrument_id,
  ROUND(AVG(price)::numeric, 2) as avg_price,
  ROUND(AVG(vwap)::numeric, 2) as avg_vwap,
  MIN(price) as min_price,
  MAX(price) as max_price,
  COUNT(*) as samples
FROM market_data
GROUP BY instrument_id
ORDER BY avg_price DESC;
```

Expected output:
```
 instrument_id | avg_price | avg_vwap | min_price | max_price | samples
---------------+-----------+----------+-----------+-----------+---------
 BTC-USD       |  42500.50 |  42480.25|  40000.00 |  45000.00 |      10
 GOOGL         |   2800.15 |   2795.30|   2750.00 |   2850.00 |      15
 AAPL          |    154.32 |    153.33|    150.00 |    160.00 |      12
 MSFT          |    310.45 |    309.20|    300.00 |    320.00 |       8
 ETH-USD       |   1900.25 |   1895.50|   1850.00 |   1950.00 |       5
```

**Outlier Analysis**:
```sql
SELECT 
  instrument_id,
  COUNT(*) as total,
  SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) as outlier_count,
  ROUND(
    100.0 * SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) / COUNT(*),
    2
  ) as outlier_percentage
FROM market_data
GROUP BY instrument_id
ORDER BY outlier_percentage DESC;
```

**Time Series Analysis**:
```sql
SELECT 
  instrument_id,
  DATE_TRUNC('hour', timestamp) as hour,
  COUNT(*) as samples_per_hour,
  ROUND(AVG(price)::numeric, 2) as hourly_avg_price
FROM market_data
GROUP BY instrument_id, DATE_TRUNC('hour', timestamp)
ORDER BY instrument_id, hour DESC;
```

**Price Volatility** (Standard Deviation):
```sql
SELECT 
  instrument_id,
  ROUND(AVG(price)::numeric, 2) as avg_price,
  ROUND(STDDEV(price)::numeric, 2) as price_stddev,
  ROUND((STDDEV(price) / AVG(price) * 100)::numeric, 2) as volatility_pct
FROM market_data
GROUP BY instrument_id;
```

### Filtering Queries

**Get outliers**:
```sql
SELECT * FROM market_data WHERE is_outlier = true;
```

**Records from last hour**:
```sql
SELECT * FROM market_data 
WHERE timestamp > NOW() - INTERVAL '1 hour'
ORDER BY timestamp DESC;
```

**Specific instrument**:
```sql
SELECT * FROM market_data 
WHERE instrument_id = 'AAPL'
ORDER BY timestamp DESC
LIMIT 10;
```

**Price range**:
```sql
SELECT * FROM market_data 
WHERE price BETWEEN 150 AND 200
AND instrument_id IN ('AAPL', 'MSFT');
```

## Performance Considerations

### Index Usage

The composite index on (instrument_id, timestamp) improves:

```sql
-- Query 1: Uses index
SELECT * FROM market_data 
WHERE instrument_id = 'AAPL' 
AND timestamp > '2024-05-18 10:00:00';

-- Query 2: Uses index partially
SELECT * FROM market_data 
WHERE instrument_id = 'AAPL';

-- Query 3: Full table scan (no index)
SELECT * FROM market_data 
WHERE price > 100;
```

### Query Optimization

**Without index** (full table scan):
- Time: O(n) - scan all records
- Example: 10,000 records = 10,000 comparisons

**With index** (index scan):
- Time: O(log n) - binary search on index
- Example: 10,000 records = ~13 comparisons

**Estimated improvement**: 1000x faster for 1M records

## Data Integrity

### ACID Properties

**Atomicity**: Transactions all-or-nothing
- INSERT succeeds completely or not at all
- No partial data

**Consistency**: Data constraints enforced
- UNIQUE prevents duplicates
- NOT NULL enforces required fields

**Isolation**: Concurrent requests independent
- Multiple ETL processes safe
- No data corruption

**Durability**: Data persisted to disk
- Survives crashes
- Persistent storage

### Constraint Enforcement

**UNIQUE Constraint**:
```sql
-- This succeeds
INSERT INTO market_data (instrument_id, price, volume, timestamp, vwap)
VALUES ('AAPL', 154.32, 2500000, '2024-05-18 10:30:45', 153.33);

-- This fails (duplicate)
INSERT INTO market_data (instrument_id, price, volume, timestamp, vwap)
VALUES ('AAPL', 155.00, 2600000, '2024-05-18 10:30:45', 154.00);

-- ON CONFLICT handles this
INSERT INTO market_data (instrument_id, price, volume, timestamp, vwap)
VALUES ('AAPL', 155.00, 2600000, '2024-05-18 10:30:45', 154.00)
ON CONFLICT (instrument_id, timestamp) DO NOTHING;
-- Result: 0 rows inserted (no error)
```

## Maintenance

### Checking Table Size

```sql
SELECT 
  schemaname,
  tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE tablename = 'market_data';
```

### Vacuuming (Cleanup)

```sql
VACUUM ANALYZE market_data;
```

### Backup

```bash
docker-compose exec postgres pg_dump -U postgres market_data > backup.sql
```

### Restore

```bash
docker-compose exec postgres psql -U postgres market_data < backup.sql
```

## Scaling Strategies

### For Current Size (1000s of records)
- Single table sufficient
- Current indexes adequate
- No partitioning needed

### For Future Scale (millions of records)

**Partitioning by time**:
```sql
CREATE TABLE market_data_2024_q1 PARTITION OF market_data
FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');

CREATE TABLE market_data_2024_q2 PARTITION OF market_data
FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');
```

**Partitioning by instrument**:
```sql
CREATE TABLE market_data_aapl PARTITION OF market_data
FOR VALUES IN ('AAPL');

CREATE TABLE market_data_googl PARTITION OF market_data
FOR VALUES IN ('GOOGL');
```

## Monitoring Queries

**Check for data quality issues**:
```sql
-- NULL values
SELECT COUNT(*) FROM market_data WHERE price IS NULL OR volume IS NULL;

-- Invalid prices
SELECT COUNT(*) FROM market_data WHERE price <= 0;

-- Data freshness
SELECT MAX(timestamp) as latest_data FROM market_data;
SELECT NOW() - MAX(timestamp) as age FROM market_data;
```

## Tools and Clients

### Command Line (psql)

```bash
docker-compose exec postgres psql -U postgres -d market_data

# Connect and execute query
docker-compose exec postgres psql -U postgres -d market_data \
  -c "SELECT COUNT(*) FROM market_data;"
```

### GUI Tools

- **pgAdmin**: Web-based PostgreSQL admin
- **DBeaver**: Full-featured database tool
- **DataGrip**: JetBrains IDE database tool
- **VS Code** with PostgreSQL extension

### Python Interface

```python
import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="market_data",
    user="postgres",
    password="postgres"
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM market_data LIMIT 5")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()
```

## References

- PostgreSQL Documentation: https://www.postgresql.org/docs/
- SQL Best Practices: https://wiki.postgresql.org/wiki/Performance_Optimization
- Indexing Guide: https://www.postgresql.org/docs/current/indexes.html
- Data Types: https://www.postgresql.org/docs/current/datatype.html
