# Seraph — ML Hardware Resource Monitor

A cloud-native, distributed hardware resource monitoring framework for concurrent ML models with phase-level attribution.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Docker permissions: either run with `sudo` or add your user to the docker group:
  ```bash
  sudo usermod -aG docker $USER
  newgrp docker  # or log out and back in
  ```
- (Optional) Python 3.11+ for local development

### Running with Docker (Recommended)

Start the entire stack (Kafka, Zookeeper, InfluxDB, Kafka UI, 3 workloads, aggregator, live-view):

```bash
docker-compose up --build
```

This will:
1. Start Zookeeper and Kafka
2. Start InfluxDB with auto-configured org, bucket, and token
3. Bootstrap topics with 3 partitions each
4. Launch 3 ML workload simulations (resnet18-train, distilbert-infer, data-pipeline)
5. Start the aggregator service (writes to InfluxDB in batches)
6. Start the live-view service (colored terminal output)
7. Start Kafka UI at http://localhost:8081
8. Start InfluxDB UI at http://localhost:8086

### Viewing Metrics

**Option 1 — Live terminal view:**
```bash
docker-compose logs -f live-view
```

**Option 2 — Aggregator logs:**
```bash
docker-compose logs -f aggregator
```

**Option 3 — Kafka UI:**
Open http://localhost:8081 in your browser to:
- Browse topics (`metrics.resnet18-train`, `metrics.distilbert-infer`, `metrics.data-pipeline`)
- View messages in real-time
- Inspect partitions and consumer groups

**Option 4 — InfluxDB UI:**
Open http://localhost:8086 in your browser to:
- Log in with username `admin` and password `mlviz-admin-password`
- Query the `metrics` bucket
- View time-series data in the Data Explorer
- See all metrics tagged by `model_id` and `phase`

### Stopping

```bash
docker-compose down
```

To also remove volumes:
```bash
docker-compose down -v
```

---

## Local Development (Without Docker)

### Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

### Running Locally (No Kafka)

The original orchestrator still works for local testing without Kafka:

```bash
# Disable Kafka in .env
echo "KAFKA_ENABLED=false" >> .env

# Run orchestrator
python orchestrator.py
```

This runs all 3 workloads as child processes with metrics printed to terminal.

### Running with Local Kafka

If you have Kafka running locally (e.g. via Docker):

```bash
# Start just Kafka infrastructure
docker-compose up zookeeper kafka kafka-ui

# In another terminal, run workloads
python -m mlviz.workloads.resnet_main &
python -m mlviz.workloads.bert_main &
python -m mlviz.workloads.pipeline_main &

# Run live-view consumer
python -m mlviz.live_view.service
```

---

## Architecture Overview

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ resnet18     │    │ distilbert   │    │ data-pipeline│
│ workload     │    │ workload     │    │ workload     │
│              │    │              │    │              │
│ MLVizAgent   │    │ MLVizAgent   │    │ MLVizAgent   │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       │ produce           │ produce           │ produce
       │ JSON              │ JSON              │ JSON
       └───────────────────┴───────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Kafka     │
                    │   Broker    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │Aggregator│  │Live-View │  │ Kafka UI │
       │(group A) │  │(group B) │  │ (browse) │
       └─────┬────┘  └──────────┘  └──────────┘
             │
             │ batch write
             │ (50 samples or 500ms)
             ▼
       ┌──────────┐
       │ InfluxDB │
       │ (metrics)│
       └──────────┘
```

### Key Components

- **MLViz Agent**: Runs in each workload process; collects hardware metrics every 150ms and produces to Kafka.
- **Workloads**: Three simulated ML models (ResNet training, DistilBERT inference, data pipeline).
- **Kafka**: Message broker with topics `metrics.{model_id}` (3 partitions each).
- **Aggregator**: Consumer group `mlviz-aggregator` that writes metrics to InfluxDB in batches (50 samples or 500ms).
- **InfluxDB**: Time-series database storing all metrics with tags (`model_id`, `phase`) and 13 metric fields.
- **Live-View**: Consumer group `mlviz-live-view` for real-time terminal display.
- **Kafka UI**: Web interface for inspecting topics, partitions, and messages.

---

## Configuration

Edit `.env` to configure:

```bash
# Workload configuration
SAMPLE_INTERVAL_MS=150      # Metric collection interval
RUN_SECONDS=300             # How long workloads run

# Kafka configuration
KAFKA_BROKER=localhost:9092 # Kafka address (kafka:9092 in Docker)
KAFKA_ENABLED=true          # Enable/disable Kafka (use false for local queue-only mode)

# InfluxDB configuration (aggregator only)
INFLUX_URL=http://localhost:8086  # InfluxDB address (http://influxdb:8086 in Docker)
INFLUX_TOKEN=mlviz-dev-token      # Admin token
INFLUX_ORG=mlviz                  # Organization name
INFLUX_BUCKET=metrics             # Bucket name
```

---

## Metrics Collected

Each `MetricSample` contains:
- **Timestamp** (Unix epoch ms)
- **Model ID** and **Phase** (e.g. "forward", "backward")
- **CPU**: Process and system-wide percentages
- **RAM**: Process MB and system percentage
- **I/O**: Read/write deltas in MB
- **Threads**: Thread count
- **Page Faults**: Minor and major deltas
- **Context Switches**: Voluntary switches delta
- **LLC Miss Rate**: Last-level cache miss rate (Linux + perf only)
- **Throughput**: Items/sec (images, tokens, records)
- **Phase Duration**: Time spent in current phase (ms)

---

## Next Steps

- [x] Add InfluxDB for time-series storage
- [ ] Implement anomaly detection and alerts
- [ ] Add FastAPI backend with WebSocket support
- [ ] Build React dashboard with Recharts
- [ ] Add interference score calculation
- [ ] Implement Kubernetes deployment manifests

---

For more details, see:
- `SERAPH_CONTEXT.md` — Full project specification
- `HOW_IT_WORKS.md` — Low-level technical explanation
