# Setup and Installation Guide

This guide walks through complete setup from fresh install to running the data pipeline.

## Prerequisites

Before starting, ensure you have:
- Docker Desktop installed and running
- Docker Compose installed
- Command line terminal access
- Minimum 4GB RAM available
- About 5-10 minutes for first-time setup

## Step-by-Step Installation

### 1. Install Docker

Visit https://www.docker.com/products/docker-desktop and download for your operating system.

**Windows/Mac**: Run the installer and follow the wizard.

**Linux**: Use package manager:
```bash
sudo apt-get install docker.io docker-compose
sudo usermod -aG docker $USER  # Avoid needing sudo
```

After installation, verify:
```bash
docker --version
docker-compose --version
```

### 2. Prepare Project Files

Navigate to the project directory:
```bash
cd path/to/data-engineering-assignment
```

Verify all files are present:
```bash
ls -la
```

You should see:
- src/ directory (contains Python code)
- config/ directory (contains Docker configurations)
- docs/ directory (contains documentation)
- docker-compose.yml
- .env file
- run.sh script

### 3. Verify Configuration

Check `.env` file contains database credentials:
```bash
cat .env
```

Expected content:
```
DB_HOST=postgres
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=market_data
```

### 4. Start Services

Choose one method:

#### Method A: Automated Script (Recommended)
```bash
bash run.sh
```

This script:
- Checks Docker is running
- Builds containers
- Starts all services
- Waits for readiness
- Runs basic verification

#### Method B: Docker Compose Direct
```bash
docker-compose -f config/docker-compose.yml up --build
```

First run downloads base images (2-3 minutes). Subsequent runs are faster.

#### Method C: Step by Step
Start each service individually:

PostgreSQL:
```bash
docker-compose -f config/docker-compose.yml up -d postgres
sleep 10  # Wait for database initialization
```

API Server:
```bash
docker-compose -f config/docker-compose.yml up -d api
```

ETL Pipeline:
```bash
docker-compose -f config/docker-compose.yml up etl
```

### 5. Verify Installation

Check all services running:
```bash
docker-compose -f config/docker-compose.yml ps
```

Expected output:
```
NAME        COMMAND                  SERVICE     STATUS
postgres    postgres                 postgres    Up 2 minutes
api         uvicorn api_server...    api         Up 1 minute
etl         python etl_pipeline.py   etl         Exited (0) 30 seconds ago
```

### 6. Test API Connectivity

Health check:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "timestamp": "2024-05-18T..."}
```

Get market data:
```bash
curl http://localhost:8000/v1/market-data | jq
```

Expected: Array of market data objects with instrument_id, price, volume, timestamp.

### 7. Verify Database

Query database:
```bash
docker-compose -f config/docker-compose.yml exec postgres psql -U postgres -d market_data \
  -c "SELECT COUNT(*) FROM market_data;"
```

Expected output shows number of records (should be 4+).

## Directory Structure Explanation

### src/
Contains the Python source code:
- `api_server.py`: FastAPI application serving synthetic market data
- `etl_pipeline.py`: ETL processing logic
- `requirements.txt`: Python package dependencies

### config/
Contains configuration files:
- `docker-compose.yml`: Docker Compose orchestration configuration
- `Dockerfile.api`: Container specifications for API service
- `Dockerfile.etl`: Container specifications for ETL service
- `.env`: Environment variables for database and API configuration

### docs/
Documentation files:
- `ARCHITECTURE.md`: System design and data flow diagrams
- `API_SPECIFICATION.md`: API endpoint documentation
- `DATABASE_SCHEMA.md`: Database table structures
- `SETUP.md`: This file

### tests/
Test files:
- `test_integration.sh`: Integration test script

## Common Tasks

### Run ETL Pipeline Again
```bash
docker-compose -f config/docker-compose.yml exec etl python src/etl_pipeline.py
```

### View Logs
All services:
```bash
docker-compose -f config/docker-compose.yml logs -f
```

Specific service:
```bash
docker-compose -f config/docker-compose.yml logs -f etl
docker-compose -f config/docker-compose.yml logs -f api
docker-compose -f config/docker-compose.yml logs -f postgres
```

### Access Database Shell
```bash
docker-compose -f config/docker-compose.yml exec postgres psql -U postgres -d market_data
```

Inside psql shell, try:
```sql
\dt                          -- List tables
SELECT * FROM market_data;   -- View all data
SELECT COUNT(*) FROM market_data;  -- Count records
\q                           -- Exit
```

### Rebuild Containers
If code changes:
```bash
docker-compose -f config/docker-compose.yml build
docker-compose -f config/docker-compose.yml up
```

### Stop Services
```bash
docker-compose -f config/docker-compose.yml down
```

Remove data too:
```bash
docker-compose -f config/docker-compose.yml down -v
```

## Troubleshooting

### Docker Daemon Not Running
**Error**: `Cannot connect to Docker daemon`

**Solution**: Start Docker Desktop application

### Port Already in Use
**Error**: `Address already in use`

**Solution**: 
```bash
docker-compose -f config/docker-compose.yml down
# Wait 5 seconds
docker-compose -f config/docker-compose.yml up
```

Or change port in docker-compose.yml:
```yaml
postgres:
  ports:
    - "5433:5432"  # Changed from 5432 to 5433
```

### Connection Refused on First Query
**Cause**: PostgreSQL needs time to initialize

**Solution**: Wait 10-15 seconds after starting before querying

### Python Module Not Found
**Error**: `ModuleNotFoundError: No module named 'fastapi'`

**Solution**: Rebuild containers:
```bash
docker-compose -f config/docker-compose.yml build --no-cache
```

### Incomplete Database Initialization
**Error**: `relation "market_data" does not exist`

**Solution**: 
1. Delete existing database volume:
```bash
docker volume ls | grep market
docker volume rm [volume_name]
```

2. Restart services:
```bash
docker-compose -f config/docker-compose.yml down -v
docker-compose -f config/docker-compose.yml up
```

## Performance Optimization

### Increase Resources
Edit docker-compose.yml to allocate more memory:
```yaml
api:
  mem_limit: 512m  # Increase from default

etl:
  mem_limit: 1g
```

### Database Performance
Create indexes for frequently queried columns:
```bash
docker-compose -f config/docker-compose.yml exec postgres psql -U postgres -d market_data \
  -c "CREATE INDEX idx_instrument ON market_data(instrument_id);"
```

### Reduce API Latency
Check network latency between services:
```bash
docker-compose -f config/docker-compose.yml exec api ping postgres
```

## Next Steps

1. Read `docs/ARCHITECTURE.md` for system design details
2. Review `docs/API_SPECIFICATION.md` for API documentation
3. Check `docs/DATABASE_SCHEMA.md` for database structure
4. Run tests with `bash tests/test_integration.sh`

## Additional Resources

- Docker documentation: https://docs.docker.com/
- FastAPI docs: https://fastapi.tiangolo.com/
- PostgreSQL docs: https://www.postgresql.org/docs/
- Pydantic validation: https://docs.pydantic.dev/
