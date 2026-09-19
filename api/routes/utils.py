from fastapi import APIRouter
from pydantic import BaseModel
from api.services.tokens import count_tokens

router = APIRouter()


class CountTokensRequest(BaseModel):
    text: str


@router.post("/count_tokens")
async def count_tokens_endpoint(body: CountTokensRequest):
    return {"token_count": count_tokens(body.text)}
