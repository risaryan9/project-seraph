"""Kafka consumer service for live terminal view of metrics."""

import logging
import os
import signal
import sys

from kafka import KafkaConsumer
from kafka.errors import KafkaError
from dotenv import load_dotenv

from mlviz.profiler.metrics import MetricSample

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


COLORS = {
    "resnet18-train": "\033[94m",
    "distilbert-infer": "\033[93m",
    "data-pipeline": "\033[92m",
    "reset": "\033[0m",
}

DIVIDER = "─" * 85


class LiveViewService:
    """
    Kafka consumer for real-time terminal display of metrics.
    
    Uses a separate consumer group (mlviz-live-view) to receive
    a full copy of the metrics stream for display purposes.
    """
    
    def __init__(self):
        """Initialize the live-view service."""
        load_dotenv()
        
        self.broker = os.getenv("KAFKA_BROKER", "localhost:9092")
        self.group_id = "mlviz-live-view"
        self.topics = [
            "metrics.resnet18-train",
            "metrics.distilbert-infer",
            "metrics.data-pipeline",
        ]
        
        self.consumer = None
        self.running = False
        self.line_count = 0
    
    def start(self):
        """Start consuming from Kafka and display metrics."""
        print("\n" + "=" * 85)
        print("MLViz — Live Metrics View")
        print(f"Consumer group: {self.group_id}")
        print("Press Ctrl+C to stop")
        print("=" * 85 + "\n")
        
        try:
            self.consumer = KafkaConsumer(
                *self.topics,
                bootstrap_servers=[self.broker],
                group_id=self.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: m.decode("utf-8"),
            )
            
            logger.info("Live-view consumer started")
            self.running = True
            
            for message in self.consumer:
                if not self.running:
                    break
                
                try:
                    sample = MetricSample.from_json(message.value)
                    self._display_sample(sample)
                except Exception as e:
                    logger.error(f"Failed to process message: {e}")
        
        except KafkaError as e:
            logger.error(f"Kafka error: {e}")
            print(f"\nKafka connection error: {e}")
            print("Make sure Kafka is running and accessible.")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.stop()
    
    def _display_sample(self, sample: MetricSample):
        """
        Display a metric sample with color coding.
        
        Args:
            sample: MetricSample to display
        """
        color = COLORS.get(sample.model_id, "")
        reset = COLORS["reset"]
        
        print(f"{color}{sample}{reset}")
        
        self.line_count += 1
        if self.line_count % 15 == 0:
            print(DIVIDER)
    
    def stop(self):
        """Stop the consumer."""
        self.running = False
        if self.consumer:
            try:
                self.consumer.close()
                logger.info("Live-view consumer stopped")
            except Exception as e:
                logger.error(f"Error closing consumer: {e}")


def main():
    """Main entry point for live-view service."""
    live_view = LiveViewService()
    
    def signal_handler(sig, frame):
        print("\n\nShutting down gracefully...")
        live_view.stop()
        print("Live-view stopped. Exiting.")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    live_view.start()


if __name__ == "__main__":
    main()
