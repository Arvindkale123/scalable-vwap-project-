"""
Mock API Server - Market Data Generation

This module simulates a financial market data API that generates synthetic data
for demonstration and testing purposes. It implements intentional fault injection
to test the ETL pipeline's error handling and resilience.

Key Features:
- RESTful API endpoints for market data
- Synthetic data generation for 5 instruments
- 5% fault injection (errors and malformed data)
- Health check endpoint for monitoring
"""

import random
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uvicorn

# Configure logging with timestamps
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI application
app = FastAPI(title="Market Data API", version="1.0.0")


# Data model for type validation
class MarketData(BaseModel):
    """Schema for market data response"""
    instrument_id: str
    price: float
    volume: float
    timestamp: str


@app.get("/health")
def health_check():
    """
    Health check endpoint for monitoring and container orchestration.
    
    Returns:
        dict: Status information with timestamp
        
    Purpose:
        - Docker HEALTHCHECK uses this endpoint
        - Kubernetes liveness probes call this
        - Load balancers verify service availability
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/v1/market-data", response_model=List[MarketData])
def get_market_data():
    """
    Get current market data for all available instruments.
    
    Returns:
        List[MarketData]: Array of market data objects
        
    Raises:
        HTTPException: 500 error for 5% of requests (fault injection)
        
    Features:
        - Generates synthetic data for 5 instruments
        - Implements chaos engineering with 5% error rate
        - Can return malformed data for validation testing
        
    Data includes:
        - AAPL: Apple stock
        - GOOGL: Alphabet/Google stock
        - BTC-USD: Bitcoin price
        - ETH-USD: Ethereum price
        - MSFT: Microsoft stock
    """
    
    # List of available financial instruments
    instruments = ["AAPL", "GOOGL", "BTC-USD", "ETH-USD", "MSFT"]
    
    # ========== FAULT INJECTION: Intentional Error (5% chance) ==========
    # This simulates real-world API failures to test pipeline resilience
    if random.random() < 0.05:
        logger.warning("Injecting fault - returning HTTP 500 error")
        raise HTTPException(
            status_code=500,
            detail="API Server Error"
        )
    
    market_data = []
    base_time = datetime.utcnow()
    
    # Generate data for each instrument
    for i, instrument in enumerate(instruments):
        # Realistic price generation with small variations
        # Each instrument has different base price range
        if "USD" in instrument:
            # Cryptocurrency: higher prices
            base_price = random.uniform(20000, 50000)
        else:
            # Stocks: lower prices
            base_price = random.uniform(50, 500)
        
        # Add realistic market fluctuation
        price = base_price + random.uniform(-5, 5)
        
        # Generate trading volume
        volume = random.uniform(1000, 1000000)
        
        # Sequential timestamp (each instrument offset by 1 second)
        timestamp = (base_time + timedelta(seconds=i)).isoformat() + "Z"
        
        # ========== FAULT INJECTION: Malformed Data (5% chance) ==========
        # For 5% of records, return invalid data type to test validation
        if random.random() < 0.05:
            logger.warning(f"Injecting malformed data for {instrument}")
            # Return string price instead of float - will fail validation
            market_data.append({
                "instrument_id": instrument,
                "price": "INVALID_PRICE",  # This will be caught by validation
                "volume": volume,
                "timestamp": timestamp
            })
        else:
            # Normal case: return valid data
            market_data.append({
                "instrument_id": instrument,
                "price": price,
                "volume": volume,
                "timestamp": timestamp
            })
    
    return market_data


# Application startup configuration
if __name__ == "__main__":
    # Start Uvicorn server
    # Host 0.0.0.0: Listen on all network interfaces (needed for Docker)
    # Port 8000: Default FastAPI port
    # Reload: Hot reload on code changes (development only)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
