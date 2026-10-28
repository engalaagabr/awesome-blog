from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await database.engine.dispose()
