from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from api.config import settings

_client: client.Client | None = None
_connection: DriverRemoteConnection | None = None


def init_neptune() -> None:
    global _client, _connection
    endpoint = f"wss://{settings.neptune_endpoint}:{settings.neptune_port}/gremlin"
    _connection = DriverRemoteConnection(endpoint, "g")
    _client = client.Client(
        endpoint,
        "g",
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


def get_client() -> client.Client:
    if _client is None:
        raise RuntimeError("Neptune client not initialised")
    return _client


def get_traversal():
    if _connection is None:
        raise RuntimeError("Neptune connection not initialised")
    return traversal().withRemote(_connection)


def close_neptune() -> None:
    global _client, _connection
    if _client:
        _client.close()
        _client = None
    if _connection:
        _connection.close()
        _connection = None
