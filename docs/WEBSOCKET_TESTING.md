# WebSocket Live Metrics Testing Guide

Complete guide for testing the Seraph WebSocket endpoint for real-time metrics streaming.

## Overview

The FastAPI backend exposes a WebSocket endpoint at `/ws/live` that streams live hardware metrics from Kafka to connected clients. This enables real-time dashboards with sub-100ms latency.

**WebSocket URL**: `ws://localhost:8000/ws/live`

## Architecture

```
Workloads → Kafka → Backend Kafka Consumer (thread) → asyncio.Queue → Broadcast Task → WebSocket Clients
```

- **Kafka Consumer**: Runs in a background thread, consumes from `metrics.*` topics
- **Consumer Group**: `mlviz-ws-bridge` (separate from aggregator and live-view)
- **Bridge**: Thread-safe queue pushes messages to asyncio event loop
- **Broadcast**: Asyncio task sends each message to all connected WebSocket clients
- **Message Format**: JSON object with all MetricSample fields

---

## Testing Methods

### 1. Postman (Recommended)

**Step-by-step:**

1. **Open Postman** and create a new request

2. **Change request type to WebSocket**:
   - Click the dropdown next to the URL bar
   - Select **WebSocket Request**

3. **Enter URL**:
   ```
   ws://localhost:8000/ws/live
   ```

4. **Click Connect**:
   - Status changes to "Connected"
   - You'll see a welcome message:
     ```json
     {
       "type": "connected",
       "message": "Live metrics stream connected"
     }
     ```

5. **View Messages**:
   - Messages appear in the **Messages** pane
   - Each message is a complete metric sample
   - Messages arrive every ~150ms (3 workloads producing metrics)

6. **Filter/Search**:
   - Use Postman's search to filter by `model_id` or `phase`
   - Example: search for `"resnet18-train"` to see only ResNet metrics

7. **Disconnect**:
   - Click **Disconnect** button
   - Connection closes gracefully

**Expected Message Example**:
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

---

### 2. Browser Console (JavaScript)

**Open browser console** (F12) and paste:

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/live');

// Connection opened
ws.onopen = () => {
  console.log('✅ Connected to live metrics stream');
};

// Receive messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'connected') {
    console.log('📡 Server:', data.message);
  } else {
    // Display metric sample
    console.log(
      `[${data.model_id}] ${data.phase}: ` +
      `CPU=${data.cpu_percent.toFixed(1)}% ` +
      `RAM=${data.ram_mb.toFixed(1)}MB ` +
      `Throughput=${data.throughput.toFixed(1)}/s`
    );
  }
};

// Handle errors
ws.onerror = (error) => {
  console.error('❌ WebSocket error:', error);
};

// Connection closed
ws.onclose = () => {
  console.log('🔌 Disconnected from live metrics stream');
};

// To disconnect manually:
// ws.close();
```

**Advanced: Count messages by model**:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/live');
const counts = {};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.model_id) {
    counts[data.model_id] = (counts[data.model_id] || 0) + 1;
    console.log('Message counts:', counts);
  }
};
```

---

### 3. Python (websockets library)

**Install websockets**:
```bash
pip install websockets
```

**Basic receiver** (`test_websocket.py`):
```python
import asyncio
import websockets
import json

async def receive_metrics():
    uri = "ws://localhost:8000/ws/live"
    
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to live metrics stream")
        
        try:
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                
                if data.get("type") == "connected":
                    print(f"📡 Server: {data['message']}")
                else:
                    print(
                        f"[{data['model_id']}] {data['phase']}: "
                        f"CPU={data['cpu_percent']:.1f}% "
                        f"RAM={data['ram_mb']:.1f}MB"
                    )
        except websockets.exceptions.ConnectionClosed:
            print("🔌 Connection closed")
        except KeyboardInterrupt:
            print("\n👋 Disconnecting...")

if __name__ == "__main__":
    asyncio.run(receive_metrics())
```

**Run**:
```bash
python test_websocket.py
```

**Press Ctrl+C** to stop.

---

### 4. wscat (Command Line)

**Install wscat**:
```bash
npm install -g wscat
```

**Connect**:
```bash
wscat -c ws://localhost:8000/ws/live
```

**Output**:
```
Connected (press CTRL+C to quit)
< {"type":"connected","message":"Live metrics stream connected"}
< {"timestamp":1710374567890.123,"model_id":"resnet18-train","phase":"forward",...}
< {"timestamp":1710374567940.456,"model_id":"distilbert-infer","phase":"inference",...}
...
```

**Disconnect**: Press **Ctrl+C**

---

### 5. curl (with websocat)

**Install websocat**:
```bash
# macOS
brew install websocat

# Linux
cargo install websocat
```

**Connect**:
```bash
websocat ws://localhost:8000/ws/live
```

---

## Verifying the Stack

Before testing WebSocket, ensure all services are running:

