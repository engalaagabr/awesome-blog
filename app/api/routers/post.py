from fastapi import APIRouter
from app.api.endpoints.post import router as post_endpoints

router = APIRouter(prefix="/api/posts", tags=["Posts"])

router.include_router(post_endpoints)