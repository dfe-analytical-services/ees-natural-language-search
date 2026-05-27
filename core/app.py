from fastapi import FastAPI
from core.config import load_local_settings

load_local_settings()

from routes.healthcheck import router as health_router
from routes.natural_language_search_function import router as natural_language_search_router

fastapi_app = FastAPI()

fastapi_app.include_router(health_router)
fastapi_app.include_router(natural_language_search_router)
