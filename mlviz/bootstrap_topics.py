"""Bootstrap Kafka topics with proper partition configuration."""

import logging
import os
import time

from kafka import KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError, KafkaError
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def create_topics(broker: str, num_partitions: int = 3, replication_factor: int = 1):
    """
    Create Kafka topics for metrics if they don't exist.
    
    Args:
        broker: Kafka broker address
        num_partitions: Number of partitions per topic
        replication_factor: Replication factor (1 for single broker)
    """
    topics_to_create = [
        "metrics.resnet18-train",
        "metrics.distilbert-infer",
        "metrics.data-pipeline",
        "metrics.alerts",
    ]
    
    logger.info(f"Connecting to Kafka at {broker}")
    
    max_retries = 10
    retry_delay = 3
    
    for attempt in range(max_retries):
        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers=[broker],
                client_id="topic-bootstrap"
            )
            
            new_topics = [
                NewTopic(
                    name=topic,
                    num_partitions=num_partitions,
                    replication_factor=replication_factor
                )
                for topic in topics_to_create
            ]
            
            logger.info(f"Creating {len(new_topics)} topics with {num_partitions} partitions each")
            
            try:
                admin_client.create_topics(new_topics=new_topics, validate_only=False)
                logger.info("Topics created successfully")
            except TopicAlreadyExistsError:
                logger.info("Topics already exist")
            
            admin_client.close()
            return True
        
        except KafkaError as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error("Failed to create topics after all retries")
                return False
    
    return False


def main():
    """Main entry point for topic bootstrap."""
    load_dotenv()
    
    broker = os.getenv("KAFKA_BROKER", "localhost:9092")
    
    success = create_topics(broker)
    
    if success:
        logger.info("Topic bootstrap completed")
    else:
        logger.error("Topic bootstrap failed")
        exit(1)


if __name__ == "__main__":
    main()
