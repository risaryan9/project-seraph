"""Kafka consumer service for aggregating metrics."""

import logging
import os
import signal
import sys

from kafka import KafkaConsumer
from kafka.errors import KafkaError
from dotenv import load_dotenv

from mlviz.profiler.metrics import MetricSample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class AggregatorService:
    """
    Kafka consumer that aggregates metrics from all model topics.
    
    Consumes from metrics.* topics, deserializes MetricSample data,
    and processes it (currently logs; later writes to InfluxDB).
    """
    
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
    
    def start(self):
        """Start consuming from Kafka."""
        logger.info(f"Aggregator connecting to Kafka at {self.broker}")
        logger.info(f"Consumer group: {self.group_id}")
        logger.info(f"Subscribing to topics: {self.topics}")
        
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
        logger.info(f"AGG | {sample}")
    
    def stop(self):
        """Stop the consumer."""
        self.running = False
        if self.consumer:
            try:
                self.consumer.close()
                logger.info("Aggregator stopped")
            except Exception as e:
                logger.error(f"Error closing consumer: {e}")


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
