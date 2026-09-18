import numpy as np
import httpx
from api.config import settings


async def embed_query(text: str) -> np.ndarray:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.jina.ai/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.jina_api_key}"},
            json={
                "model": "jina-embeddings-v4",
                "input": [text],
                "task": "retrieval.query",   # query task — different from passage task used in Lambda
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        vec = np.array(resp.json()["data"][0]["embedding"], dtype=np.float32)
        return vec / np.linalg.norm(vec)
