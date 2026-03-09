"""MLViz Agent for collecting hardware metrics in model processes."""

import logging
import os
import platform
import queue
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import List, Optional

import psutil
from dotenv import load_dotenv

from .metrics import MetricSample
from .kafka_producer import get_producer

logger = logging.getLogger(__name__)


class MLVizAgent:
    """
    Hardware monitoring agent that runs in a background thread.
    
    Collects CPU, RAM, I/O, cache, and context switch metrics at regular
    intervals without blocking the main model execution thread.
    """
    
    def __init__(self, model_id: str, sample_interval_ms: Optional[int] = None):
        """
        Initialize the MLViz Agent.
        
        Args:
            model_id: Unique identifier for this model
            sample_interval_ms: Sampling interval in milliseconds (default from .env)
        """
        load_dotenv()
        
        self.model_id = model_id
        self.sample_interval_ms = sample_interval_ms or int(
            os.getenv("SAMPLE_INTERVAL_MS", "150")
        )
        self.sample_interval_sec = self.sample_interval_ms / 1000.0
        
        self._current_phase = "idle"
        self._phase_start_time = time.time()
        self._throughput = -1.0
        self._sample_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._kafka_enabled = os.getenv("KAFKA_ENABLED", "true").lower() == "true"
        
        if self._kafka_enabled:
            try:
                self._kafka_producer = get_producer()
            except Exception as e:
                logger.warning(f"Kafka producer init failed: {e}")
                self._kafka_producer = None
        else:
            self._kafka_producer = None
        
        try:
            self._process = psutil.Process(os.getpid())
            self._process.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._process = None
        
        self._io_baseline = None
        self._pagefault_baseline = None
        self._ctx_switch_baseline = None
        
        if self._process:
            try:
                io_counters = self._process.io_counters()
                self._io_baseline = {
                    "read_bytes": io_counters.read_bytes,
                    "write_bytes": io_counters.write_bytes,
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
            
            try:
                mem_info = self._process.memory_full_info()
                self._pagefault_baseline = {
                    "minor": getattr(mem_info, "num_page_faults", 0),
                    "major": getattr(mem_info, "pageins", 0),
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
            
            try:
                ctx = self._process.num_ctx_switches()
                self._ctx_switch_baseline = {
                    "voluntary": ctx.voluntary,
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        
        self._collector_thread = threading.Thread(
            target=self._collect_loop,
            daemon=True,
            name=f"MLVizAgent-{model_id}"
        )
        self._collector_thread.start()
    
    def _collect_loop(self):
        """Background thread that collects metrics at regular intervals."""
        while not self._stop_event.is_set():
            try:
                sample = self._collect_sample()
                if sample:
                    self._sample_queue.put(sample)
                    
                    if self._kafka_producer:
                        try:
                            self._kafka_producer.send_metric(self.model_id, sample)
                        except Exception as e:
                            logger.debug(f"Kafka send failed: {e}")
            except Exception:
                pass
            
            time.sleep(self.sample_interval_sec)
    
    def _collect_sample(self) -> Optional[MetricSample]:
        """
        Collect a single metric sample.
        
        Returns:
            MetricSample if collection succeeded, None otherwise.
        """
        if not self._process:
            return None
        
        timestamp = time.time() * 1000.0
        
        try:
            cpu_percent = self._process.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cpu_percent = 0.0
        
        try:
            cpu_system = psutil.cpu_percent()
        except Exception:
            cpu_system = 0.0
        
        try:
            mem_info = self._process.memory_info()
            ram_mb = mem_info.rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            ram_mb = 0.0
        
        try:
            ram_system_pct = psutil.virtual_memory().percent
        except Exception:
            ram_system_pct = 0.0
        
        io_read_mb = 0.0
        io_write_mb = 0.0
        try:
            io_counters = self._process.io_counters()
            if self._io_baseline:
                io_read_mb = (
                    io_counters.read_bytes - self._io_baseline["read_bytes"]
                ) / (1024 * 1024)
                io_write_mb = (
                    io_counters.write_bytes - self._io_baseline["write_bytes"]
                ) / (1024 * 1024)
                self._io_baseline = {
                    "read_bytes": io_counters.read_bytes,
                    "write_bytes": io_counters.write_bytes,
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
        
        try:
            thread_count = self._process.num_threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            thread_count = 0
        
        page_faults_minor = 0
        page_faults_major = 0
        try:
            mem_full = self._process.memory_full_info()
            current_minor = getattr(mem_full, "num_page_faults", 0)
            current_major = getattr(mem_full, "pageins", 0)
            
            if self._pagefault_baseline:
                page_faults_minor = current_minor - self._pagefault_baseline["minor"]
                page_faults_major = current_major - self._pagefault_baseline["major"]
                self._pagefault_baseline = {
                    "minor": current_minor,
                    "major": current_major,
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
        
        voluntary_ctx_switches = 0
        try:
            ctx = self._process.num_ctx_switches()
            if self._ctx_switch_baseline:
                voluntary_ctx_switches = (
                    ctx.voluntary - self._ctx_switch_baseline["voluntary"]
                )
                self._ctx_switch_baseline = {"voluntary": ctx.voluntary}
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
        
        llc_miss_rate = self._get_llc_miss_rate()
        
        phase_duration_ms = (time.time() - self._phase_start_time) * 1000.0
        
        return MetricSample(
            timestamp=timestamp,
            model_id=self.model_id,
            phase=self._current_phase,
            cpu_percent=cpu_percent,
            cpu_system=cpu_system,
            ram_mb=ram_mb,
            ram_system_pct=ram_system_pct,
            io_read_mb=io_read_mb,
            io_write_mb=io_write_mb,
            thread_count=thread_count,
            page_faults_minor=page_faults_minor,
            page_faults_major=page_faults_major,
            voluntary_ctx_switches=voluntary_ctx_switches,
            llc_miss_rate=llc_miss_rate,
            throughput=self._throughput,
            phase_duration_ms=phase_duration_ms,
        )
    
    def _get_llc_miss_rate(self) -> float:
        """
        Get last-level cache miss rate via perf stat.
        
        Returns:
            Cache miss rate (0.0-1.0) or -1.0 if unavailable.
        """
        if platform.system() != "Linux":
            return -1.0
        
        if not self._process:
            return -1.0
        
        try:
            pid = self._process.pid
            result = subprocess.run(
                ["perf", "stat", "-e", "cache-misses,cache-references", 
                 "-p", str(pid), "sleep", "0.05"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            
            stderr = result.stderr
            
            cache_misses = None
            cache_references = None
            
            for line in stderr.split("\n"):
                line_clean = line.replace(",", "").strip()
                if "cache-misses" in line:
                    parts = line_clean.split()
                    if parts and parts[0].isdigit():
                        cache_misses = int(parts[0])
                elif "cache-references" in line:
                    parts = line_clean.split()
                    if parts and parts[0].isdigit():
                        cache_references = int(parts[0])
            
            if cache_misses is not None and cache_references is not None and cache_references > 0:
                return cache_misses / cache_references
            
            return -1.0
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, 
                FileNotFoundError, PermissionError, Exception):
            return -1.0
    
    @contextmanager
    def phase(self, phase_name: str):
        """
        Context manager for annotating execution phases.
        
        Args:
            phase_name: Name of the phase (e.g. "forward", "backward")
            
        Example:
            with agent.phase("forward"):
                model.forward()
        """
        self._current_phase = phase_name
        self._phase_start_time = time.time()
        try:
            yield
        finally:
            pass
    
    def set_throughput(self, throughput: float):
        """
        Set the current throughput metric.
        
        Args:
            throughput: Items processed per second
        """
        self._throughput = throughput
    
    def drain(self) -> List[MetricSample]:
        """
        Retrieve all queued samples and clear the queue.
        
        Returns:
            List of MetricSample objects collected since last drain.
        """
        samples = []
        while True:
            try:
                sample = self._sample_queue.get_nowait()
                samples.append(sample)
            except queue.Empty:
                break
        return samples
    
    def stop(self):
        """Stop the background collection thread and flush Kafka."""
        self._stop_event.set()
        if self._collector_thread.is_alive():
            self._collector_thread.join(timeout=2.0)
        
        if self._kafka_producer:
            try:
                self._kafka_producer.flush()
            except Exception:
                pass
