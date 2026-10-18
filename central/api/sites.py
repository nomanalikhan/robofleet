"""Site routes."""

from collections import Counter
from typing import get_args

import asyncpg
from fastapi import APIRouter, HTTPException

import health
from db import Db
from models import RobotStatus, Site

router = APIRouter(prefix="/sites", tags=["sites"])


async def site_list(db: asyncpg.Pool, site_id: str | None = None) -> list[Site]:
    counts = Counter((r["site_id"], r["status"]) for r in await health.robots(db, site_id=site_id))
    return [
        Site(**s, robots_by_status={st: counts[s["id"], st] for st in get_args(RobotStatus)})
        for s in await health.sites(db, site_id)
    ]


@router.get("")
async def list_sites(db: Db) -> list[Site]:
    return await site_list(db)


@router.get("/{site_id}")
async def get_site(site_id: str, db: Db) -> Site:
    sites = await site_list(db, site_id)
    if not sites:
        raise HTTPException(404, f"unknown site {site_id}")
    return sites[0]
