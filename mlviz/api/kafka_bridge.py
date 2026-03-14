"""Kafka consumer bridge for WebSocket live metrics."""

import asyncio
import logging
import threading
from typing import Optional

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from mlviz.profiler.metrics import MetricSample

logger = logging.getLogger(__name__)


def run_kafka_consumer(
    broker: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event
):
    """
    Run Kafka consumer in a separate thread and bridge to asyncio queue.
    
    Args:
        broker: Kafka broker address (e.g., "kafka:9092")
        queue: asyncio.Queue to push messages into
        loop: Event loop for thread-safe queue operations
        stop_event: Threading event to signal shutdown
    """
    topics = [
        "metrics.resnet18-train",
        "metrics.distilbert-infer",
        "metrics.data-pipeline",
    ]
    
    consumer: Optional[KafkaConsumer] = None
    
    try:
        logger.info(f"Starting Kafka consumer for WebSocket bridge at {broker}")
        logger.info(f"Subscribing to topics: {topics}")
        
        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=[broker],
            group_id="mlviz-ws-bridge",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: m.decode("utf-8"),
        )
        
        logger.info("Kafka consumer for WebSocket bridge started successfully")
        
        for message in consumer:
            if stop_event.is_set():
                logger.info("Stop event received, exiting Kafka consumer")
                break
            
            try:
                sample = MetricSample.from_json(message.value)
                payload = sample.to_dict()
                
                loop.call_soon_threadsafe(queue.put_nowait, payload)
                
            except Exception as e:
                logger.error(f"Failed to process Kafka message: {e}")
                continue
    
    except KafkaError as e:
        logger.error(f"Kafka consumer error: {e}")
        error_payload = {
            "type": "error",
            "message": f"Kafka connection error: {str(e)}"
        }
        try:
            loop.call_soon_threadsafe(queue.put_nowait, error_payload)
        except:
            pass
    
    except Exception as e:
        logger.error(f"Unexpected error in Kafka consumer: {e}")
    
    finally:
        if consumer:
            try:
                consumer.close()
                logger.info("Kafka consumer for WebSocket bridge closed")
            except Exception as e:
                logger.error(f"Error closing Kafka consumer: {e}")
