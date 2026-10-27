from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(database.Base.metadata.create_all)
        yield
    finally:
        await database.engine.dispose()
