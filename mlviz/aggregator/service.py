"""Kafka consumer service for aggregating metrics."""

import logging
import os
import signal
import sys
import time
from typing import List, Optional

from kafka import KafkaConsumer
from kafka.errors import KafkaError
from dotenv import load_dotenv

from mlviz.profiler.metrics import MetricSample

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
    INFLUX_AVAILABLE = True
except ImportError:
    INFLUX_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("influxdb-client not installed; InfluxDB writes disabled")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class AggregatorService:
    """
    Kafka consumer that aggregates metrics from all model topics.
    
    Consumes from metrics.* topics, deserializes MetricSample data,
    and writes to InfluxDB in batches.
    """
    
    BATCH_SIZE = 50
    FLUSH_INTERVAL_MS = 500
    
    def __init__(self):
        """Initialize the aggregator service."""
        load_dotenv()
        
        self.broker = os.getenv("KAFKA_BROKER", "localhost:9092")
        self.group_id = "mlviz-aggregator"
        self.topics = [
            "metrics.resnet18-train",
            "metrics.distilbert-infer",
            "metrics.data-pipeline",
        ]
        
        self.consumer = None
        self.running = False
        
        # InfluxDB configuration
        self.influx_url = os.getenv("INFLUX_URL")
        self.influx_token = os.getenv("INFLUX_TOKEN")
        self.influx_org = os.getenv("INFLUX_ORG", "mlviz")
        self.influx_bucket = os.getenv("INFLUX_BUCKET", "metrics")
        
        self.influx_client: Optional[InfluxDBClient] = None
        self.write_api = None
        self.influx_enabled = False
        
        # Batch buffer
        self.buffer: List[MetricSample] = []
        self.last_flush = time.time()
    
    def start(self):
        """Start consuming from Kafka."""
        logger.info(f"Aggregator connecting to Kafka at {self.broker}")
        logger.info(f"Consumer group: {self.group_id}")
        logger.info(f"Subscribing to topics: {self.topics}")
        
        # Initialize InfluxDB if configured
        if self.influx_url and INFLUX_AVAILABLE:
            try:
                self.influx_client = InfluxDBClient(
                    url=self.influx_url,
                    token=self.influx_token,
                    org=self.influx_org
                )
                self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
                self.influx_enabled = True
                logger.info(f"InfluxDB client initialized: {self.influx_url}")
                logger.info(f"Writing to bucket: {self.influx_bucket}, org: {self.influx_org}")
                logger.info(f"Batch config: size={self.BATCH_SIZE}, interval={self.FLUSH_INTERVAL_MS}ms")
            except Exception as e:
                logger.error(f"Failed to initialize InfluxDB client: {e}")
                logger.info("Continuing without InfluxDB writes")
        elif not self.influx_url:
            logger.info("INFLUX_URL not set; running in log-only mode")
        elif not INFLUX_AVAILABLE:
            logger.warning("influxdb-client not available; install with: pip install influxdb-client")
        
        try:
            self.consumer = KafkaConsumer(
                *self.topics,
                bootstrap_servers=[self.broker],
                group_id=self.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: m.decode("utf-8"),
            )
            
            logger.info("Aggregator started successfully")
            self.running = True
            
            for message in self.consumer:
                if not self.running:
                    break
                
                try:
                    sample = MetricSample.from_json(message.value)
                    self._process_sample(sample)
                except Exception as e:
                    logger.error(f"Failed to process message: {e}")
        
        except KafkaError as e:
            logger.error(f"Kafka error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.stop()
    
    def _process_sample(self, sample: MetricSample):
        """
        Process a single metric sample.
        
        Args:
            sample: MetricSample to process
        """
        if self.influx_enabled:
            self.buffer.append(sample)
            self._maybe_flush()
        else:
            logger.info(f"AGG | {sample}")
    
    def _maybe_flush(self):
        """Check flush conditions and flush if needed."""
        if not self.buffer:
            return
        
        current_time = time.time()
        time_since_flush = (current_time - self.last_flush) * 1000
        
        should_flush = (
            len(self.buffer) >= self.BATCH_SIZE or
            time_since_flush >= self.FLUSH_INTERVAL_MS
        )
        
        if should_flush:
            self._flush()
    
    def _flush(self):
        """Flush buffered samples to InfluxDB."""
        if not self.buffer or not self.influx_enabled:
            return
        
        try:
            points = []
            for sample in self.buffer:
                point = (
                    Point("hardware_sample")
                    .tag("model_id", sample.model_id)
                    .tag("phase", sample.phase)
                    .field("cpu_percent", sample.cpu_percent)
                    .field("cpu_system", sample.cpu_system)
                    .field("ram_mb", sample.ram_mb)
                    .field("ram_system_pct", sample.ram_system_pct)
                    .field("io_read_mb", sample.io_read_mb)
                    .field("io_write_mb", sample.io_write_mb)
                    .field("thread_count", sample.thread_count)
                    .field("page_faults_minor", sample.page_faults_minor)
                    .field("page_faults_major", sample.page_faults_major)
                    .field("voluntary_ctx_switches", sample.voluntary_ctx_switches)
                    .field("llc_miss_rate", sample.llc_miss_rate)
                    .field("throughput", sample.throughput)
                    .field("phase_duration_ms", sample.phase_duration_ms)
                    .time(int(sample.timestamp * 1_000_000), WritePrecision.NS)
                )
                points.append(point)
            
            self.write_api.write(bucket=self.influx_bucket, record=points)
            
            logger.info(f"Flushed {len(points)} points to InfluxDB")
            
            self.buffer.clear()
            self.last_flush = time.time()
            
        except Exception as e:
            logger.error(f"Failed to flush to InfluxDB: {e}")
            self.buffer.clear()
    
    def stop(self):
        """Stop the consumer."""
        self.running = False
        
        # Flush any remaining buffered samples
        if self.buffer:
            logger.info(f"Flushing {len(self.buffer)} remaining samples before shutdown")
            self._flush()
        
        # Close Kafka consumer
        if self.consumer:
            try:
                self.consumer.close()
                logger.info("Kafka consumer closed")
            except Exception as e:
                logger.error(f"Error closing consumer: {e}")
        
        # Close InfluxDB client
        if self.influx_client:
            try:
                if self.write_api:
                    self.write_api.close()
                self.influx_client.close()
                logger.info("InfluxDB client closed")
            except Exception as e:
                logger.error(f"Error closing InfluxDB client: {e}")
        
        logger.info("Aggregator stopped")


def main():
    """Main entry point for aggregator service."""
    aggregator = AggregatorService()
    
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        aggregator.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    aggregator.start()


if __name__ == "__main__":
    main()
