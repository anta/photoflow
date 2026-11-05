"""FastAPI application factory."""

from fastapi import FastAPI

from photoflow import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="PhotoFlow", version=__version__)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
