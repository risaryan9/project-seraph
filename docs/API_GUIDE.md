# Seraph API Guide

Complete guide to the Seraph FastAPI backend for querying hardware metrics from InfluxDB.

## Base URL

- **Local development**: `http://localhost:8000`
- **Docker**: `http://localhost:8000`

## Interactive Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Quick Start

### 1. Start the stack

```bash
docker compose up --build
```

### 2. Wait for services to be healthy

```bash
# Check backend logs
docker compose logs -f backend

# You should see:
# Connected to InfluxDB at http://influxdb:8086
```

### 3. Test the API

```bash
# Health check
curl http://localhost:8000/health

# Get available models
curl http://localhost:8000/api/models

# Get raw metrics
curl "http://localhost:8000/api/metrics/raw?start_relative=-5m&limit=10"
```

---

## Endpoints

### Health & Status

#### `GET /`
Root endpoint with API information.

**Response:**
```json
{
  "name": "Seraph Metrics API",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "redoc": "/redoc"
}
```

#### `GET /health`
Health check endpoint.

**Response (healthy):**
```json
{
  "status": "ok",
  "influx": "connected"
}
```

**Response (degraded):**
```json
{
  "status": "degraded",
  "influx": "disconnected"
}
```

---

### Metrics Queries

#### `GET /api/metrics/raw`
Get raw time-series metrics from InfluxDB.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start_relative` | string | `-1h` | Relative time range (e.g., `-5m`, `-1h`, `-24h`). Ignored if `start` is set. |
| `start` | string | — | Absolute start time (ISO8601 or Unix ms) |
| `end` | string | — | Absolute end time (ISO8601 or Unix ms) |
| `model_id` | string | — | Filter by model (e.g., `resnet18-train`) |
| `phase` | string | — | Filter by phase (e.g., `forward`, `backward`) |
| `fields` | string | — | Comma-separated field names (e.g., `cpu_percent,ram_mb`) |
| `limit` | int | 1000 | Max number of points (1-10000) |

**Examples:**

```bash
# Last 15 minutes, all fields
curl "http://localhost:8000/api/metrics/raw?start_relative=-15m"

# Specific model and fields
curl "http://localhost:8000/api/metrics/raw?start_relative=-5m&model_id=resnet18-train&fields=cpu_percent,ram_mb&limit=100"

# Absolute time range (ISO8601)
curl "http://localhost:8000/api/metrics/raw?start=2024-03-14T00:00:00Z&end=2024-03-14T12:00:00Z"

# Absolute time range (Unix milliseconds)
curl "http://localhost:8000/api/metrics/raw?start=1710374400000&end=1710417600000"

# Filter by phase
curl "http://localhost:8000/api/metrics/raw?start_relative=-10m&model_id=resnet18-train&phase=forward"
```

**Response:**
```json
{
  "count": 150,
  "data": [
    {
      "timestamp": "2024-03-14T12:34:56.789Z",
      "model_id": "resnet18-train",
      "phase": "forward",
      "field": "cpu_percent",
      "value": 45.2
    },
    {
      "timestamp": "2024-03-14T12:34:56.789Z",
      "model_id": "resnet18-train",
      "phase": "forward",
      "field": "ram_mb",
      "value": 1024.5
    }
  ]
}
```

---

#### `GET /api/metrics/aggregate`
Get aggregated time-series metrics with windowing.

**Query Parameters:**

All parameters from `/api/metrics/raw`, plus:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `window` | string | `1m` | Window duration (e.g., `30s`, `1m`, `5m`) |
| `aggregation` | string | `mean` | Aggregation function: `mean`, `max`, or `min` |

**Examples:**

```bash
# Mean CPU over 30-second windows
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-1h&window=30s&aggregation=mean&fields=cpu_percent"

# Max RAM per minute for a specific model
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-2h&window=1m&aggregation=max&model_id=resnet18-train&fields=ram_mb"

# Min throughput over 5-minute windows
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-24h&window=5m&aggregation=min&fields=throughput"
```

**Response:**
```json
{
  "count": 120,
  "window": "30s",
  "aggregation": "mean",
  "data": [
    {
      "timestamp": "2024-03-14T12:00:00Z",
      "model_id": "resnet18-train",
      "phase": "forward",
      "field": "cpu_percent",
      "value": 42.8
    }
  ]
}
```

---

### Discovery / Metadata

#### `GET /api/models`
Get list of distinct model_id values.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start_relative` | string | `-24h` | Time range for discovery |
| `start` | string | — | Absolute start time |
| `end` | string | — | Absolute end time |

**Example:**

```bash
curl "http://localhost:8000/api/models"
```

**Response:**
```json
{
  "count": 3,
  "models": [
    "data-pipeline",
    "distilbert-infer",
    "resnet18-train"
  ]
}
```

---

#### `GET /api/phases`
Get list of distinct phase values.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_id` | string | — | Filter by model |
| `start_relative` | string | `-24h` | Time range for discovery |
| `start` | string | — | Absolute start time |
| `end` | string | — | Absolute end time |

**Examples:**

```bash
# All phases
curl "http://localhost:8000/api/phases"

