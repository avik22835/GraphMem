import hmac
import hashlib
import base64
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.cognito import get_cognito_user
from api.auth.apikey import generate_api_key
from api.config import settings
from api.db.postgres import get_pool

router = APIRouter()


# ── Cognito helpers ──────────────────────────────────────────────────

def _cognito_client():
    return boto3.client("cognito-idp", region_name=settings.cognito_region)


def _secret_hash(username: str) -> Optional[str]:
    secret = getattr(settings, "cognito_client_secret", "")
    if not secret:
        return None
    msg = username + settings.cognito_client_id
    dig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


def _auth_params(username: str, password: str) -> dict:
    params: dict = {"USERNAME": username, "PASSWORD": password}
    h = _secret_hash(username)
    if h:
        params["SECRET_HASH"] = h
    return params


def _cognito_error(e: ClientError) -> HTTPException:
    code = e.response["Error"]["Code"]
    msg  = e.response["Error"]["Message"]
    status = {
        "NotAuthorizedException":   401,
        "UserNotConfirmedException": 403,
        "UserNotFoundException":     404,
        "UsernameExistsException":   409,
        "CodeMismatchException":     400,
        "ExpiredCodeException":      400,
        "InvalidPasswordException":  400,
        "LimitExceededException":    429,
        "TooManyRequestsException":  429,
    }.get(code, 400)
    return HTTPException(status_code=status, detail=msg)


# ── Cognito proxy routes (no auth required) ──────────────────────────

class SignUpRequest(BaseModel):
    email:    str
    password: str

class ConfirmRequest(BaseModel):
    email: str
    code:  str

class SignInRequest(BaseModel):
    email:    str
    password: str

class ResendRequest(BaseModel):
    email: str


@router.post("/signup", status_code=200)
async def cognito_signup(body: SignUpRequest):
    c = _cognito_client()
    kwargs: dict = {
        "ClientId": settings.cognito_client_id,
        "Username": body.email,
        "Password": body.password,
        "UserAttributes": [{"Name": "email", "Value": body.email}],
    }
    h = _secret_hash(body.email)
    if h:
        kwargs["SecretHash"] = h
    try:
        c.sign_up(**kwargs)
    except ClientError as e:
        raise _cognito_error(e)
    return {"status": "confirmation_required"}


@router.post("/confirm", status_code=200)
async def cognito_confirm(body: ConfirmRequest):
    c = _cognito_client()
    kwargs: dict = {
        "ClientId":        settings.cognito_client_id,
        "Username":        body.email,
        "ConfirmationCode": body.code.strip(),
    }
    h = _secret_hash(body.email)
    if h:
        kwargs["SecretHash"] = h
    try:
        c.confirm_sign_up(**kwargs)
    except ClientError as e:
        raise _cognito_error(e)
    return {"status": "confirmed"}


@router.post("/signin", status_code=200)
async def cognito_signin(body: SignInRequest):
    c = _cognito_client()
    try:
        resp = c.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=_auth_params(body.email, body.password),
        )
    except ClientError as e:
        raise _cognito_error(e)
    t = resp["AuthenticationResult"]
    return {
        "id_token":      t["IdToken"],
        "access_token":  t["AccessToken"],
        "refresh_token": t["RefreshToken"],
        "expires_in":    t["ExpiresIn"],
    }


class RefreshRequest(BaseModel):
    refresh_token: str
    email: str  # needed to compute SECRET_HASH against client secret


@router.post("/refresh", status_code=200)
async def cognito_refresh(body: RefreshRequest):
    c = _cognito_client()
    params: dict = {"REFRESH_TOKEN": body.refresh_token}
    h = _secret_hash(body.email)
    if h:
        params["SECRET_HASH"] = h
    try:
        resp = c.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters=params,
        )
    except ClientError as e:
        raise _cognito_error(e)
    t = resp["AuthenticationResult"]
    # Cognito does not return a new refresh_token on REFRESH_TOKEN_AUTH — old one stays valid
    return {
        "id_token":     t["IdToken"],
        "access_token": t["AccessToken"],
        "expires_in":   t["ExpiresIn"],
    }


@router.post("/resend", status_code=200)
async def cognito_resend(body: ResendRequest):
    c = _cognito_client()
    kwargs: dict = {
        "ClientId": settings.cognito_client_id,
        "Username": body.email,
    }
    h = _secret_hash(body.email)
    if h:
        kwargs["SecretHash"] = h
    try:
        c.resend_confirmation_code(**kwargs)
    except ClientError as e:
        raise _cognito_error(e)
    return {"status": "sent"}


# ── API key routes (require Cognito JWT) ──────────────────────────────

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
