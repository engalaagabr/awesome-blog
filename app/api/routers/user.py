from fastapi import APIRouter
from app.api.endpoints.user import router as user_endpoints

router = APIRouter(prefix="/api/users", tags=["Users"])

router.include_router(user_endpoints)