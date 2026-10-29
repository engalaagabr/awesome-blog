from fastapi import APIRouter
from app.api.endpoints.post import router as post_endpoints
from app.api.endpoints.interaction import router as interaction_endpoints

router = APIRouter(prefix="/api/posts")

router.include_router(post_endpoints, tags=["Posts"])
router.include_router(interaction_endpoints, tags=["Engagement"])
