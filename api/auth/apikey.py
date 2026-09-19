import asyncio
import secrets
import bcrypt
from fastapi import HTTPException
from api.db.postgres import get_pool

# Chars of random suffix after "gm_sk_" stored as key_prefix for DB prefix-index lookup
_PREFIX_CHARS = 16


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, key_prefix, key_hash). full_key is shown once and never stored."""
    raw = secrets.token_urlsafe(32)
    full_key = f"gm_sk_{raw}"
    key_prefix = full_key[: 6 + _PREFIX_CHARS]
    key_hash = bcrypt.hashpw(full_key.encode(), bcrypt.gensalt(rounds=12)).decode()
    return full_key, key_prefix, key_hash


async def authenticate_key(raw_key: str) -> dict:
    """Verify API key against DB. Returns principal dict or raises HTTPException."""
    if not raw_key.startswith("gm_sk_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    key_prefix = raw_key[: 6 + _PREFIX_CHARS]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT key_id, key_hash, user_id, permissions, is_active "
            "FROM api_keys WHERE key_prefix = $1",
            key_prefix,
        )

    if row is None or not row["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # bcrypt is CPU-bound — run in thread pool to avoid blocking the event loop
    valid = await asyncio.to_thread(
        bcrypt.checkpw, raw_key.encode(), row["key_hash"].encode()
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid API key")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE key_id = $1",
            row["key_id"],
        )

    return {
        "type": "api_key",
        "key_id": str(row["key_id"]),
        "user_id": row["user_id"],
        "permissions": dict(row["permissions"]),
    }
