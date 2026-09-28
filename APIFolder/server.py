import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from APIFolder.api import router as api_router
from Database.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
EMPLOYEE_DIR = BASE_DIR / "MinAppEmployee"
MANAGER_DIR = BASE_DIR / "MinAppManager"


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск сервера...")
    await init_db()
    logger.info("Таблицы готовы")
    yield
    logger.info("Остановка сервера...")


app = FastAPI(title="MTS Reports Bot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(api_router)

if EMPLOYEE_DIR.exists():
    app.mount("/employee", NoCacheStaticFiles(directory=str(EMPLOYEE_DIR), html=True), name="employee")
if MANAGER_DIR.exists():
    app.mount("/manager", NoCacheStaticFiles(directory=str(MANAGER_DIR), html=True), name="manager")


@app.get("/")
async def root():
    return {"status": "ok"}