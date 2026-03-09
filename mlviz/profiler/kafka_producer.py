"""Kafka producer wrapper for sending metrics."""

import json
import logging
import os
from typing import Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError

from .metrics import MetricSample

logger = logging.getLogger(__name__)


class MetricProducer:
    """
    Singleton Kafka producer for sending MetricSample data.
    
    Lazily initializes a KafkaProducer and provides a simple API
    for sending metrics to per-model topics.
    """
    
    _instance: Optional["MetricProducer"] = None
    _producer: Optional[KafkaProducer] = None
    
    def __new__(cls):
        """Ensure only one instance exists per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the producer (lazy, on first use)."""
        if self._producer is None:
            self._init_producer()
    
    def _init_producer(self):
        """Create the Kafka producer with safe defaults."""
        broker = os.getenv("KAFKA_BROKER", "localhost:9092")
        
        try:
            self._producer = KafkaProducer(
                bootstrap_servers=[broker],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks=0,
                retries=2,
                max_in_flight_requests_per_connection=5,
                linger_ms=10,
            )
            logger.info(f"Kafka producer initialized: {broker}")
        except KafkaError as e:
            logger.warning(f"Failed to initialize Kafka producer: {e}")
            self._producer = None
    
    def send_metric(self, model_id: str, sample: MetricSample):
        """
        Send a MetricSample to the appropriate Kafka topic.
        
        Args:
            model_id: Model identifier (used for topic and key)
            sample: MetricSample to send
        """
        if self._producer is None:
            return
        
        topic = f"metrics.{model_id}"
        
        try:
            self._producer.send(
                topic=topic,
                key=model_id,
                value=sample.to_dict(),
            )
        except KafkaError as e:
            logger.debug(f"Failed to send metric to {topic}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error sending metric: {e}")
    
    def flush(self):
        """Flush any pending messages."""
        if self._producer:
            try:
                self._producer.flush(timeout=1.0)
            except Exception:
                pass
    
    def close(self):
        """Close the producer connection."""
        if self._producer:
            try:
                self._producer.close(timeout=2.0)
            except Exception:
                pass
            finally:
                self._producer = None


def get_producer() -> MetricProducer:
    """
    Get the singleton MetricProducer instance.
    
    Returns:
        MetricProducer instance.
    """
    return MetricProducer()
