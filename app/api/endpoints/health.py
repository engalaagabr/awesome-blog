from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Check application and database health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Report readiness without exposing connection details or exception text."""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
