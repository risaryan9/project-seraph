# Kafka & Docker Integration — Verification Guide

This document provides step-by-step instructions to verify the Kafka and Docker integration is working correctly.

---

## 1. Pre-flight Checks

Before starting, ensure:

```bash
# Docker is installed and accessible
docker --version
docker compose version

# If you get permission errors, either:
# Option A: Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Option B: Run all docker commands with sudo
```

---

## 2. Start the Stack

```bash
cd /home/aryan/Projects/project-seraph

# Build and start all services
docker compose up --build
```

Expected output:
- Zookeeper starts first
- Kafka starts and becomes healthy
- Topic bootstrap runs and creates 4 topics with 3 partitions each
- 3 workload services start (resnet18-train, distilbert-infer, data-pipeline)
- Aggregator and live-view consumers start
- Kafka UI becomes available

---

## 3. Verification Steps

### 3.1. Check All Services Are Running

```bash
docker compose ps
```

Expected: All services should be in "Up" state except `topic-bootstrap` (which exits after creating topics).

### 3.2. Verify Kafka Topics Created

Open Kafka UI in browser:
```
http://localhost:8080
```

You should see:
- **Topics tab**: 4 topics listed
  - `metrics.resnet18-train`
  - `metrics.distilbert-infer`
  - `metrics.data-pipeline`
  - `metrics.alerts`
- **Each topic**: 3 partitions, replication factor 1
- **Messages**: Click on a topic → View Messages to see live MetricSample JSON

### 3.3. Verify Workloads Are Producing

In Kafka UI, view messages for any `metrics.*` topic. You should see:
- New messages arriving every ~150ms per workload
- JSON structure with all MetricSample fields
- Different `phase` values cycling (e.g. "data_load" → "forward" → "backward")

### 3.4. Verify Live-View Consumer

```bash
docker compose logs -f live-view
```

Expected output:
- Colored lines (blue, yellow, green) for each model
- Format: `[HH:MM:SS.mmm] model_id | phase | CPU | RAM | ...`
- Divider lines every 15 samples
- All 3 models appearing within 10-15 seconds

### 3.5. Verify Aggregator Consumer

```bash
docker compose logs -f aggregator
```

Expected output:
- Lines prefixed with `AGG |` followed by the metric sample
- All 3 models' metrics being logged
- No error messages about Kafka connection

### 3.6. Verify Consumer Groups

In Kafka UI:
- Go to **Consumers** tab
- You should see 2 consumer groups:
  - `mlviz-aggregator` (1 member, subscribed to 3 topics)
  - `mlviz-live-view` (1 member, subscribed to 3 topics)
- Each group should show **lag = 0** or very low (< 100) indicating they're keeping up

---

## 4. Common Issues & Fixes

### Issue: "Permission denied while trying to connect to docker API"

**Fix**: Add your user to docker group or use sudo:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Issue: Kafka UI shows "No topics"

**Fix**: Check if topic-bootstrap completed:
```bash
docker compose logs topic-bootstrap
```

If it failed, manually create topics:
```bash
docker compose exec kafka kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic metrics.resnet18-train \
  --partitions 3 \
  --replication-factor 1
```

### Issue: Live-view or aggregator show "Kafka connection error"

**Fix**: Ensure Kafka is healthy:
```bash
docker compose ps kafka
# Should show "healthy" status

# Check Kafka logs
docker compose logs kafka | tail -50
```

### Issue: LLC shows "n/a" in metrics

**Fix**: This is expected in Docker without additional setup. To enable:
1. The containers need `CAP_SYS_ADMIN` capability (already added in compose)
2. Host kernel must allow perf: `sudo sysctl -w kernel.perf_event_paranoid=2`
3. Or run containers in privileged mode (not recommended for production)

### Issue: No metrics appearing in live-view

**Fix**: Check if workloads are running and producing:
```bash
# Check workload logs
docker compose logs resnet18-train | tail -20
docker compose logs distilbert-infer | tail -20
docker compose logs data-pipeline | tail -20

# Verify in Kafka UI that messages are being produced
```

---

## 5. Performance Verification

### Expected Behavior

Within 15 seconds of startup:
- All 3 model IDs should appear in live-view output
- CPU values should vary by phase (e.g. 200-400% during compute phases)
- RAM should grow from ~40MB to 70-110MB and stabilize
- Throughput should show after first loop completes
- LLC should show 0.00-0.50 range (if perf is working) or "n/a"
- Phase names should cycle through the expected sequences

### Throughput Ranges (Approximate)

- **resnet18-train**: 50-120 images/sec
- **distilbert-infer**: 200-500 tokens/sec (varies by batch/seq_len)
- **data-pipeline**: 300-900 records/sec

---

## 6. Cleanup

Stop all services:
```bash
docker compose down
```

Remove volumes (Kafka data):
```bash
docker compose down -v
```

Remove images:
```bash
docker compose down --rmi all
```

---

## 7. Success Criteria

The integration is successful if:

- ✅ All Docker services start without errors
- ✅ Kafka UI shows 4 topics with 3 partitions each
- ✅ Kafka UI shows live messages in `metrics.*` topics
- ✅ Live-view displays colored metrics from all 3 models
- ✅ Aggregator logs show metrics being consumed
- ✅ Both consumer groups appear in Kafka UI with low lag
- ✅ No crashes or connection errors after 60 seconds of running

---

*Once verified, you can proceed to add InfluxDB, FastAPI, and the React dashboard.*
