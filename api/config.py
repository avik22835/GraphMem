from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # PostgreSQL + pgvector
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "graphmem"
    postgres_user: str = "graphmem"
    postgres_password: str = ""

    # Neptune
    neptune_endpoint: str = ""
    neptune_port: int = 8182

    # SQS
    sqs_node_queue_url: str = ""
    sqs_topic_queue_url: str = ""

    # Cognito
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_region: str = "us-east-1"

    # External APIs
    jina_api_key: str = ""
    groq_api_key: str = ""

    # GraphMem defaults
    default_k: int = 5
    default_threshold: float = 0.4
    default_max_tokens: int = 2000
    topic_recompute_interval: int = 20
    cold_start_min_nodes: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
