import json
import pathlib
import asyncpg
from pgvector.asyncpg import register_vector
from api.config import settings

_pool: asyncpg.Pool | None = None

_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=2,
        max_size=10,
        init=_init_connection,
    )


async def init_schema() -> None:
    sql = _SCHEMA_SQL.read_text()
    async with _pool.acquire() as conn:
        await conn.execute(sql)


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json",  encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised")
    return _pool
