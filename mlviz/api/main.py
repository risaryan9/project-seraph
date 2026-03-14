"""FastAPI application for Seraph metrics API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .influx import influx_helper
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle.
    
    Connects to InfluxDB on startup and closes connection on shutdown.
    """
    logger.info("Starting Seraph API...")
    try:
        influx_helper.connect()
        logger.info("InfluxDB client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize InfluxDB: {e}")
    
    yield
    
    logger.info("Shutting down Seraph API...")
    influx_helper.close()


app = FastAPI(
    title="Seraph Metrics API",
    description="REST API for querying hardware metrics from InfluxDB",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "Seraph Metrics API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    influx_status = "connected" if influx_helper.health_check() else "disconnected"
    
    status_code = 200 if influx_status == "connected" else 503
    
    return {
        "status": "ok" if status_code == 200 else "degraded",
        "influx": influx_status
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mlviz.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