### 1. Check Docker Services
```bash
docker compose ps
```

Expected: All services `Up` except `topic-bootstrap` (exits after setup).

### 2. Check Backend Logs
```bash
docker compose logs backend | tail -20
```

Look for:
```
Kafka consumer thread started for WebSocket bridge
WebSocket broadcast task started
```

### 3. Check Kafka Consumer
```bash
docker compose logs backend | grep "Kafka consumer"
```

Should see:
```
Starting Kafka consumer for WebSocket bridge at kafka:9092
Kafka consumer for WebSocket bridge started successfully
```

### 4. Verify Workloads Are Producing
```bash
docker compose logs aggregator | grep "Flushed"
```

Should see regular flush messages:
```
Flushed 50 points to InfluxDB
```

---

## Troubleshooting

### No Messages Received

**Symptom**: WebSocket connects but no metric messages arrive.

**Checks**:

1. **Verify workloads are running**:
   ```bash
   docker compose ps | grep -E "resnet|distilbert|pipeline"
   ```
   All should be `Up`.

2. **Check if workloads finished**:
   Workloads run for 300 seconds by default. Restart:
   ```bash
   docker compose restart resnet18-train distilbert-infer data-pipeline
   ```

3. **Check Kafka consumer in backend**:
   ```bash
   docker compose logs backend | grep -i kafka
   ```
   Look for errors.

4. **Verify Kafka is healthy**:
   ```bash
   docker compose logs kafka | tail -20
   ```

5. **Check consumer group**:
   ```bash
   docker compose exec kafka kafka-consumer-groups \
     --bootstrap-server localhost:9092 \
     --describe --group mlviz-ws-bridge
   ```

### Connection Refused

**Symptom**: Cannot connect to `ws://localhost:8000/ws/live`.

**Fixes**:

1. **Check backend is running**:
   ```bash
   docker compose ps backend
   ```

2. **Check port 8000**:
   ```bash
   curl http://localhost:8000/health
   ```

3. **Check firewall**:
   ```bash
   # Linux
   sudo ufw status
   
   # macOS
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
   ```

4. **Verify URL scheme**:
   - Use `ws://` not `wss://` (no TLS in development)
   - Use `localhost` not `127.0.0.1` if CORS is configured for localhost

### Connection Drops

**Symptom**: WebSocket connects then immediately disconnects.

**Checks**:

1. **Backend logs**:
   ```bash
   docker compose logs backend | grep -i websocket
   ```

2. **Network issues**:
   - Check Docker network: `docker network inspect mlviz-network`
   - Restart backend: `docker compose restart backend`

3. **Client timeout**:
   Some clients have short timeouts. The server sends a welcome message immediately, so this is rare.

### Slow Message Rate

**Symptom**: Messages arrive slower than expected (should be ~150ms intervals).

**Causes**:

1. **System load**: Check CPU/RAM on host
2. **Docker resources**: Increase Docker memory/CPU limits
3. **Kafka lag**: Check consumer lag with `kafka-consumer-groups`

---

## Message Statistics

With 3 workloads producing metrics every ~150ms:

- **Expected rate**: ~20 messages/second (6-7 per workload)
- **Message size**: ~300-400 bytes per JSON message
- **Bandwidth**: ~6-8 KB/s per client
- **Models**: `resnet18-train`, `distilbert-infer`, `data-pipeline`
- **Phases**: Varies by model (forward, backward, data_load, inference, etc.)

---

## Production Considerations

For production deployments:

1. **Authentication**: Add token-based auth to WebSocket endpoint
2. **Rate limiting**: Limit connections per IP or user
3. **Reconnection**: Implement exponential backoff in clients
4. **Compression**: Enable WebSocket compression for bandwidth savings
5. **Load balancing**: Use sticky sessions if deploying multiple backend instances
6. **Monitoring**: Track connected clients, message rate, queue depth
7. **Backpressure**: Handle slow clients (current implementation drops messages to slow clients)

---

## Example: React Hook

For React dashboard (future):

```typescript
import { useEffect, useState } from 'react';

interface MetricSample {
  timestamp: number;
  model_id: string;
  phase: string;
  cpu_percent: number;
  ram_mb: number;
  // ... other fields
}

export function useLiveMetrics() {
  const [metrics, setMetrics] = useState<MetricSample[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws/live');

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type !== 'connected') {
        setMetrics((prev) => {
          const updated = [...prev, data];
          // Keep last 60 seconds (assuming ~20 msg/s = 1200 samples)
          return updated.slice(-1200);
        });
      }
    };

    return () => ws.close();
  }, []);

  return { metrics, connected };
}
```

---

## Summary

The WebSocket endpoint provides real-time access to hardware metrics with minimal latency. Use Postman for quick testing, browser console for debugging, or Python for automated monitoring. The endpoint is production-ready for React dashboards and other real-time applications.
