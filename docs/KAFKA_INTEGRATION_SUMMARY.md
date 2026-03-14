# Kafka Integration — Implementation Summary

This document summarizes the Kafka and Docker integration that was just completed.

---

## What Was Implemented

### 1. Kafka Producer Integration

**Files modified/created:**
- `requirements.txt` — Added `kafka-python==2.0.2`
- `.env` — Added `KAFKA_BROKER=localhost:9092`
- `mlviz/profiler/metrics.py` — Added `to_dict()`, `to_json()`, `from_dict()`, `from_json()` methods
- `mlviz/profiler/kafka_producer.py` — **New**: Singleton Kafka producer wrapper
- `mlviz/profiler/agent.py` — Integrated Kafka producer; agent now sends to both internal queue and Kafka

**How it works:**
- `MLVizAgent` now has a `_kafka_producer` that's initialized if `KAFKA_ENABLED=true`
- Every 150ms when a sample is collected, it's both:
  - Put in the internal queue (for backward compatibility / local testing)
  - Sent to Kafka topic `metrics.{model_id}` with key `model_id`
- Kafka sending is non-blocking and failures are logged but don't crash the agent

### 2. Standalone Workload Services

**Files created:**
- `mlviz/workloads/resnet_main.py` — Standalone ResNet-18 training entrypoint
- `mlviz/workloads/bert_main.py` — Standalone DistilBERT inference entrypoint
- `mlviz/workloads/pipeline_main.py` — Standalone data pipeline entrypoint

**How it works:**
- Each file is a complete `if __name__ == "__main__"` script
- No dependency on `mp.Queue` or orchestrator
- Creates its own `MLVizAgent`, runs the workload loop, uses `phase()` and `set_throughput()`
- Agent automatically sends to Kafka in the background
- Can be run standalone: `python -m mlviz.workloads.resnet_main`

### 3. Aggregator Consumer Service

**Files created:**
- `mlviz/aggregator/__init__.py`
- `mlviz/aggregator/service.py` — Kafka consumer with group `mlviz-aggregator`

**How it works:**
- Subscribes to all 3 `metrics.*` topics
- Consumer group: `mlviz-aggregator`
- Deserializes JSON → `MetricSample`
- Currently logs with prefix `AGG |`
- Later will write to InfluxDB and produce alerts

### 4. Live-View Consumer Service

**Files created:**
- `mlviz/live_view/__init__.py`
- `mlviz/live_view/service.py` — Kafka consumer with group `mlviz-live-view`

**How it works:**
- Subscribes to all 3 `metrics.*` topics (separate consumer group from aggregator)
- Consumer group: `mlviz-live-view`
- Displays colored terminal output (same format as original orchestrator)
- Divider lines every 15 samples
- This is the "real-time view" that replaces the orchestrator's queue-based display

### 5. Topic Bootstrap

**Files created:**
- `mlviz/bootstrap_topics.py` — Script to create topics with 3 partitions each

**How it works:**
- Uses Kafka admin client to create 4 topics:
  - `metrics.resnet18-train`
  - `metrics.distilbert-infer`
  - `metrics.data-pipeline`
  - `metrics.alerts`
- Each topic: 3 partitions, replication factor 1
- Retries up to 10 times with 3s delay (waits for Kafka to be ready)
- Runs as a one-shot init container in Docker Compose

### 6. Docker Infrastructure

**Files created:**
- `Dockerfile` — Multi-purpose Python image for all services
- `docker-compose.yml` — Complete stack definition

**Services in docker-compose.yml:**
1. **zookeeper** — Kafka coordination
2. **kafka** — Message broker with healthcheck
3. **kafka-ui** — Kafdrop web UI on port 8080
4. **topic-bootstrap** — One-shot topic creation
5. **resnet18-train** — Workload container
6. **distilbert-infer** — Workload container
7. **data-pipeline** — Workload container
8. **aggregator** — Consumer for long-term processing
9. **live-view** — Consumer for real-time terminal display

All services share the `mlviz-network` bridge network.

### 7. Documentation

**Files created:**
- `README.md` — Quick start, architecture, configuration
- `VERIFICATION.md` — Step-by-step verification guide
- `HOW_IT_WORKS.md` — Low-level explanation for hackathon judges (created earlier)

---

## Architecture Changes

### Before (Queue-based)

