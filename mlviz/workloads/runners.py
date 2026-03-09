"""Simulated ML workload runners."""

import multiprocessing as mp
import random
import time

import numpy as np

from mlviz.profiler.agent import MLVizAgent


def run_resnet18_training(shared_queue: mp.Queue, run_seconds: int):
    """
    Simulate ResNet-18 training workload.
    
    Phases: data_load → forward → backward → optimizer_step (repeat)
    
    Args:
        shared_queue: Multiprocessing queue for sending samples to orchestrator
        run_seconds: Duration to run the simulation
    """
    agent = MLVizAgent("resnet18-train")
    
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
            
            samples = agent.drain()
            for sample in samples:
                shared_queue.put(sample)
            
            time.sleep(0.05)
    
    finally:
        agent.stop()


def run_distilbert_inference(shared_queue: mp.Queue, run_seconds: int):
    """
    Simulate DistilBERT inference workload.
    
    Phases: data_load → inference (repeat)
    Variable batch size and sequence length.
    
    Args:
        shared_queue: Multiprocessing queue for sending samples to orchestrator
        run_seconds: Duration to run the simulation
    """
    agent = MLVizAgent("distilbert-infer")
    
    try:
        start_time = time.time()
        
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
            
            samples = agent.drain()
            for sample in samples:
                shared_queue.put(sample)
            
            time.sleep(0.08)
    
    finally:
        agent.stop()


def run_data_pipeline(shared_queue: mp.Queue, run_seconds: int):
    """
    Simulate data pipeline workload.
    
    Phases: data_load → augment → serialize (repeat)
    
    Args:
        shared_queue: Multiprocessing queue for sending samples to orchestrator
        run_seconds: Duration to run the simulation
    """
    agent = MLVizAgent("data-pipeline")
    
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
            
            samples = agent.drain()
            for sample in samples:
                shared_queue.put(sample)
            
            time.sleep(0.03)
    
    finally:
        agent.stop()
