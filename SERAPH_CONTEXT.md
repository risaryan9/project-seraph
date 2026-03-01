# Seraph — Persistent Context Reference

This document is the single source of truth for the Seraph codebase. Use it as persistent context for all future development.

> **Important:** Treat this document as **rough, flexible context** — do not adhere to it rigidly. Requirements and architecture may change over time; when they do, update this document accordingly so it stays useful as a living reference.

---

## 1. Project Overview

**Project name:** Seraph

**What Seraph is:** A cloud-native, distributed hardware resource monitoring framework for concurrent ML models. It attributes **CPU, RAM, cache, and I/O** usage to individual ML models at the **phase level** — i.e., it tracks not only which model is consuming resources, but during which specific stage of execution (data loading, forward pass, backward pass, optimizer step, inference).

**Core insight:** Existing monitoring tools (Datadog, Prometheus) report system-wide metrics (e.g., "CPU at 87%") but cannot attribute that to a specific model or phase. ML experiment trackers (W&B, MLflow) track model accuracy and hyperparameters but not hardware consumption. Seraph sits in the gap between those two categories and is built with production-grade distributed infrastructure from day one, not as an afterthought.

---

## 2. Tech Stack

### Infrastructure (Docker Compose — single-command startup)

| Component | Image / Notes |
|-----------|----------------|
| Apache Kafka | `confluentinc/cp-kafka` — message broker |
| Zookeeper | `confluentinc/cp-zookeeper` — Kafka coordination |
| InfluxDB | `influxdb:2.7` — time-series storage |

**Start all infrastructure:** `docker-compose up -d`

### Python services

| Library | Purpose |
|---------|--------|
| `kafka-python` | Kafka producer in agents, consumer in aggregator |
| `influxdb-client` | Writes from aggregator, reads from FastAPI |
| `fastapi` + `uvicorn` | REST API + WebSocket backend |
| `psutil` | Per-process hardware metrics |
| `numpy` | Model simulation via matrix multiplications |
| `perf stat` (subprocess) | LLC cache metrics on Linux |

### Frontend

| Technology | Purpose |
|------------|--------|
| React 18 | UI framework |
| Recharts | All chart components |
| Native WebSocket API | Real-time data from FastAPI `/ws/live` |

---

## 3. Core Data Structure — MetricSample

Every sample collected by an agent and sent to Kafka is a **MetricSample**. It contains:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | float | Unix epoch milliseconds |
| `model_id` | string | e.g. `"resnet18-train"` |
| `phase` | string | e.g. `"forward"`, `"backward"`, `"data_load"`, `"inference"`, `"optimizer_step"`, `"idle"`, or any custom string |
| `cpu_percent` | float | This process only (via psutil) |
| `cpu_system` | float | System-wide CPU % |
| `ram_mb` | float | RSS in megabytes |
| `ram_system_pct` | float | System RAM used % |
| `io_read_mb` | float | Delta since last sample |
| `io_write_mb` | float | Delta since last sample |
| `thread_count` | int | — |
| `page_faults_minor` | int | Delta |
| `page_faults_major` | int | Delta |
| `voluntary_ctx_switches` | int | Delta |
| `llc_miss_rate` | float | 0.0–1.0 from perf stat, or `-1` if unavailable |
| `throughput` | float | Items/sec, or `-1` if not set |
| `phase_duration_ms` | float | — |

**Serialization:** JSON. Every MetricSample is `json.dumps()` before Kafka produce and `json.loads()` after Kafka consume.

---

## 4. Kafka Topic Design

| Aspect | Design |
|--------|--------|
| **Naming** | One topic per model: `metrics.{model_id}` (e.g. `metrics.resnet18-train`, `metrics.distilbert-infer`) |
| **Alerts** | One shared topic: `metrics.alerts` |
| **Partitions** | 3 per topic (enables parallel consumers) |
| **Retention** | 24 hours (not permanent storage — InfluxDB handles that) |
| **Auto topic creation** | Enabled in Kafka config |

---

## 5. InfluxDB Design

| Setting | Value |
|---------|--------|
| **Organization** | `mlviz` |
| **Bucket** | `metrics` (7-day retention) |
| **Measurement name** | `hardware_sample` |

**Tags (indexed, for fast filtering):**

- `model_id`
- `phase`

**Fields (metric values):**

- `cpu_percent`, `cpu_system`, `ram_mb`, `ram_system_pct`
- `io_read_mb`, `io_write_mb`, `thread_count`
- `page_faults_minor`, `page_faults_major`, `voluntary_ctx_switches`
- `llc_miss_rate`, `throughput`, `phase_duration_ms`

**Time:** `MetricSample.timestamp` (nanosecond precision).

---

## 6. Services and Their Roles

### 6.1 MLViz Agent (runs inside each model process)

- Collects metrics via psutil every **150 ms**.
- Tags each sample with `model_id` and current **phase**.
- Produces MetricSample JSON to Kafka topic `metrics.{model_id}`.
- **Never blocks** model execution — runs in a daemon thread.
- Connects to Kafka using `bootstrap_servers` from env var **`KAFKA_BROKER`** (default: `localhost:9092`).