```
Orchestrator (main process)
  ├─> Process 1: resnet18-train + agent → mp.Queue
  ├─> Process 2: distilbert-infer + agent → mp.Queue
  └─> Process 3: data-pipeline + agent → mp.Queue
       ↓
  Orchestrator reads queue and prints
```

### After (Kafka-based)

```
Container 1: resnet18-train + agent → Kafka (metrics.resnet18-train)
Container 2: distilbert-infer + agent → Kafka (metrics.distilbert-infer)
Container 3: data-pipeline + agent → Kafka (metrics.data-pipeline)
                                       ↓
                                    Kafka Broker
                                       ↓
                    ┌──────────────────┴──────────────────┐
                    ↓                                     ↓
          Container 4: Aggregator              Container 5: Live-View
          (group: mlviz-aggregator)            (group: mlviz-live-view)
          → logs with AGG prefix               → colored terminal output
```

**Key differences:**
- Workloads are now **independent containers** (not child processes)
- Communication via **Kafka topics** (not in-process queue)
- **Two consumer groups** get independent copies of the stream
- Kafka UI provides web-based inspection
- Architecture is now **cloud-native**: same code works on laptop or K8s cluster

---

## How to Run

### Full Stack (Docker)

```bash
# Start everything
docker compose up --build

# View live metrics
docker compose logs -f live-view

# View aggregator
docker compose logs -f aggregator

# Open Kafka UI
# Browser: http://localhost:8080

# Stop
docker compose down
```

### Local Development (No Docker)

```bash
# Disable Kafka
echo "KAFKA_ENABLED=false" >> .env

# Run original orchestrator
python orchestrator.py
```

---

## Consumer Group Design

| Group ID | Purpose | What It Does |
|----------|---------|--------------|
| `mlviz-aggregator` | Long-term processing | Consumes all `metrics.*` topics; later writes to InfluxDB and produces alerts |
| `mlviz-live-view` | Real-time display | Consumes all `metrics.*` topics; prints colored terminal output for monitoring |

Both groups receive **the same messages** (Kafka duplicates the stream per consumer group). Partitions (3 per topic) allow each group to scale to 3 parallel consumers if needed.

---

## Next Steps (Not Yet Implemented)

1. Add InfluxDB container to docker-compose
2. Update aggregator to write to InfluxDB (batches of 50 or every 500ms)
3. Implement anomaly detection in aggregator (CPU > 90%, LLC > 0.8)
4. Add FastAPI backend with REST + WebSocket
5. Build React dashboard with Recharts
6. Add interference score calculation

---

## File Structure

```
project-seraph/
├── mlviz/
│   ├── __init__.py
│   ├── profiler/
│   │   ├── __init__.py
│   │   ├── metrics.py          ← MetricSample + JSON serialization
│   │   ├── agent.py            ← MLVizAgent + Kafka integration
│   │   └── kafka_producer.py   ← NEW: Kafka producer wrapper
│   ├── workloads/
│   │   ├── __init__.py
│   │   ├── runners.py          ← Original mp.Queue-based runners (kept for reference)
│   │   ├── resnet_main.py      ← NEW: Standalone ResNet service
│   │   ├── bert_main.py        ← NEW: Standalone BERT service
│   │   └── pipeline_main.py    ← NEW: Standalone pipeline service
│   ├── aggregator/
│   │   ├── __init__.py         ← NEW
│   │   └── service.py          ← NEW: Aggregator consumer (group A)
│   ├── live_view/
│   │   ├── __init__.py         ← NEW
│   │   └── service.py          ← NEW: Live-view consumer (group B)
│   └── bootstrap_topics.py     ← NEW: Topic creation script
├── orchestrator.py             ← Original orchestrator (still works for local dev)
├── Dockerfile                  ← NEW: Multi-purpose Python image
├── docker-compose.yml          ← NEW: Full stack definition
├── requirements.txt            ← Updated: added kafka-python
├── .env                        ← Updated: added KAFKA_BROKER
├── .gitignore
├── README.md                   ← NEW: Quick start guide
├── VERIFICATION.md             ← NEW: Testing guide
├── HOW_IT_WORKS.md             ← Hackathon explanation
└── SERAPH_CONTEXT.md           ← Project specification
```

---

*Implementation complete. All code is ready to run. See VERIFICATION.md for testing instructions.*
