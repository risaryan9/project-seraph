# InfluxDB Integration Guide

This document describes the InfluxDB integration in Seraph and how to verify it's working correctly.

## Overview

The aggregator service consumes metrics from Kafka and writes them to InfluxDB in batches:
- **Batch size**: 50 samples
- **Flush interval**: 500 milliseconds
- **Measurement**: `hardware_sample`
- **Tags**: `model_id`, `phase`
- **Fields**: All 13 metric fields from MetricSample

## Quick Start

### 1. Start the Stack

```bash
docker-compose up --build
```

This will start:
- Kafka and Zookeeper
- InfluxDB (auto-configured with org, bucket, and token)
- 3 workload simulations
- Aggregator (writing to InfluxDB)
- Live-view (terminal display)

### 2. Verify InfluxDB is Running

Check the aggregator logs:

```bash
docker-compose logs aggregator | grep -i influx
```

You should see:
```
InfluxDB client initialized: http://influxdb:8086
Writing to bucket: metrics, org: mlviz
Batch config: size=50, interval=500ms
Flushed 50 points to InfluxDB
```

### 3. Access InfluxDB UI

1. Open http://localhost:8086 in your browser
2. Log in with:
   - **Username**: `admin`
   - **Password**: `mlviz-admin-password`
3. Click **Data Explorer** in the left sidebar

### 4. Query Metrics

In the Data Explorer:

1. Select bucket: `metrics`
2. Select measurement: `hardware_sample`
3. Filter by tags:
   - `model_id`: `resnet18-train`, `distilbert-infer`, or `data-pipeline`
   - `phase`: `forward`, `backward`, `data_load`, `inference`, etc.
4. Select fields to visualize (e.g., `cpu_percent`, `ram_mb`)
5. Click **Submit** to see the time-series graph

## Configuration

### Docker Compose

The InfluxDB service is configured with automatic setup:

```yaml
influxdb:
  image: influxdb:2.7
  environment:
    DOCKER_INFLUXDB_INIT_MODE: setup
    DOCKER_INFLUXDB_INIT_ORG: mlviz
    DOCKER_INFLUXDB_INIT_BUCKET: metrics
    DOCKER_INFLUXDB_INIT_USERNAME: admin
    DOCKER_INFLUXDB_INIT_PASSWORD: mlviz-admin-password
    DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: mlviz-dev-token
```

### Aggregator Environment Variables

```yaml
aggregator:
  environment:
    INFLUX_URL: http://influxdb:8086
    INFLUX_TOKEN: mlviz-dev-token
    INFLUX_ORG: mlviz
    INFLUX_BUCKET: metrics
```

## Data Schema

### Measurement: `hardware_sample`

**Tags** (indexed for fast filtering):
- `model_id`: Identifier for the model (e.g., "resnet18-train")
- `phase`: Execution phase (e.g., "forward", "backward")

**Fields** (metric values):
- `cpu_percent`: Process CPU usage percentage
- `cpu_system`: System-wide CPU usage percentage
- `ram_mb`: Process RSS memory in megabytes
- `ram_system_pct`: System-wide RAM usage percentage
- `io_read_mb`: I/O read in MB since last sample
- `io_write_mb`: I/O write in MB since last sample
- `thread_count`: Number of threads in the process
- `page_faults_minor`: Minor page faults since last sample
- `page_faults_major`: Major page faults since last sample
- `voluntary_ctx_switches`: Voluntary context switches since last sample
- `llc_miss_rate`: Last-level cache miss rate (0.0-1.0, or -1 if unavailable)
- `throughput`: Items processed per second (or -1 if not set)
- `phase_duration_ms`: Duration of the current phase in milliseconds

**Timestamp**: Nanosecond precision (converted from MetricSample milliseconds)

## Example Queries

### Flux Query: Average CPU by Model

```flux
from(bucket: "metrics")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  |> filter(fn: (r) => r._field == "cpu_percent")
  |> group(columns: ["model_id"])
  |> mean()
```

### Flux Query: RAM Usage by Phase

```flux
from(bucket: "metrics")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  |> filter(fn: (r) => r._field == "ram_mb")
  |> filter(fn: (r) => r.model_id == "resnet18-train")
  |> group(columns: ["phase"])
```

### Flux Query: Throughput Over Time

```flux
from(bucket: "metrics")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  |> filter(fn: (r) => r._field == "throughput")
  |> filter(fn: (r) => r.throughput >= 0)
```

## Troubleshooting

### Aggregator Not Writing to InfluxDB

Check logs:
```bash
docker-compose logs aggregator
```

Common issues:
1. **InfluxDB not healthy**: Wait for healthcheck to pass
2. **Wrong credentials**: Verify token matches in both services
3. **Network issues**: Ensure both services are on `mlviz-network`

### No Data in InfluxDB UI

1. Verify workloads are running:
   ```bash
   docker-compose ps
   ```

2. Check Kafka has messages:
   - Open http://localhost:8081
   - Browse to a `metrics.*` topic
   - View messages

3. Verify aggregator is consuming:
   ```bash
   docker-compose logs aggregator | grep "Flushed"
   ```

### InfluxDB Container Won't Start

1. Remove old volumes:
   ```bash
   docker-compose down -v
   docker-compose up --build
   ```

2. Check port 8086 is not in use:
   ```bash
   lsof -i :8086
   ```

## Bucket Retention Policy

By default, InfluxDB creates the bucket with infinite retention. To set a 7-day retention (as specified in SERAPH_CONTEXT.md):

### Option 1: Via UI

1. Go to **Load Data** → **Buckets**
2. Click on the `metrics` bucket
3. Edit retention period to `7 days`

### Option 2: Via CLI

```bash
docker exec -it mlviz-influxdb influx bucket update \
  --name metrics \
  --retention 7d \
  --org mlviz \
  --token mlviz-dev-token
```

### Option 3: Via API

```bash
curl -X PATCH http://localhost:8086/api/v2/buckets/<bucket-id> \
  -H "Authorization: Token mlviz-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"retentionRules": [{"type": "expire", "everySeconds": 604800}]}'
```

## Performance Notes

- **Batch writes** reduce InfluxDB load compared to individual writes
- **50 samples** typically represents ~7.5 seconds of data (3 models × 150ms interval)
- **500ms flush interval** ensures low latency even with low throughput
- **Synchronous writes** ensure data consistency; for higher throughput, consider async mode

## Next Steps

- Implement anomaly detection (CPU > 90%, LLC > 0.8) and produce alerts
- Add FastAPI backend to query InfluxDB for historical data
- Build React dashboard with Recharts to visualize time-series data
- Add Grafana integration for advanced visualization
