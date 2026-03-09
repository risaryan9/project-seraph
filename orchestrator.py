"""Orchestrator for running multiple ML workloads concurrently."""

import multiprocessing as mp
import os
import queue
import signal
import sys

from dotenv import load_dotenv

from mlviz.workloads.runners import (
    run_resnet18_training,
    run_distilbert_inference,
    run_data_pipeline,
)


COLORS = {
    "resnet18-train": "\033[94m",
    "distilbert-infer": "\033[93m",
    "data-pipeline": "\033[92m",
    "reset": "\033[0m",
}

DIVIDER = "─" * 85


def main():
    """
    Main orchestrator entry point.
    
    Spawns 3 model simulation processes and prints their metrics in real time.
    """
    load_dotenv()
    
    run_seconds = int(os.getenv("RUN_SECONDS", "300"))
    
    print("\n" + "=" * 85)
    print("MLViz — ML Hardware Monitor")
    print("3 models starting...")
    print("Press Ctrl+C to stop")
    print("=" * 85 + "\n")
    
    shared_queue = mp.Queue()
    
    processes = [
        mp.Process(
            target=run_resnet18_training,
            args=(shared_queue, run_seconds),
            daemon=True,
            name="resnet18-train"
        ),
        mp.Process(
            target=run_distilbert_inference,
            args=(shared_queue, run_seconds),
            daemon=True,
            name="distilbert-infer"
        ),
        mp.Process(
            target=run_data_pipeline,
            args=(shared_queue, run_seconds),
            daemon=True,
            name="data-pipeline"
        ),
    ]
    
    for proc in processes:
        proc.start()
    
    line_count = 0
    
    try:
        while True:
            try:
                sample = shared_queue.get(timeout=0.5)
                
                color = COLORS.get(sample.model_id, "")
                reset = COLORS["reset"]
                
                print(f"{color}{sample}{reset}")
                
                line_count += 1
                if line_count % 15 == 0:
                    print(DIVIDER)
            
            except queue.Empty:
                alive = any(proc.is_alive() for proc in processes)
                if not alive:
                    break
    
    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...")
        
        for proc in processes:
            if proc.is_alive():
                proc.terminate()
        
        for proc in processes:
            proc.join(timeout=3)
        
        print("All processes stopped. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
