import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.settings import settings
from app.models.revoked_token import RevokedToken
from app.models.user import User

COOKIE_NAME = "blog_session"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "fastapi-blog"
JWT_AUDIENCE = "fastapi-blog-api"
bearer_scheme = HTTPBearer(auto_error=False)


def check_origin(request: Request):
    """Reject cross-origin browser writes, including login/logout CSRF."""
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


def request_token(request: Request) -> str | None:
    # An explicit Authorization header takes precedence over the browser cookie.
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        return token.strip() if scheme.lower() == "bearer" else None
    return request.cookies.get(COOKIE_NAME)


def credential_tag(user: User) -> str:
    # Bind tokens to the salted password hash without exposing that hash.
    # Password changes and a deleted SQLite user ID being reused invalidate them.
    return hmac.digest(
        settings.JWT_SECRET_KEY.get_secret_value().encode(), user.password.encode(), "sha256"
    ).hex()


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": credential_tag(user),
            "jti": secrets.token_urlsafe(32),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES),
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    claims = jwt.decode(
        token,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "ver", "jti", "iat", "nbf", "exp", "iss", "aud"]},
    )
    subject = claims["sub"]
    if not subject.isascii() or not subject.isdecimal() or not 0 < int(subject) < 2**63:
        raise jwt.InvalidTokenError("Invalid user ID")
    if not claims["jti"] or len(claims["jti"]) > 64:
        raise jwt.InvalidTokenError("Invalid token ID")
    if not isinstance(claims["ver"], str) or len(claims["ver"]) != 64 or not claims["ver"].isascii():
        raise jwt.InvalidTokenError("Invalid credential version")
    if any(type(claims[name]) is not int for name in ("iat", "nbf", "exp")):
        raise jwt.InvalidTokenError("Invalid timestamp")
    if claims["exp"] <= claims["iat"]:
        raise jwt.InvalidTokenError("Invalid token lifetime")
    return claims


async def revoke_token(token: str | None, db: AsyncSession):
    if not token:
        return
    try:
        claims = decode_access_token(token)
        expires_at = datetime.fromtimestamp(claims["exp"], UTC)
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        return
    # The savepoint makes repeated/concurrent logout requests idempotent.
    try:
        async with db.begin_nested():
            db.add(RevokedToken(jti=claims["jti"], expires_at=expires_at))
            await db.flush()
    except IntegrityError:
        pass


async def revoke_request_tokens(request: Request, db: AsyncSession):
    # Revoke both transports when an API client also sends a browser cookie.
    for token in {request_token(request), request.cookies.get(COOKIE_NAME)}:
        await revoke_token(token, db)
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= datetime.now(UTC)))


async def start_login(request: Request, response: Response, user: User, db: AsyncSession) -> str:
    await revoke_request_tokens(request, db)
    await db.commit()
    token = create_access_token(user)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.JWT_ACCESS_TOKEN_MINUTES * 60, httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )
    return token


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
    unauthorized = HTTPException(
        status_code=401, detail="Please log in to continue",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials.strip() if credentials else request_token(request)
    if not token:
        raise unauthorized
    try:
        claims = decode_access_token(token)
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        raise unauthorized from None
    if await db.get(RevokedToken, claims["jti"]) is not None:
        raise unauthorized
    user = await db.get(User, int(claims["sub"]))
    if user is None or not hmac.compare_digest(claims["ver"], credential_tag(user)):
        raise unauthorized
    return user
