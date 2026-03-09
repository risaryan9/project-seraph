"""Standalone entrypoint for DistilBERT inference workload."""

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
    """Run DistilBERT inference simulation."""
    load_dotenv()
    
    run_seconds = int(os.getenv("RUN_SECONDS", "300"))
    model_id = "distilbert-infer"
    
    logger.info(f"Starting {model_id} workload for {run_seconds}s")
    
    agent = MLVizAgent(model_id)
    
    try:
        start_time = time.time()
        iterations = 0
        
        while time.time() - start_time < run_seconds:
            loop_start = time.time()
            
            batch_size = random.choice([1, 2, 4, 8])
            seq_len = random.choice([128, 256, 512])
            
            with agent.phase("data_load"):
                tokens = np.random.randint(0, 30000, (batch_size, seq_len), dtype=np.int32)
                time.sleep(0.01)
            
            with agent.phase("inference"):
                for layer in range(6):
                    batch_seq = batch_size * seq_len
                    
                    q = np.random.randn(batch_seq, 768).astype(np.float32)
                    k = np.random.randn(768, 768).astype(np.float32)
                    q = q @ k
                    
                    k = np.random.randn(batch_seq, 768).astype(np.float32)
                    v = np.random.randn(768, 768).astype(np.float32)
                    k = k @ v
                    
                    v = np.random.randn(batch_seq, 768).astype(np.float32)
                    attn = np.random.randn(768, 768).astype(np.float32)
                    v = v @ attn
                    
                    ffn_in = np.random.randn(batch_seq, 768).astype(np.float32)
                    ffn_w = np.random.randn(768, 3072).astype(np.float32)
                    ffn_out = ffn_in @ ffn_w
                
                time.sleep(0.02)
            
            loop_duration = time.time() - loop_start
            total_tokens = batch_size * seq_len
            throughput = total_tokens / loop_duration if loop_duration > 0 else 0
            agent.set_throughput(throughput)
            
            iterations += 1
            time.sleep(0.08)
        
        logger.info(f"Completed {iterations} iterations")
    
    finally:
        agent.stop()
        logger.info(f"{model_id} workload stopped")


if __name__ == "__main__":
    main()
