from __future__ import annotations

from typing import Literal, Optional

import httpx


class _Resource:
    def __init__(self, client: httpx.Client) -> None:
        self._c = client


class _Conversations(_Resource):

    def create(self, metadata: Optional[dict] = None) -> dict:
        r = self._c.post("/conversations", json={"metadata": metadata or {}})
        r.raise_for_status()
        return r.json()

    def list(self) -> list[dict]:
        r = self._c.get("/conversations")
        r.raise_for_status()
        return r.json()

    def delete(self, conversation_id: str) -> None:
        self._c.delete(f"/conversations/{conversation_id}").raise_for_status()

    def stats(self, conversation_id: str) -> dict:
        r = self._c.get(f"/conversations/{conversation_id}/stats")
        r.raise_for_status()
        return r.json()

    def export(self, conversation_id: str) -> list[dict]:
        r = self._c.get(f"/conversations/{conversation_id}/export")
        r.raise_for_status()
        return r.json()


class _Memory(_Resource):

    def add_prompt(
        self,
        conversation_id: str,
        content: str,
        *,
        timestamp: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        body: dict = {"conversation_id": conversation_id, "content": content}
        if timestamp:
            body["timestamp"] = timestamp
        if metadata:
            body["metadata"] = metadata
        r = self._c.post("/memory/prompt", json=body)
        r.raise_for_status()
        return r.json()["memory_id"]

    def add_response(
        self,
        memory_id: str,
        conversation_id: str,
        content: str,
        *,
        timestamp: Optional[str] = None,
    ) -> dict:
        body: dict = {"conversation_id": conversation_id, "content": content}
        if timestamp:
            body["timestamp"] = timestamp
        r = self._c.post(f"/memory/{memory_id}/response", json=body)
        r.raise_for_status()
        return r.json()

    def add_batch(self, items: list[dict]) -> dict:
        r = self._c.post("/memory/batch", json={"items": items})
        r.raise_for_status()
        return r.json()

    def recall(
        self,
        conversation_id: str,
        query: str,
        *,
        k: Optional[int] = None,
        threshold: Optional[float] = None,
        strategy: Literal["semantic", "semantic_recency"] = "semantic",
        recency_alpha: float = 0.7,
        recency_half_life: Optional[float] = None,
        always_include_recent: int = 0,
        max_tokens: Optional[int] = None,
    ) -> dict:
        body: dict = {
            "conversation_id": conversation_id,
            "query": query,
            "strategy": strategy,
            "recency_alpha": recency_alpha,
            "always_include_recent": always_include_recent,
        }
        if k is not None:
            body["k"] = k
        if threshold is not None:
            body["threshold"] = threshold
        if recency_half_life is not None:
            body["recency_half_life"] = recency_half_life
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        r = self._c.post("/memory/recall", json=body)
        r.raise_for_status()
        return r.json()

    def get(self, memory_id: str) -> dict:
        r = self._c.get(f"/memory/{memory_id}")
        r.raise_for_status()
        return r.json()

    def delete(self, memory_id: str) -> None:
        self._c.delete(f"/memory/{memory_id}").raise_for_status()

    def neighbours(
        self,
        memory_id: str,
        *,
        threshold: float = 0.7,
        limit: Optional[int] = None,
        order: Literal["relevance", "timestamp"] = "relevance",
    ) -> list[dict]:
        params: dict = {"threshold": threshold, "order": order}
        if limit is not None:
            params["limit"] = limit
        r = self._c.get(f"/memory/{memory_id}/neighbours", params=params)
        r.raise_for_status()
        return r.json()


class _Topics(_Resource):

    def list(
        self,
        conversation_id: str,
        *,
        status: Optional[Literal["active", "dormant", "resolved"]] = None,
    ) -> list[dict]:
        params: dict = {"conversation_id": conversation_id}
        if status:
            params["status"] = status
        r = self._c.get("/topics", params=params)
        r.raise_for_status()
        return r.json()

    def get(self, topic_id: str) -> dict:
        r = self._c.get(f"/topics/{topic_id}")
        r.raise_for_status()
        return r.json()

    def summary(self, topic_id: str) -> dict:
        r = self._c.get(f"/topics/{topic_id}/summary")
        r.raise_for_status()
        return r.json()

    def status(self, topic_id: str) -> dict:
        r = self._c.get(f"/topics/{topic_id}/status")
        r.raise_for_status()
        return r.json()

    def messages(
        self,
        topic_id: str,
        conversation_id: str,
        *,
        query: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        params: dict = {"conversation_id": conversation_id}
        if query:
            params["query"] = query
        if max_tokens:
            params["max_tokens"] = max_tokens
        r = self._c.get(f"/topics/{topic_id}/messages", params=params)
        r.raise_for_status()
        return r.json()

    def current(
        self,
        conversation_id: str,
        *,
        mode: Literal["centroid", "hybrid", "llm"] = "centroid",
    ) -> Optional[dict]:
        r = self._c.get("/topics/current", params={"conversation_id": conversation_id, "mode": mode})
        r.raise_for_status()
        return r.json()

    def relevance(
        self,
        conversation_id: str,
        query: str,
        *,
        top_n: int = 3,
    ) -> list[dict]:
        r = self._c.get(
            "/topics/relevance",
            params={"conversation_id": conversation_id, "query": query, "top_n": top_n},
        )
        r.raise_for_status()
        return r.json()

    def retrieve(
        self,
        conversation_id: str,
        query: str,
        *,
        top_n: int = 3,
        max_tokens: Optional[int] = None,
    ) -> dict:
        body: dict = {"conversation_id": conversation_id, "query": query, "top_n": top_n}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        r = self._c.post("/topics/retrieve", json=body)
        r.raise_for_status()
        return r.json()

    def recompute(self, conversation_id: str) -> dict:
        r = self._c.post("/topics/recompute", params={"conversation_id": conversation_id})
        r.raise_for_status()
        return r.json()


class _Auth(_Resource):

    def create_key(
        self,
        *,
        project_name: Optional[str] = None,
        permissions: Optional[dict] = None,
    ) -> dict:
        body: dict = {"permissions": permissions or {"read": True, "write": True}}
        if project_name:
            body["project_name"] = project_name
        r = self._c.post("/auth/keys", json=body)
        r.raise_for_status()
        return r.json()

    def list_keys(self) -> list[dict]:
        r = self._c.get("/auth/keys")
        r.raise_for_status()
        return r.json()

    def revoke_key(self, key_id: str) -> None:
        self._c.delete(f"/auth/keys/{key_id}").raise_for_status()


class _Utils(_Resource):

    def health(self) -> dict:
        r = self._c.get("/health")
        r.raise_for_status()
        return r.json()

    def count_tokens(self, text: str) -> int:
        r = self._c.post("/utils/count_tokens", json={"text": text})
        r.raise_for_status()
        return r.json()["token_count"]


class GraphMemClient:
    """Sync Python client for the GraphMem API.

    Usage::

        gm = GraphMemClient("http://your-api-url", api_key="gm_sk_...")
        conv = gm.conversations.create()
        mid = gm.memory.add_prompt(conv["conversation_id"], "What is recursion?")
        gm.memory.add_response(mid, conv["conversation_id"], "A function that calls itself...")
        result = gm.memory.recall(conv["conversation_id"], "recursion definition")

    Use as a context manager to ensure the underlying HTTP session is closed::

        with GraphMemClient(...) as gm:
            ...
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key and not token:
            raise ValueError("Provide either api_key or token")

        headers: dict = {}
        if api_key:
            headers["X-API-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {token}"

        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

        self.conversations = _Conversations(self._http)
        self.memory = _Memory(self._http)
        self.topics = _Topics(self._http)
        self.auth = _Auth(self._http)
        self.utils = _Utils(self._http)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GraphMemClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
