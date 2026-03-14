"""FastAPI application for Seraph metrics API."""

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .influx import influx_helper
from .routes import router
from .kafka_bridge import run_kafka_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle.
    
    Connects to InfluxDB on startup, starts Kafka consumer for WebSocket,
    and closes connections on shutdown.
    """
    logger.info("Starting Seraph API...")
    
    # Initialize InfluxDB
    try:
        influx_helper.connect()
        logger.info("InfluxDB client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize InfluxDB: {e}")
    
    # Initialize WebSocket state
    app.state.ws_connections = set()
    app.state.broadcast_queue = asyncio.Queue()
    
    # Start Kafka consumer thread
    broker = os.getenv("KAFKA_BROKER", "localhost:9092")
    stop_event = threading.Event()
    loop = asyncio.get_event_loop()
    
    kafka_thread = threading.Thread(
        target=run_kafka_consumer,
        args=(broker, app.state.broadcast_queue, loop, stop_event),
        daemon=True,
        name="kafka-ws-bridge"
    )
    kafka_thread.start()
    logger.info("Kafka consumer thread started for WebSocket bridge")
    
    # Start broadcast task
    async def broadcast_task():
        """Broadcast messages from queue to all connected WebSocket clients."""
        while True:
            try:
                payload = await app.state.broadcast_queue.get()
                
                disconnected = set()
                for ws in app.state.ws_connections:
                    try:
                        await ws.send_json(payload)
                    except Exception as e:
                        logger.debug(f"Failed to send to WebSocket: {e}")
                        disconnected.add(ws)
                
                for ws in disconnected:
                    app.state.ws_connections.discard(ws)
                    
            except asyncio.CancelledError:
                logger.info("Broadcast task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in broadcast task: {e}")
    
    broadcast_task_handle = asyncio.create_task(broadcast_task())
    app.state.broadcast_task = broadcast_task_handle
    logger.info("WebSocket broadcast task started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Seraph API...")
    
    # Stop Kafka consumer
    stop_event.set()
    kafka_thread.join(timeout=5)
    if kafka_thread.is_alive():
        logger.warning("Kafka consumer thread did not stop gracefully")
    else:
        logger.info("Kafka consumer thread stopped")
    
    # Cancel broadcast task
    broadcast_task_handle.cancel()
    try:
        await broadcast_task_handle
    except asyncio.CancelledError:
        pass
    logger.info("Broadcast task stopped")
    
    # Close all WebSocket connections
    for ws in list(app.state.ws_connections):
        try:
            await ws.close()
        except:
            pass
    app.state.ws_connections.clear()
    
    # Close InfluxDB
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


@app.websocket("/ws/live")
async def websocket_live_metrics(websocket: WebSocket):
    """
    WebSocket endpoint for live metrics streaming.
    
    Clients connect to this endpoint to receive real-time metric samples
    as they are produced by the workloads and consumed from Kafka.
    
    Each message is a JSON object with MetricSample fields:
    - timestamp, model_id, phase
    - cpu_percent, cpu_system, ram_mb, ram_system_pct
    - io_read_mb, io_write_mb, thread_count
    - page_faults_minor, page_faults_major, voluntary_ctx_switches
    - llc_miss_rate, throughput, phase_duration_ms
    """
    await websocket.accept()
    app.state.ws_connections.add(websocket)
    
    logger.info(f"WebSocket client connected. Total connections: {len(app.state.ws_connections)}")
    
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Live metrics stream connected"
        })
        
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        app.state.ws_connections.discard(websocket)
        logger.info(f"WebSocket client removed. Total connections: {len(app.state.ws_connections)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mlviz.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
