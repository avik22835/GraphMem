from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.db.postgres import init_pool, init_schema, close_pool
from api.db.neptune import init_neptune, close_neptune
from api.routes import memory, conversations, topics, utils, auth
from api.auth.dependencies import get_current_principal


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await init_schema()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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


# ── Frontend page routes ───────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("api/static/index.html")

@app.get("/reference", include_in_schema=False)
async def reference():
    return FileResponse("api/static/reference.html")

@app.get("/playground", include_in_schema=False)
async def playground():
    return FileResponse("api/static/playground.html")

@app.get("/login", include_in_schema=False)
async def login():
    return FileResponse("api/static/login.html")

@app.get("/signup", include_in_schema=False)
async def signup():
    return FileResponse("api/static/signup.html")

@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse("api/static/dashboard.html")


app.mount("/static", StaticFiles(directory="api/static"), name="static")
