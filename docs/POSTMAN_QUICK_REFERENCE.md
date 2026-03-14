# Postman Quick Reference for Seraph API

Quick copy-paste URLs for testing the Seraph API in Postman.

## Setup

1. **Base URL**: `http://localhost:8000`
2. **Start the stack**: `docker compose up --build`
3. **Wait ~30 seconds** for services to start and data to populate

---

## Essential Endpoints (Copy & Paste)

### 1. Health Check
```
GET http://localhost:8000/health
```

### 2. List All Models
```
GET http://localhost:8000/api/models
```

### 3. List All Phases
```
GET http://localhost:8000/api/phases
```

### 4. List Available Fields
```
GET http://localhost:8000/api/metrics/fields
```

---

## Raw Metrics Queries

### Last 5 Minutes (All Models)
```
GET http://localhost:8000/api/metrics/raw?start_relative=-5m&limit=100
```

### Last 15 Minutes (Specific Model)
```
GET http://localhost:8000/api/metrics/raw?start_relative=-15m&model_id=resnet18-train&limit=200
```

### CPU and RAM Only
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&fields=cpu_percent,ram_mb&limit=150
```

### Specific Phase
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&model_id=resnet18-train&phase=forward&limit=100
```

### Multiple Fields for One Model
```
GET http://localhost:8000/api/metrics/raw?start_relative=-5m&model_id=distilbert-infer&fields=cpu_percent,ram_mb,throughput&limit=100
```

---

## Aggregated Metrics Queries

### Mean CPU (30-second windows, last hour)
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-1h&window=30s&aggregation=mean&fields=cpu_percent
```

### Max RAM (1-minute windows, last 2 hours)
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-2h&window=1m&aggregation=max&fields=ram_mb
```

### Mean CPU for Specific Model
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-1h&window=30s&aggregation=mean&model_id=resnet18-train&fields=cpu_percent
```

### Min Throughput (5-minute windows)
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-6h&window=5m&aggregation=min&fields=throughput
```

### Multiple Metrics Aggregated
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-1h&window=1m&aggregation=mean&fields=cpu_percent,ram_mb,io_read_mb,io_write_mb
```

---

## Discovery Queries

### Phases for ResNet Model
```
GET http://localhost:8000/api/phases?model_id=resnet18-train
```

### Phases for DistilBERT Model
```
GET http://localhost:8000/api/phases?model_id=distilbert-infer
```

### Phases for Data Pipeline
```
GET http://localhost:8000/api/phases?model_id=data-pipeline
```

### Models in Last 6 Hours
```
GET http://localhost:8000/api/models?start_relative=-6h
```

---

## Advanced Queries

### Absolute Time Range (ISO8601)
```
GET http://localhost:8000/api/metrics/raw?start=2024-03-14T00:00:00Z&end=2024-03-14T12:00:00Z&limit=500
```

### All Metrics for Forward Pass
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&phase=forward&limit=200
```

### LLC Cache Miss Rate
```
GET http://localhost:8000/api/metrics/raw?start_relative=-15m&fields=llc_miss_rate&limit=100
```

### I/O Metrics
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&fields=io_read_mb,io_write_mb&limit=150
```

### Page Faults
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&fields=page_faults_minor,page_faults_major&limit=150
```

### System-Wide Metrics
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&fields=cpu_system,ram_system_pct&limit=150
```

---

## Postman Collection Import

### Method 1: OpenAPI Import (Recommended)

1. Start the API: `docker compose up backend`
2. In Postman: **Import** → **Link**
3. Paste: `http://localhost:8000/openapi.json`
4. Click **Import**

### Method 2: Manual Collection

1. Create new collection: "Seraph API"
2. Add variable: `base_url` = `http://localhost:8000`
3. Copy-paste requests from above, replacing `http://localhost:8000` with `{{base_url}}`

---

## Testing Workflow

### 1. Verify Stack is Running
```
GET http://localhost:8000/health
```
Expected: `{"status": "ok", "influx": "connected"}`

### 2. Discover Available Data
```
GET http://localhost:8000/api/models
GET http://localhost:8000/api/phases
GET http://localhost:8000/api/metrics/fields
```

### 3. Query Recent Data
```
GET http://localhost:8000/api/metrics/raw?start_relative=-5m&limit=50
```

### 4. Filter by Model
```
GET http://localhost:8000/api/metrics/raw?start_relative=-10m&model_id=resnet18-train&limit=100
```

### 5. Try Aggregation
```
GET http://localhost:8000/api/metrics/aggregate?start_relative=-30m&window=1m&aggregation=mean&fields=cpu_percent
```

---

## Common Issues

### Empty Response (`"count": 0, "data": []`)

**Cause:** No data in time range or filters too restrictive.

**Fix:**
1. Check models exist: `GET http://localhost:8000/api/models`
2. Try wider time range: `start_relative=-1h` or `-24h`
3. Remove filters (model_id, phase, fields)
4. Check aggregator logs: `docker compose logs aggregator`

### 503 Error

**Cause:** InfluxDB not connected.

**Fix:**
```bash
docker compose restart influxdb backend
docker compose logs backend
```

### 422 Error

**Cause:** Invalid parameter (e.g., limit > 10000).

**Fix:** Check parameter constraints in error message.

---

## Pro Tips

1. **Start simple**: Test `/health` and `/api/models` first
2. **Use small limits**: Start with `limit=10` to see data structure
3. **Check timestamps**: Verify data is recent (within last hour)
4. **Filter progressively**: Start broad, then add model_id, phase, fields
5. **Use Swagger UI**: Visit http://localhost:8000/docs for interactive testing
6. **Save responses**: Use Postman's "Save Response" to compare results
7. **Create tests**: Add Postman tests to verify response structure

---

## Example Response Structures

### Raw Metrics Response
```json
{
  "count": 2,
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

### Aggregate Response
```json
{
  "count": 1,
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

### Models Response
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

## Quick Curl Commands (Terminal)

```bash
# Health
curl http://localhost:8000/health

# Models
curl http://localhost:8000/api/models

# Raw metrics (pretty print with jq)
curl "http://localhost:8000/api/metrics/raw?start_relative=-5m&limit=10" | jq

# Aggregate (pretty print)
curl "http://localhost:8000/api/metrics/aggregate?start_relative=-30m&window=1m&aggregation=mean&fields=cpu_percent" | jq
```
