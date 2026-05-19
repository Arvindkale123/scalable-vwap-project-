#!/bin/bash

# Data Engineering Assignment - Quick Start Script
# Automated setup for local development and testing

set -e

echo "=========================================="
echo "Data Engineering Assignment Setup"
echo "=========================================="
echo ""

# Check Docker installation
if ! command -v docker &> /dev/null; then
    echo "Error: Docker not found. Please install Docker Desktop."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "Error: Docker Compose not found. Please install Docker Desktop."
    exit 1
fi

echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker-compose --version)"
echo ""

# Build and start services
echo "Building Docker images..."
docker-compose build

echo ""
echo "Starting services..."
docker-compose up -d

echo ""
echo "Waiting for services to initialize..."
sleep 10

# Verify services
echo ""
echo "Checking service status..."
docker-compose ps

echo ""
echo "Testing API..."
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✓ API is healthy"
else
    echo "✗ API not responding"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Services running:"
echo "  - PostgreSQL: localhost:5432"
echo "  - API: http://localhost:8000"
echo "  - ETL Pipeline: Running"
echo ""
echo "Next steps:"
echo "  1. View logs: docker-compose logs -f"
echo "  2. Query data: docker-compose exec postgres psql -U postgres -d market_data"
echo "  3. Stop services: docker-compose down"
echo ""
