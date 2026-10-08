"""FastAPI application: JSON API under /api + the web interface (./web) served at /."""
from __future__ import annotations

from pathlib import Path

import pymysql
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import DOCS_DIR, ROOT
from .routes_core import router as core_router
from .routes_ops import router as ops_router

WEB_DIR = ROOT / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="TnP Placement Engine API", version="1.0.0",
                  description="Placement probability and company-student matching. Thin layer over the "
                              "MySQL stored procedures, views and ML jobs.")
    app.include_router(core_router)
    app.include_router(ops_router)

    @app.exception_handler(pymysql.MySQLError)
    async def mysql_error(_: Request, exc: pymysql.MySQLError):
        code = exc.args[0] if exc.args else 0
        msg = exc.args[1] if len(exc.args) > 1 else str(exc)
        if code in (1142, 1143, 1044, 1370):      # privilege errors of the least-privilege accounts
            return JSONResponse({"detail": "That data is restricted for this account."}, status_code=403)
        if code == 3024:                          # MAX_EXECUTION_TIME exceeded
            return JSONResponse({"detail": "The query took too long and was stopped."}, status_code=408)
        # 1644 = rules raised on purpose by our triggers/procedures (SIGNAL 45000) -> a friendly 409
        user_rule = code in (1644, 1062, 1451, 1452, 3819, 4025)
        return JSONResponse({"detail": msg}, status_code=409 if user_rule else 500)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
    app.mount("/docs-files", StaticFiles(directory=DOCS_DIR), name="docs-files")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
