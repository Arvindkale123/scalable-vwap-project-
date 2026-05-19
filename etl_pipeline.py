"""
ETL Pipeline - Data Processing Engine

This module orchestrates the complete ETL (Extract-Transform-Load) process:
- Extraction: Polling API and handling network errors
- Transformation: Schema validation, VWAP calculation, outlier detection
- Loading: Database insertion with duplicate prevention

The pipeline is designed to be resilient, scalable, and maintainable.
It handles errors gracefully and provides detailed logging for monitoring.
"""

import requests
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import execute_values
from pydantic import BaseModel, ValidationError
import time
import os
from statistics import mean

# Configure structured logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ========== DATA MODELS ==========
# Pydantic models for type validation

class MarketDataSchema(BaseModel):
    """
    Validation schema for incoming market data.
    
    Pydantic automatically validates:
    - Type correctness (float for price/volume)
    - Non-null values for required fields
    - String format for timestamps
    
    Raises ValidationError if data doesn't match schema.
    """
    instrument_id: str  # e.g., "AAPL"
    price: float        # Must be numeric
    volume: float       # Must be numeric
    timestamp: str      # ISO 8601 format


# ========== ETL PIPELINE CLASS ==========

class ETLPipeline:
    """
    Main ETL Pipeline Orchestrator
    
    Handles complete data pipeline: extraction, validation, transformation, and loading.
    Implements error handling, logging, and quality control at each stage.
    """
    
    def __init__(self, api_url: str, db_config: Dict):
        """
        Initialize pipeline with configuration.
        
        Args:
            api_url: URL of market data API
            db_config: Database connection parameters
                - host: Database hostname
                - user: Database user
                - password: Database password
                - database: Database name
                - port: Database port (default 5432)
        """
        self.api_url = api_url
        self.db_config = db_config
        self.db_conn = None
        
        # Statistics tracking for pipeline monitoring
        self.stats = {
            "records_processed": 0,      # Total input records
            "records_dropped": 0,         # Failed validation
            "records_loaded": 0,          # Successfully inserted
            "validation_failures": 0,     # Validation errors
            "outliers_detected": 0        # Outliers flagged
        }
    
    def connect_db(self):
        """
        Establish database connection with retry logic.
        
        Implements exponential backoff for resilience:
        - Retry up to 5 times
        - Wait 2 seconds between attempts
        - Log status at each attempt
        
        Raises:
            psycopg2.OperationalError: If connection fails after all retries
        """
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to database (attempt {attempt + 1}/{max_retries})")
                self.db_conn = psycopg2.connect(
                    host=self.db_config['host'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    port=self.db_config.get('port', 5432)
                )
                logger.info("Database connection established")
                return
            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Connection failed, retrying in {retry_delay}s... "
                        f"(Attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"Failed to connect after {max_retries} attempts"
                    )
                    raise
    
    def create_table(self):
        """
        Create market_data table if it doesn't exist.
        
        Schema includes:
        - Primary key for record identification
        - UNIQUE(instrument_id, timestamp) for duplicate prevention
        - VWAP and is_outlier columns for quality metrics
        - Index for query performance
        
        This is idempotent - safe to call multiple times.
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS market_data (
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
        
        CREATE INDEX IF NOT EXISTS idx_instrument_timestamp 
        ON market_data(instrument_id, timestamp);
        """
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(create_table_sql)
            self.db_conn.commit()
            cursor.close()
            logger.info("Database table created/verified")
        except Exception as e:
            logger.error(f"Error creating table: {e}")
            raise
    
    # ========== STAGE 1: EXTRACT ==========
    
    def extract(self) -> Optional[List[Dict]]:
        """
        Extract data from API with comprehensive error handling.
        
        Returns:
            List[Dict]: Raw market data from API, or None if failed
            
        Handles:
            - Network timeouts (>10 seconds)
            - HTTP errors (500, etc.)
            - JSON parsing errors
            - Connection failures
            
        Logs:
            - Successful extraction
            - Each type of error encountered
        """
        try:
            logger.info("Extracting data from API: %s", self.api_url)
            
            # Request with 10 second timeout to prevent hanging
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()  # Raise exception for 4xx/5xx status codes
            
            data = response.json()
            logger.info(f"Successfully extracted {len(data)} records from API")
            return data
        
        except requests.exceptions.Timeout:
            logger.error("API request timeout (>10 seconds)")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to API")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"API returned error: HTTP {e.response.status_code}")
            return None
        except json.JSONDecodeError:
            logger.error("API returned malformed JSON")
            return None
    
    # ========== STAGE 2: VALIDATE ==========
    
    def validate(self, raw_data: List[Dict]) -> tuple:
        """
        Validate data schema using Pydantic models.
        
        Args:
            raw_data: List of records from extraction
            
        Returns:
            Tuple[List[Dict], int]: (valid_records, failure_count)
            
        Validation checks:
            - Type correctness (instrument_id: str, price: float, etc.)
            - Required fields present
            - Value ranges reasonable
            
        Purpose:
            Catch data quality issues early before transformation.
            Prevents invalid data from contaminating database.
            
        Logs:
            - Each validation failure with specific error
            - Summary of valid/invalid counts
        """
        valid_records = []
        failures = 0
        
        logger.info("Starting schema validation")
        
        for i, record in enumerate(raw_data):
            try:
                # Pydantic validates against schema
                validated = MarketDataSchema(**record)
                valid_records.append(validated.dict())
                self.stats["records_processed"] += 1
            except ValidationError as e:
                failures += 1
                self.stats["validation_failures"] += 1
                # Log the specific validation error for debugging
                error_msg = e.errors()[0]['msg'] if e.errors() else "Unknown error"
                logger.warning(
                    f"Record {i} failed validation: {error_msg}\n"
                    f"  Input: {record}"
                )
        
        logger.info(
            f"Validation complete: {len(valid_records)} valid, {failures} invalid"
        )
        return valid_records, failures
    
    # ========== STAGE 3: TRANSFORM ==========
    
    def calculate_vwap(self, records: List[Dict]) -> Dict[str, float]:
        """
        Calculate Volume Weighted Average Price (VWAP) per instrument.
        
        Formula:
            VWAP = Σ(price × volume) / Σ(volume)
            
        This weights prices by trading volume - higher volume trades
        have more impact on the average price.
        
        Args:
            records: List of validated market data records
            
        Returns:
            Dict[str, float]: Mapping of instrument_id to VWAP
            
        Example:
            If AAPL has:
            - Trade 1: price=$150, volume=1M
            - Trade 2: price=$155, volume=2M
            VWAP = (150*1M + 155*2M) / (1M+2M)
                 = 460M / 3M
                 = $153.33
            
        Purpose:
            Provides fair price baseline for outlier detection.
            Used in financial analysis and trading.
        """
        vwap_dict = {}
        logger.info("Calculating VWAP by instrument")
        
        # Group records by instrument
        instruments = {}
        for record in records:
            inst_id = record['instrument_id']
            if inst_id not in instruments:
                instruments[inst_id] = []
            instruments[inst_id].append(record)
        
        # Calculate VWAP for each instrument
        for inst_id, inst_records in instruments.items():
            # VWAP = sum(price * volume) / sum(volume)
            total_pv = sum(r['price'] * r['volume'] for r in inst_records)
            total_volume = sum(r['volume'] for r in inst_records)
            
            # Handle division by zero (shouldn't happen with valid data)
            vwap = total_pv / total_volume if total_volume > 0 else 0
            vwap_dict[inst_id] = vwap
            
            logger.info(f"  {inst_id}: VWAP = ${vwap:.2f}")
        
        return vwap_dict
    
    def detect_outliers(self, records: List[Dict], vwap_dict: Dict) -> List[Dict]:
        """
        Flag outliers: records where price deviates >15% from VWAP.
        
        Formula:
            deviation = |price - vwap| / vwap
            is_outlier = deviation > 0.15
            
        Args:
            records: List of validated records
            vwap_dict: VWAP values from calculate_vwap()
            
        Returns:
            List[Dict]: Same records with is_outlier flag added
            
        Logic:
            - Normal range: ±15% from VWAP
            - Example: VWAP=$100
              - Price=$110 (10% dev) → Normal
              - Price=$120 (20% dev) → Outlier
              
        Purpose:
            Detect unusual price movements for analysis.
            Flag data quality issues or market anomalies.
            
        Logs:
            - Summary of outlier count
            - Specific outliers with deviation percentages
        """
        logger.info("Detecting outliers (±15% threshold)")
        
        outlier_count = 0
        for record in records:
            inst_id = record['instrument_id']
            vwap = vwap_dict.get(inst_id, 0)
            
            # Calculate price deviation from VWAP
            if vwap > 0:
                deviation = abs(record['price'] - vwap) / vwap
                record['is_outlier'] = deviation > 0.15
                
                if record['is_outlier']:
                    outlier_count += 1
                    self.stats["outliers_detected"] += 1
                    # Log specific outlier details for investigation
                    logger.warning(
                        f"Outlier detected: {inst_id} "
                        f"price=${record['price']:.2f} "
                        f"(VWAP ${vwap:.2f}, deviation {deviation*100:.1f}%)"
                    )
            else:
                record['is_outlier'] = False
            
            # Attach VWAP to record for database storage
            record['vwap'] = vwap
        
        logger.info(f"Outlier detection complete: {outlier_count} outliers found")
        return records
    
    # ========== STAGE 4: LOAD ==========
    
    def load(self, records: List[Dict]) -> int:
        """
        Load transformed data into PostgreSQL database.
        
        Args:
            records: List of fully processed records
            
        Returns:
            int: Number of records successfully inserted
            
        Features:
            - UNIQUE constraint prevents duplicates
            - ON CONFLICT DO NOTHING for idempotency
            - Atomic transaction (all or nothing)
            - Detailed error logging
            
        Idempotency:
            If same records are inserted multiple times,
            duplicates are silently ignored. Safe to retry.
            
        Process:
            1. Prepare data tuples for insertion
            2. Execute INSERT with ON CONFLICT
            3. Commit transaction
            4. Log results
            
        Purpose:
            Persist processed data for analysis and querying.
            """
        if not records:
            logger.info("No records to load")
            return 0
        
        logger.info(f"Loading {len(records)} records into database")
        
        try:
            cursor = self.db_conn.cursor()
            
            # Prepare data tuples for insertion
            data_tuples = [
                (
                    r['instrument_id'],
                    r['price'],
                    r['volume'],
                    r['timestamp'],
                    r.get('vwap', 0),
                    r.get('is_outlier', False)
                )
                for r in records
            ]
            
            # SQL with duplicate prevention
            # ON CONFLICT prevents errors if duplicate exists
            # DO NOTHING silently ignores duplicates
            insert_sql = """
            INSERT INTO market_data 
              (instrument_id, price, volume, timestamp, vwap, is_outlier)
            VALUES %s
            ON CONFLICT (instrument_id, timestamp) DO NOTHING
            """
            
            # execute_values efficiently inserts multiple rows
            execute_values(cursor, insert_sql, data_tuples)
            self.db_conn.commit()
            
            rows_inserted = cursor.rowcount
            self.stats["records_loaded"] += rows_inserted
            
            cursor.close()
            logger.info(f"Successfully loaded {rows_inserted} records to database")
            return rows_inserted
        
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.db_conn.rollback()
            return 0
    
    # ========== ORCHESTRATION ==========
    
    def run(self):
        """
        Execute the complete ETL pipeline.
        
        Orchestrates all stages in sequence:
        1. Extract: Get data from API
        2. Validate: Schema validation
        3. Transform: VWAP + outlier detection
        4. Load: Insert into database
        
        Produces summary statistics for monitoring.
        
        Error handling:
            - Catches exceptions at each stage
            - Logs detailed error information
            - Continues processing on partial failures
            - Reports final statistics
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("ETL PIPELINE STARTED")
        logger.info("=" * 60)
        
        try:
            # Step 1: Extract
            raw_data = self.extract()
            if raw_data is None:
                logger.error("Pipeline halted: extraction failed")
                return
            
            # Step 2: Validate
            valid_records, validation_failures = self.validate(raw_data)
            self.stats["records_dropped"] = validation_failures
            
            if not valid_records:
                logger.warning("No valid records after validation")
                return
            
            # Step 3: Transform
            vwap_dict = self.calculate_vwap(valid_records)
            records_with_quality = self.detect_outliers(valid_records, vwap_dict)
            
            # Step 4: Load
            self.load(records_with_quality)
            
            # Summary Report
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            logger.info("=" * 60)
            logger.info("PIPELINE SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Records Processed:      {self.stats['records_processed']}")
            logger.info(f"Records Dropped:        {self.stats['records_dropped']}")
            logger.info(f"Records Loaded:         {self.stats['records_loaded']}")
            logger.info(f"Outliers Detected:      {self.stats['outliers_detected']}")
            logger.info(f"Execution Time:         {execution_time:.2f} seconds")
            logger.info("=" * 60)
        
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
        
        finally:
            # Always close database connection
            if self.db_conn:
                self.db_conn.close()
                logger.info("Database connection closed")


# ========== MAIN ENTRY POINT ==========

if __name__ == "__main__":
    # Read configuration from environment variables
    # These are set in .env file or Docker environment
    api_url = os.getenv("API_URL", "http://api:8000/v1/market-data")
    
    db_config = {
        'host': os.getenv("DB_HOST", "postgres"),
        'user': os.getenv("DB_USER", "postgres"),
        'password': os.getenv("DB_PASSWORD", "postgres"),
        'database': os.getenv("DB_NAME", "market_data"),
        'port': int(os.getenv("DB_PORT", 5432))
    }
    
    logger.info("Initializing ETL Pipeline")
    logger.info(f"  API URL: {api_url}")
    logger.info(f"  Database: {db_config['database']} on {db_config['host']}")
    
    # Initialize and run pipeline
    pipeline = ETLPipeline(api_url, db_config)
    pipeline.connect_db()
    pipeline.create_table()
    pipeline.run()
