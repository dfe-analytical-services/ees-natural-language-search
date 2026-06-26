from fastapi import FastAPI
from core.config import load_local_settings
from core.logging_config import configure_logging

load_local_settings()
configure_logging()

from routes.natural_language_search_function import router as natural_language_search_router
from routes.vectorizer_middleware import router as vectorizer_middleware_router

fastapi_app = FastAPI()

fastapi_app.include_router(natural_language_search_router)
fastapi_app.include_router(vectorizer_middleware_router)