### 6.2 Model Simulations (3 separate OS processes)

- **resnet18-train:** `data_load` → `forward` → `backward` → `optimizer_step` (repeat).
- **distilbert-infer:** `data_load` → `inference` (variable batch + seq_len).
- **data-pipeline:** `data_load` → `augment` → `serialize` (repeat).

All use numpy matmuls sized to match real model compute profiles. Each process creates its own MLViz Agent on startup.

### 6.3 Aggregator Consumer (standalone Python process)

- Subscribes to all `metrics.*` topics via a Kafka consumer group.
- Deserializes MetricSample JSON.
- Writes to InfluxDB in **batches of 50** or **every 500 ms**.
- Watches for anomalies (e.g. CPU > 90% sustained, LLC > 0.8) and produces alert events to **`metrics.alerts`**.

### 6.4 FastAPI Backend

- Queries InfluxDB for historical/aggregated data (REST endpoints).
- Maintains WebSocket connections to React clients.
- Runs a background Kafka consumer that forwards **live samples** directly to connected WebSocket clients with **<100 ms latency**.
- CORS enabled for React dev server (`localhost:3000`).

### 6.5 React Dashboard

- Connects to FastAPI WebSocket on mount.
- Maintains a **rolling 60-second buffer** of samples in memory (`useState`).
- **No polling** — all updates are push-based via WebSocket.
- Recharts for all visualizations.

---

## 7. Three Simulated Workloads

### 7.1 resnet18-train

**Phases:** `data_load` → `forward` → `backward` → `optimizer_step` → repeat.

| Phase | Description |
|-------|-------------|
| **data_load** | `np.random.randint(0, 255, (32, 224, 224, 3), uint8)`, normalize |
| **forward** | Matmuls at [512×512, 256×256, 128×128, 64×64] sequential |
| **backward** | Matmuls at [768×768, 512×512] + gradient array allocation |
| **optimizer_step** | Matmuls at [256×256, 128×128] + array writes |

**Throughput:** images/sec.

### 7.2 distilbert-infer

- `batch_size = random.choice([1, 2, 4, 8])`
- `seq_len = random.choice([128, 256, 512])`

**Phases:** `data_load` → `inference` → repeat.

| Phase | Description |
|-------|-------------|
| **data_load** | `np.random.randint(0, 30000, (batch_size, seq_len), int32)` |
| **inference** | 6 transformer layers, each with: Q/K/V: `matmul(batch*seq, 768) × (768, 768)` — 3 times; FFN: `matmul(batch*seq, 768) × (768, 3072)` |

**Throughput:** tokens/sec.

### 7.3 data-pipeline

**Phases:** `data_load` → `augment` → `serialize` → repeat.

| Phase | Description |
|-------|-------------|
| **data_load** | `np.random.randint(0, 255, (128, 256, 256, 3), uint8)` |
| **augment** | Matmuls [400×400, 300×300] + numpy array slicing ops |
| **serialize** | Array copy + reshape operations |

**Throughput:** records/sec.

---

## 8. Key Design Decisions

### Kafka over mp.Queue

`mp.Queue` only works within one machine and one Python runtime. Kafka works across machines, languages, and clouds. The architecture is the same whether running on one laptop or 50 servers — agents only need a different `KAFKA_BROKER` address. This is what makes Seraph genuinely cloud-native.

### InfluxDB over SQLite

SQLite is file-based; InfluxDB is purpose-built for time-series data. It compresses metrics efficiently, indexes by time automatically, and provides Flux for time-window aggregations. Queries like "average CPU per phase over last 30 seconds" are one line in Flux vs. complex SQL window functions.

### WebSocket over Streamlit polling

Streamlit reruns the entire script on every refresh; with many panels this causes lag and flickering. WebSocket pushes only changed data; React updates only changed components. The result feels like a real product.

### FastAPI as the bridge

React cannot talk to Kafka or InfluxDB directly — there are no browser-compatible clients. FastAPI is the translation layer: it speaks Kafka/InfluxDB on the backend and HTTP/WebSocket to the browser. This is the standard production pattern.

### One Kafka topic per model

Consumers can subscribe to specific models. The dashboard can show only the models a team cares about. In enterprise setups, teams see only their own models' topics.

---

## 9. Differentiating Features vs. Existing Tools

1. **Phase-attributed hardware metrics** — no existing tool does this.
2. **Per-model attribution on shared hardware** via psutil PID isolation.
3. **True cloud-native agent** — same code on laptop or K8s cluster.
4. **Interference score** — throughput delta: solo vs. concurrent.
5. **LLC cache contention** via `perf stat` (Linux).
6. **WebSocket real-time** — sub-100 ms latency from metric to screen.
7. **Plug-and-play onboarding** — ~4 lines of code; model appears in ~15 s.

---

*End of SERAPH_CONTEXT.md*
