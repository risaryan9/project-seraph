"""Core data structure for hardware metrics."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricSample:
    """
    A single hardware metric sample collected from a model process.
    
    Attributes:
        timestamp: Unix epoch milliseconds
        model_id: Identifier for the model (e.g. "resnet18-train")
        phase: Execution phase (e.g. "forward", "backward", "data_load")
        cpu_percent: Process CPU usage percentage
        cpu_system: System-wide CPU usage percentage
        ram_mb: Process RSS memory in megabytes
        ram_system_pct: System-wide RAM usage percentage
        io_read_mb: Delta I/O read in MB since last sample
        io_write_mb: Delta I/O write in MB since last sample
        thread_count: Number of threads in the process
        page_faults_minor: Delta minor page faults since last sample
        page_faults_major: Delta major page faults since last sample
        voluntary_ctx_switches: Delta voluntary context switches since last sample
        llc_miss_rate: Last-level cache miss rate (0.0-1.0), or -1 if unavailable
        throughput: Items processed per second, or -1 if not set
        phase_duration_ms: Duration of the current phase in milliseconds
    """
    
    timestamp: float
    model_id: str
    phase: str
    cpu_percent: float
    cpu_system: float
    ram_mb: float
    ram_system_pct: float
    io_read_mb: float
    io_write_mb: float
    thread_count: int
    page_faults_minor: int
    page_faults_major: int
    voluntary_ctx_switches: int
    llc_miss_rate: float
    throughput: float
    phase_duration_ms: float
    
    def __str__(self) -> str:
        """
        Format metric sample as a single-line human-readable string.
        
        Returns:
            Formatted string with timestamp, model, phase, and key metrics.
        """
        ts = datetime.fromtimestamp(self.timestamp / 1000.0)
        time_str = ts.strftime("%H:%M:%S.%f")[:-3]
        
        llc_str = f"{self.llc_miss_rate:.2f}" if self.llc_miss_rate >= 0 else "n/a"
        
        if self.throughput >= 0:
            tput_str = f"{self.throughput:6.1f}/s"
        else:
            tput_str = "--"
        
        pagefaults = self.page_faults_minor + self.page_faults_major
        
        return (
            f"[{time_str}] {self.model_id:<22} | {self.phase:<16} | "
            f"CPU: {self.cpu_percent:5.1f}% | RAM: {self.ram_mb:6.1f}MB | "
            f"Threads: {self.thread_count:2d} | PgFlt: {pagefaults:4d} | "
            f"LLC: {llc_str:>5} | Tput: {tput_str:>9} | "
            f"Phase: {self.phase_duration_ms:.0f}ms"
        )
