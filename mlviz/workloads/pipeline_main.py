"""Standalone entrypoint for data pipeline workload."""

import logging
import os
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
    """Run data pipeline simulation."""
    load_dotenv()
    
    run_seconds = int(os.getenv("RUN_SECONDS", "300"))
    model_id = "data-pipeline"
    
    logger.info(f"Starting {model_id} workload for {run_seconds}s")
    
    agent = MLVizAgent(model_id)
    
    try:
        start_time = time.time()
        batch_size = 128
        iterations = 0
        
        while time.time() - start_time < run_seconds:
            loop_start = time.time()
            
            with agent.phase("data_load"):
                images = np.random.randint(0, 255, (batch_size, 256, 256, 3), dtype=np.uint8)
                time.sleep(0.015)
            
            with agent.phase("augment"):
                aug1 = np.random.randn(400, 400).astype(np.float32)
                aug1 = aug1 @ aug1
                aug2 = np.random.randn(300, 300).astype(np.float32)
                aug2 = aug2 @ aug2
                
                for i in range(10):
                    slice_data = images[i:i+10, 50:200, 50:200, :]
                
                time.sleep(0.01)
            
            with agent.phase("serialize"):
                serialized = images.copy()
                serialized = serialized.reshape(batch_size, -1)
                time.sleep(0.008)
            
            loop_duration = time.time() - loop_start
            iterations += 1
            throughput = batch_size / loop_duration if loop_duration > 0 else 0
            agent.set_throughput(throughput)
            
            time.sleep(0.03)
        
        logger.info(f"Completed {iterations} iterations")
    
    finally:
        agent.stop()
        logger.info(f"{model_id} workload stopped")


if __name__ == "__main__":
    main()
