"""Standalone entrypoint for ResNet-18 training workload."""

import logging
import os
import random
import time

import numpy as np
from dotenv import load_dotenv

from mlviz.profiler.agent import MLVizAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Run ResNet-18 training simulation."""
    load_dotenv()
    
    run_seconds = int(os.getenv("RUN_SECONDS", "300"))
    model_id = "resnet18-train"
    
    logger.info(f"Starting {model_id} workload for {run_seconds}s")
    
    agent = MLVizAgent(model_id)
    
    try:
        start_time = time.time()
        batch_size = 32
        iterations = 0
        
        while time.time() - start_time < run_seconds:
            loop_start = time.time()
            
            with agent.phase("data_load"):
                data = np.random.randint(0, 255, (batch_size, 224, 224, 3), dtype=np.uint8)
                data = data.astype(np.float32) / 255.0
                time.sleep(0.02)
            
            with agent.phase("forward"):
                x = np.random.randn(512, 512).astype(np.float32)
                x = x @ x
                x = np.random.randn(256, 256).astype(np.float32)
                x = x @ x
                x = np.random.randn(128, 128).astype(np.float32)
                x = x @ x
                x = np.random.randn(64, 64).astype(np.float32)
                x = x @ x
                time.sleep(0.01)
            
            with agent.phase("backward"):
                grad = np.random.randn(768, 768).astype(np.float32)
                grad = grad @ grad
                grad = np.random.randn(512, 512).astype(np.float32)
                grad = grad @ grad
                grad_accum = np.zeros((1024, 1024), dtype=np.float32)
                time.sleep(0.015)
            
            with agent.phase("optimizer_step"):
                weights = np.random.randn(256, 256).astype(np.float32)
                updates = weights @ weights
                weights = np.random.randn(128, 128).astype(np.float32)
                updates = weights @ weights
                weights -= 0.001 * updates
                time.sleep(0.01)
            
            loop_duration = time.time() - loop_start
            iterations += 1
            throughput = batch_size / loop_duration if loop_duration > 0 else 0
            agent.set_throughput(throughput)
            
            time.sleep(0.05)
        
        logger.info(f"Completed {iterations} iterations")
    
    finally:
        agent.stop()
        logger.info(f"{model_id} workload stopped")


if __name__ == "__main__":
    main()