# Phases for a specific model
curl "http://localhost:8000/api/phases?model_id=resnet18-train"
```

**Response:**
```json
{
  "count": 4,
  "model_id": "resnet18-train",
  "phases": [
    "backward",
    "data_load",
    "forward",
    "optimizer_step"
  ]
}
```

---

#### `GET /api/metrics/fields`
Get list of available metric field names.

**Example:**

```bash
curl "http://localhost:8000/api/metrics/fields"
```

**Response:**
```json
{
  "count": 13,
  "fields": [
    "cpu_percent",
    "cpu_system",
    "ram_mb",
    "ram_system_pct",
    "io_read_mb",
    "io_write_mb",
    "thread_count",
    "page_faults_minor",
    "page_faults_major",
    "voluntary_ctx_switches",
    "llc_miss_rate",
    "throughput",
    "phase_duration_ms"
  ]
}
```

---

## Error Responses

### 422 Unprocessable Entity
Invalid query parameters (e.g., wrong type, out of range).

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "ensure this value is less than or equal to 10000",
      "type": "value_error.number.not_le"
    }
  ]
}
```

### 502 Bad Gateway
InfluxDB query failed.

```json
{
  "detail": "InfluxDB query failed: connection timeout"
}
```

### 503 Service Unavailable
InfluxDB is not reachable (health check).

---

## Postman Collection

### Import via OpenAPI

1. Start the API: `docker compose up backend`
2. In Postman: **Import** → **Link**
3. Enter: `http://localhost:8000/openapi.json`
4. Click **Import**

All endpoints will be available as a Postman collection with pre-filled parameters.

### Manual Setup

Create a new collection with these requests:

**Environment variables:**
- `base_url`: `http://localhost:8000`

**Requests:**

1. **Health Check**
   - GET `{{base_url}}/health`

2. **List Models**
   - GET `{{base_url}}/api/models`

3. **List Phases**
   - GET `{{base_url}}/api/phases?model_id=resnet18-train`

4. **Raw Metrics (Last 15m)**
   - GET `{{base_url}}/api/metrics/raw?start_relative=-15m&limit=100`

5. **Filtered Raw Metrics**
   - GET `{{base_url}}/api/metrics/raw?start_relative=-5m&model_id=resnet18-train&fields=cpu_percent,ram_mb`

6. **Aggregated Metrics**
   - GET `{{base_url}}/api/metrics/aggregate?start_relative=-1h&window=30s&aggregation=mean&fields=cpu_percent`

---

## Common Use Cases

### 1. Monitor CPU usage for a specific model

```bash
curl "http://localhost:8000/api/metrics/raw?start_relative=-30m&model_id=resnet18-train&fields=cpu_percent&limit=500"
```

### 2. Compare phases for a model

```bash
# Get all phases
curl "http://localhost:8000/api/phases?model_id=resnet18-train"

# Query each phase
curl "http://localhost:8000/api/metrics/raw?start_relative=-15m&model_id=resnet18-train&phase=forward&fields=cpu_percent"
curl "http://localhost:8000/api/metrics/raw?start_relative=-15m&model_id=resnet18-train&phase=backward&fields=cpu_percent"
```

### 3. Get average metrics over time windows

```bash
# Average CPU per minute for the last hour
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-1h&window=1m&aggregation=mean&fields=cpu_percent,ram_mb"
```

### 4. Find peak resource usage

```bash
# Max RAM usage in 5-minute windows
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-6h&window=5m&aggregation=max&fields=ram_mb,ram_system_pct"
```

### 5. Analyze specific time range

```bash
# Query a specific incident window
curl "http://localhost:8000/api/metrics/raw?start=2024-03-14T10:00:00Z&end=2024-03-14T10:30:00Z&fields=cpu_percent,llc_miss_rate"
```

---

## Running Locally (Development)

### Without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export INFLUX_URL=http://localhost:8086
export INFLUX_TOKEN=mlviz-dev-token
export INFLUX_ORG=mlviz
export INFLUX_BUCKET=metrics

# Run with auto-reload
uvicorn mlviz.api.main:app --reload --host 0.0.0.0 --port 8000

# Or use the main module
python -m mlviz.api.main
```

### With Docker (API only)

```bash
# Start just InfluxDB
docker compose up influxdb

# Run API locally
uvicorn mlviz.api.main:app --reload
```

---

## Tips & Best Practices

1. **Use relative time ranges** for recent data (e.g., `-5m`, `-1h`) — simpler and always current.

2. **Filter by model_id and phase** to reduce data volume and improve query performance.

3. **Specify fields** explicitly when you only need certain metrics (e.g., `fields=cpu_percent,ram_mb`).

4. **Use aggregation** for longer time ranges to reduce data points and see trends.

5. **Set appropriate limits** — default is 1000 for raw, 500 for aggregate. Increase if needed, but be mindful of response size.

6. **Check `/api/models` and `/api/phases`** first to discover what data is available.

7. **Use the Swagger UI** (`/docs`) for interactive testing and to see all parameter options.

8. **Export OpenAPI spec** for Postman to get a ready-made collection with all endpoints.

---

## Troubleshooting

### API returns 503 "InfluxDB disconnected"

**Cause:** InfluxDB is not running or not reachable.

**Fix:**
```bash
# Check InfluxDB status
docker compose ps influxdb

