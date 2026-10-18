"""Fleet API. Read-only over central TimescaleDB. Run with uvicorn main:app."""

from fastapi import FastAPI

import robots
import sites
from db import Db, lifespan

app = FastAPI(title="Olivaw Fleet API", version="1.0.0", lifespan=lifespan)
app.include_router(sites.router, prefix="/api/v1")
app.include_router(robots.router, prefix="/api/v1")


@app.get("/health", include_in_schema=False)
async def ok(db: Db) -> dict:
    await db.fetchval("SELECT 1")
    return {"status": "ok"}
