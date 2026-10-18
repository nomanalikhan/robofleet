"""The connection pool, opened with the app and handed to routes as a dependency."""

import os
from contextlib import asynccontextmanager
from typing import Annotated

import asyncpg
from fastapi import Depends, FastAPI, Request


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=8)
    yield
    await app.state.db.close()


def pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db


Db = Annotated[asyncpg.Pool, Depends(pool)]
