from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.db.postgres import init_pool, close_pool
from api.db.neptune import init_neptune, close_neptune
from api.routes import memory, conversations, topics


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    init_neptune()
    yield
    await close_pool()
    close_neptune()


app = FastAPI(
    title="GraphMem",
    description="Semantic graph-based memory API for LLM agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(topics.router, prefix="/topics", tags=["topics"])


@app.get("/health")
async def health():
    return {"status": "ok"}
