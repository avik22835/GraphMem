import numpy as np
import httpx
from api.config import settings

_JINA_URL = "https://api.jina.ai/v1/embeddings"
_JINA_MODEL = "jina-embeddings-v4"
_DIM = 1024


async def _jina_embed(text: str, task: str) -> np.ndarray:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _JINA_URL,
            headers={"Authorization": f"Bearer {settings.jina_api_key}"},
            json={"model": _JINA_MODEL, "input": [text], "task": task, "dimensions": _DIM},
            timeout=30.0,
        )
        resp.raise_for_status()
        vec = np.array(resp.json()["data"][0]["embedding"], dtype=np.float32)
        return vec / np.linalg.norm(vec)


async def embed_query(text: str) -> np.ndarray:
    return await _jina_embed(text, "retrieval.query")


async def embed_passage(text: str) -> np.ndarray:
    return await _jina_embed(text, "retrieval.passage")
