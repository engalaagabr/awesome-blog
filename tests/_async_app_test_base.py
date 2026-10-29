"""Exercise real async database I/O without opening the project's blog.db."""

import asyncio
import os
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from contextlib import AsyncExitStack
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Keep importing the application independent of local .env credentials.
with patch.dict(os.environ, {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "JWT_SECRET_KEY": "test-only-signing-key-with-at-least-64-bytes-for-algorithm-rejection-tests",
    "JWT_ACCESS_TOKEN_MINUTES": "30",
    "REFRESH_TOKEN_DAYS": "7",
}):
    from app import main
    from app.core import database
    from app.models.user import User
    from app.models.post import Post
    from app.models.revoked_token import RevokedToken
    from app.models.refresh_token import RefreshToken
    from app.core.auth import (
        COOKIE_NAME, REFRESH_COOKIE_NAME, JWT_ALGORITHM, decode_access_token, refresh_token_hash,
    )
    from app.core.config import settings
    from app.utils import profile_images




class AsyncAppTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        media_directory = Path(directory) / "media"
        self.profile_directory = media_directory / "profile_pics"
        self.profile_directory.mkdir(parents=True)
        self.stack.enter_context(patch.object(profile_images, "PROFILE_PICS_DIR", self.profile_directory))
        media_app = next(route.app for route in main.app.routes if getattr(route, "path", None) == "/media")
        self.stack.enter_context(patch.object(media_app, "all_directories", [str(media_directory)]))
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(directory) / 'test.db'}"
        )
        factory = async_sessionmaker(
            self.engine, autoflush=False, expire_on_commit=False
        )
        self.stack.enter_context(patch.object(database, "engine", self.engine))
        self.stack.enter_context(patch.object(database, "SessionLocal", factory))
        async with self.engine.begin() as connection:
            await connection.run_sync(database.Base.metadata.create_all)
        # Exercise the real startup, shutdown, and request session dependency.
        await self.stack.enter_async_context(main.app.router.lifespan_context(main.app))
        self.client = await self.stack.enter_async_context(
            AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")
        )

    async def register(self, username="alice", login=True):
        response = await self.client.post("/api/users/register", json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Password1",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("password", response.json())
        if login:
            await self.login(username)
        return response.json()

    async def login(self, username="alice", password="Password1"):
        response = await self.client.post("/api/users/login", json={
            "username": username, "password": password,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response

    async def create_post(self, user_id, title="Async post"):
        profile = (await self.client.get(f"/api/users/{user_id}/profile")).json()
        await self.login(profile["username"])
        response = await self.client.post("/api/posts/", json={
            "title": title, "content": "Async content",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["date_posted"])
        return response.json()
