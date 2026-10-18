"""Fleet API. Read-only over central TimescaleDB. Run with uvicorn main:app."""

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse

import robots
import sites
from db import Db, lifespan

# redoc_url=None because FastAPI's default loads redoc@next, a prerelease that renders a blank page.
app = FastAPI(title="Olivaw Fleet API", version="1.0.0", lifespan=lifespan, redoc_url=None)
app.include_router(sites.router, prefix="/api/v1")
app.include_router(robots.router, prefix="/api/v1")


@app.get("/redoc", include_in_schema=False)
async def redoc() -> HTMLResponse:
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} docs",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js",
    )


@app.get("/health", include_in_schema=False)
async def ok(db: Db) -> dict:
    await db.fetchval("SELECT 1")
    return {"status": "ok"}
