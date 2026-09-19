from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from api.auth.cognito import verify_cognito_token
from api.auth.apikey import authenticate_key

_bearer = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict:
    """Accepts either Authorization: Bearer <JWT> or X-API-Key: gm_sk_... header."""
    if credentials is not None:
        payload = await verify_cognito_token(credentials.credentials)
        return {
            "type": "jwt",
            "user_id": payload.get("sub"),
            "email": payload.get("email", ""),
            "permissions": {"read": True, "write": True},
        }
    if x_api_key is not None:
        return await authenticate_key(x_api_key)
    raise HTTPException(
        status_code=401,
        detail="Authentication required — provide Authorization: Bearer <token> or X-API-Key header",
    )


async def require_write(principal: dict = Depends(get_current_principal)) -> dict:
    if not principal.get("permissions", {}).get("write"):
        raise HTTPException(status_code=403, detail="Write permission required")
    return principal
