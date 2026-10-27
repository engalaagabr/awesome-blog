import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import LoginSession
from app.models.user import User

COOKIE_NAME = "blog_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


def check_origin(request: Request):
    """Reject cross-origin browser writes, including login/logout CSRF."""
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def revoke_session(request: Request, db: AsyncSession):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(token)))


async def start_session(request: Request, response: Response, user: User, db: AsyncSession):
    await revoke_session(request, db)
    now = datetime.now(UTC)
    await db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(
        token_hash=token_hash(token), user_id=user.id,
        expires_at=now + timedelta(seconds=SESSION_SECONDS),
    ))
    await db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    user = None
    if token:
        user = await db.scalar(
            select(User).join(LoginSession, LoginSession.user_id == User.id).where(
                LoginSession.token_hash == token_hash(token),
                LoginSession.expires_at > datetime.now(UTC),
            )
        )
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return user
