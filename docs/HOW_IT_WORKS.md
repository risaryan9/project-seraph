# How MLViz Works — For Hackathon Judges

A short, judge-friendly explanation of how the ML hardware monitoring system works: first in simple terms, then with a bit more technical detail.

---

## Part 1: Simple Explanation

**What problem does this solve?**  
When you run several ML models on the same machine, you see things like “CPU 90%” but you don’t know *which* model is using it or *when* (e.g. during data loading vs. training step). This project **attributes** CPU, RAM, I/O, and cache usage to **each model** and to **each phase** of execution (data load, forward pass, backward pass, etc.).

**How does it work in one sentence?**  
Each model process runs a small **monitoring agent** in the background that, every 150 ms, reads that process’s resource usage from the OS, tags it with the current “phase” (e.g. forward, backward), and sends those numbers to a central place that can display or store them.

**The flow in three steps:**

1. **Orchestrator** starts three separate **processes** (simulating three different ML workloads).
2. Inside each process, an **MLViz Agent** runs in a **background thread**. It wakes up every 150 ms, asks the OS “how much CPU/RAM/I/O does *this* process use right now?”, and puts that into a **metric sample** labeled with the current phase.
3. The **workload** (e.g. “ResNet training”) tells the agent “I’m in the forward pass now” or “I’m in data load” using a **phase** context manager. After each loop it **drains** the collected samples and puts them on a **shared queue**. The **orchestrator** reads from that queue and prints them to the terminal (with colors per model).

So: **separate OS processes** = separate PIDs = per-model attribution; **phase annotations** = we know *when* (which stage) the resources were used; **background thread** = monitoring never blocks the actual model code.

---

## Part 2: Slightly More Detail

### Overall architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR (main process)                                              │
│  - Creates one multiprocessing.Queue (shared_queue)                        │
│  - Spawns 3 child processes (resnet18-train, distilbert-infer,            │
│    data-pipeline), each gets the same queue                               │
│  - Loop: shared_queue.get(timeout=0.5) → print(sample) with color        │
│  - On Ctrl+C: terminate all children, join, exit                          │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Process 1     │    │ Process 2     │    │ Process 3     │
│ resnet18-train│    │ distilbert-   │    │ data-pipeline │
│               │    │ infer         │    │               │
│ ┌───────────┐ │    │ ┌───────────┐ │    │ ┌───────────┐ │
│ │ MLViz     │ │    │ │ MLViz     │ │    │ │ MLViz     │ │
│ │ Agent     │ │    │ │ Agent     │ │    │ │ Agent     │ │
│ │ (thread)  │ │    │ │ (thread)  │ │    │ │ (thread)  │ │
│ └─────┬─────┘ │    │ └─────┬─────┘ │    │ └─────┬─────┘ │
│       │       │    │       │       │    │       │       │
│       │drain()│    │       │drain()│    │       │drain()│
│       ▼       │    │       ▼       │    │       ▼       │
│  samples ─────┼────┼───────────────┼────┼──► shared_queue ──► orchestrator
│               │    │               │    │               │
│  workload     │    │  workload     │    │  workload     │
│  loop +       │    │  loop +       │    │  loop +       │
│  phase()      │    │  phase()      │    │  phase()      │
└───────────────┘    └───────────────┘    └───────────────┘
```

- **One process per model** → the OS gives each a different **PID**. We only ever read metrics for *that* PID, so all numbers are **per model**.
- **One agent per process** → each agent uses `psutil.Process(os.getpid())` so it only sees its own process.
- **Shared queue** → the only cross-process channel in this step. Workers put `MetricSample` objects on it; the orchestrator consumes and prints. No Kafka/DB in this version.

### What the agent does (low level)

- **On init:**  
  - Loads `.env` (e.g. `SAMPLE_INTERVAL_MS=150`).  
  - Gets `psutil.Process(os.getpid())` and calls `cpu_percent()` once (first call is 0, so we “warm up”).  
  - Reads initial baselines for I/O bytes, page faults, and context switches from `/proc` (via psutil) so we can report **deltas** later.  
  - Starts a **daemon thread** that runs `_collect_loop`.

- **Collect loop (every 150 ms):**  
  - **CPU:** `process.cpu_percent()` (process) and `psutil.cpu_percent()` (system).  
  - **RAM:** `process.memory_info().rss` (process) and `psutil.virtual_memory().percent` (system).  
  - **I/O:** `process.io_counters()`; subtract previous read/write bytes to get **delta** read/write in MB.  
  - **Threads:** `process.num_threads()`.  
  - **Page faults:** `process.memory_full_info()` → minor/major fault counters; subtract previous values for **delta** minor/major.  
  - **Context switches:** `process.num_ctx_switches().voluntary`; again **delta** vs previous.  
  - **LLC (Linux only):** `subprocess.run(["perf", "stat", "-e", "cache-misses,cache-references", "-p", str(pid), "sleep", "0.05"], timeout=0.5)`, parse stderr, compute `misses/references`; on error or non-Linux return -1 (shown as “n/a”).  
  - Builds a **MetricSample** (timestamp, model_id, phase, all the above, throughput, phase_duration_ms) and puts it in an in-process **queue.Queue**.

- **Phase and throughput:**  
  - The workload code uses `with agent.phase("forward"): ...`. That just sets `_current_phase` and `_phase_start_time`; each sample then carries that phase and phase duration.  
  - After each loop the workload calls `agent.set_throughput(images_per_sec)` (or tokens/sec, records/sec). The next samples get that value until the next update.

- **Drain:**  
  - `agent.drain()` returns all `MetricSample` objects currently in the queue and clears it. The **workload** calls `drain()` after each loop, then `shared_queue.put(sample)` for each sample so the **orchestrator** can print them.

All psutil and perf calls are wrapped in try/except so a single failure (e.g. permission, NoSuchProcess) doesn’t kill the collector thread; we fill in 0 or -1 as appropriate.

### Why this gives “phase-attributed” metrics

- The **model code** (or simulation) is the only thing that knows “I’m in forward pass now.” It wraps that code in `with agent.phase("forward"): ...`.
- The **agent** doesn’t run the model; it only reads OS metrics and stores the **current** phase name and phase start time. So every sample is tagged with the phase that was active at that moment.
- Result: you see lines like `resnet18-train | forward | CPU: 320%` — meaning “during the forward phase, this process was using 320% CPU.”

### Data flow summary

| Step | Where | What happens |
|------|--------|--------------|
| 1 | Orchestrator | Creates `mp.Queue()`, starts 3 `mp.Process` with the queue and `run_seconds`. |
| 2 | Each process | Creates its own `MLVizAgent(model_id)`. Agent starts daemon thread, reads baselines. |
| 3 | Agent thread | Every 150 ms: read OS metrics for this PID, build MetricSample, put in internal queue. |
| 4 | Workload | Runs phases with `agent.phase("...")`, sets throughput, then `drain()` → put each sample on shared_queue. |
| 5 | Orchestrator | `shared_queue.get(timeout=0.5)` → print colored `str(sample)`. Every 15 lines print a divider. |

So the only “magic” is: **per-PID metrics** (psutil + optional perf) + **phase labels** (set by the model) + **one background thread per process** that never blocks the main workload loop. Everything else is just moving `MetricSample` objects from the agent queue to the shared queue to the terminal.

---

*You can use this doc as a cheat sheet when explaining the system to judges: start with Part 1, then use Part 2 for “how does it actually work under the hood?”*
