from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from api.db.postgres import init_pool, close_pool
from api.db.neptune import init_neptune, close_neptune
from api.routes import memory, conversations, topics, utils, auth
from api.auth.dependencies import get_current_principal


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

_auth = [Depends(get_current_principal)]

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(memory.router, prefix="/memory", tags=["memory"], dependencies=_auth)
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"], dependencies=_auth)
app.include_router(topics.router, prefix="/topics", tags=["topics"], dependencies=_auth)
app.include_router(utils.router, prefix="/utils", tags=["utils"], dependencies=_auth)


@app.get("/health")
async def health():
    return {"status": "ok"}
