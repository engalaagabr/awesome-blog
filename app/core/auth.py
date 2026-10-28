import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.revoked_token import RevokedToken
from app.models.refresh_token import RefreshToken
from app.models.user import User

COOKIE_NAME = "blog_session"
REFRESH_COOKIE_NAME = "blog_refresh"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "awesome-blog"
JWT_AUDIENCE = "awesome-blog-api"
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
    # Password changes and a deleted user ID being reused invalidate them.
    return hmac.digest(
        settings.JWT_SECRET_KEY.get_secret_value().encode(), user.password.encode(), "sha256"
    ).hex()


def create_access_token(user: User, session_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user.id),
            "sid": session_id,
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
    # Tokens issued before refresh support remain valid until their original expiry.
    if "sid" in claims and (
        not isinstance(claims["sid"], str) or not 0 < len(claims["sid"]) <= 64
    ):
        raise jwt.InvalidTokenError("Invalid session ID")
    return claims


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def revoke_session(session_id: str, db: AsyncSession):
    await db.execute(update(RefreshToken).where(
        RefreshToken.session_id == session_id,
    ).values(revoked=True))


async def revoke_token(token: str | None, db: AsyncSession):
    if not token:
        return
    try:
        claims = decode_access_token(token)
        expires_at = datetime.fromtimestamp(claims["exp"], UTC)
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        return
    if "sid" in claims:
        await revoke_session(claims["sid"], db)
    # The savepoint makes repeated/concurrent logout requests idempotent.
    try:
        async with db.begin_nested():
            db.add(RevokedToken(jti=claims["jti"], expires_at=expires_at))
            await db.flush()
    except IntegrityError:
        pass


async def revoke_request_tokens(request: Request, db: AsyncSession, refresh_token: str | None = None):
    # Revoke both transports when an API client also sends a browser cookie.
    for token in {request_token(request), request.cookies.get(COOKIE_NAME)}:
        await revoke_token(token, db)
    for token in {refresh_token, request.cookies.get(REFRESH_COOKIE_NAME)}:
        if token:
            stored = await db.get(RefreshToken, refresh_token_hash(token))
            if stored:
                await revoke_session(stored.session_id, db)
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= datetime.now(UTC)))
    await db.execute(delete(RefreshToken).where(
        RefreshToken.expires_at <= datetime.now(UTC),
    ).execution_options(synchronize_session=False))


def set_token_cookies(request: Request, response: Response, tokens: dict):
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE_NAME, tokens["access_token"], max_age=tokens["expires_in"], httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME, tokens["refresh_token"], max_age=tokens["refresh_expires_in"], httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )


def clear_token_cookies(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    for name in (COOKIE_NAME, REFRESH_COOKIE_NAME):
        response.delete_cookie(name, path="/", httponly=True, samesite="lax",
                               secure=request.url.scheme == "https")


def issue_token_pair(user: User, db: AsyncSession, session_id: str, expires_at: datetime) -> dict:
    refresh_token = secrets.token_urlsafe(48)
    db.add(RefreshToken(
        token_hash=refresh_token_hash(refresh_token), session_id=session_id,
        user_id=user.id, credential_version=credential_tag(user), expires_at=expires_at,
    ))
    return {
        "access_token": create_access_token(user, session_id),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        "refresh_expires_in": max(0, int((expires_at - datetime.now(UTC)).total_seconds())),
    }


async def start_login(request: Request, response: Response, user: User, db: AsyncSession) -> dict:
    await revoke_request_tokens(request, db)
    tokens = issue_token_pair(user, db, secrets.token_urlsafe(32),
                              datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_DAYS))
    await db.commit()
    set_token_cookies(request, response, tokens)
    return tokens


async def refresh_login(token: str | None, request: Request, response: Response, db: AsyncSession) -> dict:
    unauthorized = HTTPException(
        status_code=401, detail="Please log in to continue",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )
    stored = await db.get(RefreshToken, refresh_token_hash(token)) if token else None
    if stored is None:
        raise unauthorized
    # Claim the token atomically so two requests cannot both rotate it successfully.
    claimed = await db.execute(update(RefreshToken).where(
        RefreshToken.token_hash == stored.token_hash,
        RefreshToken.used.is_(False), RefreshToken.revoked.is_(False),
        RefreshToken.expires_at > datetime.now(UTC),
    ).values(used=True).execution_options(synchronize_session=False))
    user = await db.get(User, stored.user_id)
    if claimed.rowcount != 1 or user is None or not hmac.compare_digest(
        stored.credential_version, credential_tag(user)
    ):
        # Reuse of a rotated token invalidates its entire session, including access JWTs.
        await revoke_session(stored.session_id, db)
        await db.commit()
        raise unauthorized
    # Treat a naive timestamp as UTC for compatibility with database drivers.
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    tokens = issue_token_pair(user, db, stored.session_id, expires_at)
    await db.commit()
    set_token_cookies(request, response, tokens)
    return tokens


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
    if "sid" in claims:
        active = await db.scalar(select(RefreshToken.token_hash).where(
            RefreshToken.session_id == claims["sid"],
            RefreshToken.user_id == int(claims["sub"]),
            RefreshToken.used.is_(False), RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        ).limit(1))
        if active is None:
            raise unauthorized
    user = await db.get(User, int(claims["sub"]))
    if user is None or not hmac.compare_digest(claims["ver"], credential_tag(user)):
        raise unauthorized
    return user
