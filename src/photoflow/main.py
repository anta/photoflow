"""FastAPI factory with explicit schema checks and short-lived request sessions."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from photoflow import __version__
from photoflow.api import router
from photoflow.config import Settings
from photoflow.db import bind_library, create_db_engine, require_current_schema


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings if settings is not None else Settings()
        engine = create_db_engine(config)
        try:
            require_current_schema(engine)
            with Session(engine) as session:
                bind_library(session, config)
            app.state.settings = config
            app.state.engine = engine
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="PhotoFlow", version=__version__, lifespan=lifespan)
    app.include_router(router)

    @app.middleware("http")
    async def privacy_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, _error: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "Photo index unavailable"})

    @app.get("/health", tags=["health"])
    def health(request: Request):
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            if not request.app.state.settings.nas_root.is_dir():
                raise OSError
        except (SQLAlchemyError, OSError):
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}

    return app
