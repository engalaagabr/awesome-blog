from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers.post import router as posts_router
from app.api.routers.user import router as users_router
from app.core.exceptions import exception_handlers
from app.core.lifespan import lifespan
from app.web.routes import router as pages_router

app = FastAPI(lifespan=lifespan, exception_handlers=exception_handlers)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/media", StaticFiles(directory="app/media"), name="media")

app.include_router(posts_router)
app.include_router(users_router)
app.include_router(pages_router)
