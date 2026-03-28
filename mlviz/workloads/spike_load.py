"""Short, high-intensity CPU bursts for a given model_id — metrics flow through Kafka like other workloads."""

from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

import numpy as np
from dotenv import load_dotenv

from mlviz.profiler.agent import MLVizAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _saturation_until(deadline: float, n: int, dim: int) -> None:
    """Burn CPU with large matmuls until wall-clock deadline (shared across threads)."""

    def worker() -> None:
        rng = np.random.default_rng()
        while time.time() < deadline:
            a = rng.standard_normal((dim, dim), dtype=np.float32)
            b = rng.standard_normal((dim, dim), dtype=np.float32)
            a = a @ b

    if n <= 1:
        worker()
        return
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(worker) for _ in range(n)]
        wait(futures)


def _segment(agent: MLVizAgent, phase: str, seg_end: float, workers: int, dim: int) -> None:
    if time.time() >= seg_end:
        return
    with agent.phase(phase):
        _saturation_until(seg_end, workers, dim)


def _burst_resnet(agent: MLVizAgent, burst_end: float, workers: int, dim: int) -> None:
    while time.time() < burst_end:
        t = time.time()
        _segment(agent, "data_load", min(t + 0.35, burst_end), max(1, workers // 2), dim)
        _segment(agent, "forward", min(time.time() + 0.5, burst_end), workers, dim + 128)
        _segment(agent, "backward", min(time.time() + 0.55, burst_end), workers, dim + 128)
        _segment(agent, "optimizer_step", min(time.time() + 0.35, burst_end), workers, dim)


def _burst_distilbert(agent: MLVizAgent, burst_end: float, workers: int, dim: int) -> None:
    while time.time() < burst_end:
        _segment(agent, "data_load", min(time.time() + 0.25, burst_end), max(1, workers // 2), dim // 2)
        _segment(agent, "inference", min(time.time() + 1.2, burst_end), workers, dim + 256)


def _burst_pipeline(agent: MLVizAgent, burst_end: float, workers: int, dim: int) -> None:
    while time.time() < burst_end:
        _segment(agent, "data_load", min(time.time() + 0.3, burst_end), max(1, workers // 2), dim // 2)
        _segment(agent, "augment", min(time.time() + 0.6, burst_end), workers, dim)
        _segment(agent, "serialize", min(time.time() + 0.35, burst_end), workers, dim // 2)


_BURSTERS: dict[str, Callable[[MLVizAgent, float, int, int], None]] = {
    "resnet18-train": _burst_resnet,
    "distilbert-infer": _burst_distilbert,
    "data-pipeline": _burst_pipeline,
}


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Emit sharp metric spikes for a model_id via MLVizAgent + Kafka.")
    parser.add_argument(
        "--model",
        default=os.getenv("SPIKE_MODEL_ID", "resnet18-train"),
        help="model_id tag (default: resnet18-train). Must match dashboard filters.",
    )
    parser.add_argument(
        "--burst-seconds",
        type=float,
        default=float(os.getenv("SPIKE_BURST_SECONDS", "45")),
        help="Length of each high-CPU burst (default: 45).",
    )
    parser.add_argument(
        "--cool-seconds",
        type=float,
        default=float(os.getenv("SPIKE_COOL_SECONDS", "20")),
        help="Idle phase between bursts (default: 20).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=int(os.getenv("SPIKE_CYCLES", "4")),
        help="Number of burst/cool cycles (default: 4).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("SPIKE_WORKERS", "8")),
        help="Thread count for matmul saturation (default: 8).",
    )
    parser.add_argument(
        "--matrix-dim",
        type=int,
        default=int(os.getenv("SPIKE_MATRIX_DIM", "896")),
        help="Base square matrix dimension for matmul (default: 896).",
    )
    args = parser.parse_args()

    model_id = args.model.strip()
    burster = _BURSTERS.get(model_id)
    if burster is None:
        logger.warning("Unknown model %r — using generic single-phase spike", model_id)
        burster = lambda a, end, w, d: _segment(a, "spike", end, w, d + 256)

    sample_ms = int(os.getenv("SAMPLE_INTERVAL_MS", "400"))
    agent = MLVizAgent(model_id, sample_interval_ms=sample_ms)

    try:
        for i in range(args.cycles):
            logger.info(
                "Cycle %s/%s: BURST %.0fs for model_id=%s",
                i + 1,
                args.cycles,
                args.burst_seconds,
                model_id,
            )
            burst_end = time.time() + args.burst_seconds
            loop_start = time.time()
            burster(agent, burst_end, max(1, args.workers), max(256, args.matrix_dim))
            elapsed = time.time() - loop_start
            agent.set_throughput(10_000.0 / max(elapsed, 0.001))

            logger.info("Cycle %s/%s: COOL %.0fs", i + 1, args.cycles, args.cool_seconds)
            cool_end = time.time() + args.cool_seconds
            agent.set_throughput(0.0)
            with agent.phase("idle"):
                while time.time() < cool_end:
                    time.sleep(0.05)

        logger.info("Spike load finished for %s", model_id)
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
