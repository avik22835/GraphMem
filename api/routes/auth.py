from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth.cognito import get_cognito_user
from api.auth.apikey import generate_api_key
from api.db.postgres import get_pool

router = APIRouter()


class CreateKeyRequest(BaseModel):
    project_name: Optional[str] = None
    permissions: dict = {"read": True, "write": True}


@router.post("/keys", status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    cognito_user: dict = Depends(get_cognito_user),
):
    full_key, key_prefix, key_hash = generate_api_key()
    user_id = cognito_user.get("sub")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (key_prefix, key_hash, user_id, project_name, permissions)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING key_id, created_at
            """,
            key_prefix,
            key_hash,
            user_id,
            body.project_name,
            body.permissions,
        )
    return {
        "key_id": str(row["key_id"]),
        "key": full_key,
        "key_prefix": key_prefix,
        "project_name": body.project_name,
        "permissions": body.permissions,
        "created_at": row["created_at"].isoformat(),
        "note": "This is the only time the full key will be shown. Copy it now.",
    }


@router.get("/keys")
async def list_api_keys(cognito_user: dict = Depends(get_cognito_user)):
    user_id = cognito_user.get("sub")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key_id, key_prefix, project_name, permissions, is_active, last_used_at, created_at
            FROM api_keys WHERE user_id = $1 ORDER BY created_at DESC
            """,
            user_id,
        )
    return [
        {
            "key_id": str(r["key_id"]),
            "key_prefix": r["key_prefix"],
            "project_name": r["project_name"],
            "permissions": dict(r["permissions"]),
            "is_active": r["is_active"],
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, cognito_user: dict = Depends(get_cognito_user)):
    user_id = cognito_user.get("sub")
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET is_active = FALSE WHERE key_id = $1::uuid AND user_id = $2",
            key_id,
            user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Key not found or not owned by you")
