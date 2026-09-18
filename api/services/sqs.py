import json
import boto3
from api.config import settings

_sqs = boto3.client("sqs", region_name=settings.aws_region)


def push_node_job(memory_id: str, conversation_id: str) -> None:
    _sqs.send_message(
        QueueUrl=settings.sqs_node_queue_url,
        MessageBody=json.dumps({
            "memory_id": memory_id,
            "conversation_id": conversation_id,
        }),
    )


def push_topic_job(conversation_id: str) -> None:
    _sqs.send_message(
        QueueUrl=settings.sqs_topic_queue_url,
        MessageBody=json.dumps({
            "conversation_id": conversation_id,
        }),
    )