# Check InfluxDB logs
docker compose logs influxdb

# Restart if needed
docker compose restart influxdb backend
```

### Query returns empty data

**Possible causes:**
1. No data in the time range
2. Wrong model_id or phase
3. Aggregator hasn't written data yet

**Debug:**
```bash
# Check if models exist
curl "http://localhost:8000/api/models"

# Check aggregator logs
docker compose logs aggregator | grep "Flushed"

# Try wider time range
curl "http://localhost:8000/api/metrics/raw?start_relative=-24h&limit=10"
```

### Slow queries

**Tips:**
- Add `model_id` filter to reduce data scanned
- Use smaller time ranges
- Reduce `limit` parameter
- Use aggregation instead of raw for long ranges

---

## WebSocket Live Streaming

### `WS /ws/live`
Real-time metrics streaming via WebSocket.

**URL:** `ws://localhost:8000/ws/live`

**Description:**  
Connect to this WebSocket endpoint to receive live metric samples as they are produced by workloads and consumed from Kafka. Each message is pushed to all connected clients with sub-100ms latency.

**Message Format:**  
Each message is a JSON object with all MetricSample fields:

```json
{
  "timestamp": 1710374567890.123,
  "model_id": "resnet18-train",
  "phase": "forward",
  "cpu_percent": 45.2,
  "cpu_system": 23.5,
  "ram_mb": 1024.5,
  "ram_system_pct": 45.8,
  "io_read_mb": 12.3,
  "io_write_mb": 5.6,
  "thread_count": 8,
  "page_faults_minor": 150,
  "page_faults_major": 2,
  "voluntary_ctx_switches": 45,
  "llc_miss_rate": 0.15,
  "throughput": 32.5,
  "phase_duration_ms": 125.3
}
```

**Connection Message:**  
Upon successful connection, the server sends a welcome message:

```json
{
  "type": "connected",
  "message": "Live metrics stream connected"
}
```

### Testing with Postman

1. **Create WebSocket Request**:
   - In Postman, click **New** → **WebSocket Request**
   - Or change an existing request type to **WebSocket**

2. **Enter URL**:
   ```
   ws://localhost:8000/ws/live
   ```

3. **Connect**:
   - Click **Connect** button
   - You should see "Connected" status and the welcome message

4. **Receive Messages**:
   - Live metric samples will appear in the **Messages** pane
   - Each message is a complete MetricSample JSON object
   - Messages arrive every ~150ms (3 workloads × ~50ms each)

5. **Monitor**:
   - Messages are color-coded by direction (received = green)
   - You can filter messages or search for specific model_id/phase
   - The timestamp shows when each message was received

6. **Disconnect**:
   - Click **Disconnect** to close the WebSocket connection

### Testing with curl (wscat)

Install wscat if needed:
```bash
npm install -g wscat
```

Connect and receive messages:
```bash
wscat -c ws://localhost:8000/ws/live
```

Press Ctrl+C to disconnect.

### Testing with Python

```python
import asyncio
import websockets
import json

async def receive_metrics():
    uri = "ws://localhost:8000/ws/live"
    async with websockets.connect(uri) as websocket:
        print("Connected to live metrics stream")
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data.get("type") == "connected":
                print(f"Server: {data['message']}")
            else:
                print(f"[{data['model_id']}] {data['phase']}: CPU={data['cpu_percent']:.1f}%")

asyncio.run(receive_metrics())
```

### Testing with JavaScript (Browser)

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/live');

ws.onopen = () => {
  console.log('Connected to live metrics stream');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'connected') {
    console.log('Server:', data.message);
  } else {
    console.log(`[${data.model_id}] ${data.phase}: CPU=${data.cpu_percent.toFixed(1)}%`);
  }
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('Disconnected from live metrics stream');
};
```

### Troubleshooting

**No messages received:**
1. Verify workloads are running: `docker compose ps`
2. Check backend logs: `docker compose logs backend`
3. Confirm Kafka is healthy: `docker compose logs kafka`
4. Verify metrics are being produced: `docker compose logs aggregator | grep Flushed`

**Connection refused:**
- Ensure backend is running on port 8000
- Check firewall settings
- Verify URL uses `ws://` not `wss://` (no TLS in dev)

**Messages stop flowing:**
- Workloads may have finished (default 300s runtime)
- Restart stack: `docker compose restart`
- Check for Kafka consumer errors in backend logs

---

## Next Steps

- Implement authentication/API keys
- Add rate limiting
- Build React dashboard that consumes WebSocket and REST endpoints
- Add reconnection logic for production use
