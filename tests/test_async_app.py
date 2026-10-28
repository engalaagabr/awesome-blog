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
    from app.core.settings import settings
    from app.utils import profile_images


class AsyncAppTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_post_crud_and_html_relationships(self):
        user = await self.register()
        post = await self.create_post(user["id"])
        self.assertEqual(post["author"], "alice")
        post_url = f"/api/posts/{post['id']}"
        response = await self.client.get(post_url)
        self.assertEqual(response.json(), post)
        for url in ("/api/posts/", f"/api/users/{user['id']}/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), [post])
        for url in ("/", "/posts", f"/posts/{post['id']}", f"/users/{user['id']}/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("Async post", response.text)
            self.assertIn("alice", response.text)
        response = await self.client.patch(post_url, params={"user_id": user["id"]},
                                           json={"title": "Updated post"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Updated post")
        self.assertEqual(response.json()["content"], post["content"])
        self.assertEqual(response.json()["author"], "alice")
        response = await self.client.delete(post_url, params={"user_id": user["id"]})
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual((await self.client.get(post_url)).status_code, 404)

    async def test_post_pagination_and_navigation(self):
        async with database.SessionLocal() as db:
            alice = User(username="alice", email="alice@example.com", password="unused")
            bob = User(username="bob", email="bob@example.com", password="unused")
            db.add_all([alice, bob])
            await db.flush()
            timestamp = datetime(2026, 1, 1, tzinfo=UTC)
            posts = [Post(title=f"Article {index:02d}", content="Body", user_id=alice.id,
                          date_posted=timestamp) for index in range(12)]
            # A higher ID with an older timestamp must still sort last.
            older = Post(title="Older article", content="Body", user_id=bob.id,
                         date_posted=timestamp - timedelta(days=1))
            db.add_all([*posts, older])
            await db.commit()
            alice_id = alice.id
            expected_ids = [post.id for post in reversed(posts)]
            older_id = older.id

        for url, expected in (("/api/posts/", [*expected_ids, older_id]),
                              (f"/api/users/{alice_id}/posts", expected_ids)):
            with self.subTest(url=url):
                default = await self.client.get(url)
                self.assertEqual(len(default.json()), 10)
                collected = []
                for page in range(1, 4):
                    response = await self.client.get(url, params={"page": page, "per_page": 5})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.headers["x-total-count"], str(len(expected)))
                    self.assertEqual(response.headers["x-total-pages"], "3")
                    self.assertEqual(response.headers["x-page"], str(page))
                    self.assertEqual(response.headers["x-per-page"], "5")
                    collected.extend(item["id"] for item in response.json())
                self.assertEqual(collected, expected)
                response = await self.client.get(url, params={"page": 4, "per_page": 5})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

        for url in ("/", "/posts", f"/users/{alice_id}/posts"):
            with self.subTest(url=url):
                response = await self.client.get(url, params={"per_page": 5})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.text.count("<article "), 5)
                self.assertIn("Article 11", response.text)
                self.assertNotIn("Article 06", response.text)
                self.assertNotIn('rel="prev"', response.text)
                self.assertIn('rel="next"', response.text)
                response = await self.client.get(url, params={"page": 2, "per_page": 5})
                self.assertIn("Page 2 of 3", response.text)
                self.assertIn(f"http://test{url}?page=3&amp;per_page=5", response.text)
                self.assertIn('aria-current="page"', response.text)
                self.assertIn("Article 06", response.text)
                self.assertNotIn("Article 11", response.text)
                response = await self.client.get(url, params={"page": 3, "per_page": 5})
                self.assertIn('rel="prev"', response.text)
                self.assertNotIn('rel="next"', response.text)
                self.assertEqual((await self.client.get(url, params={"page": 4, "per_page": 5})).status_code, 404)

    async def test_pagination_validation_and_empty_results(self):
        user = await self.register(login=False)
        urls = ("/", "/posts", f"/users/{user['id']}/posts",
                "/api/posts/", f"/api/users/{user['id']}/posts")
        for url in urls:
            for params in ({"page": 0}, {"page": -1}, {"page": "bad"},
                           {"per_page": 0}, {"per_page": 101}, {"per_page": "bad"}):
                with self.subTest(url=url, params=params):
                    response = await self.client.get(url, params=params)
                    self.assertEqual(response.status_code, 422, response.text)
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            if url.startswith("/api/"):
                self.assertEqual(response.json(), [])
                self.assertEqual(response.headers["x-total-count"], "0")
                self.assertEqual(response.headers["x-total-pages"], "0")
            else:
                self.assertNotIn('aria-label="Post pagination"', response.text)
                self.assertEqual((await self.client.get(url, params={"page": 2})).status_code, 404)

    async def test_login_profile_and_password_update(self):
        user = await self.register()
        response = await self.client.post("/api/users/login", json={
            "username": "alice", "password": "Password1",
        })
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.get(f"/api/users/{user['id']}/profile")
        self.assertEqual(response.json(), user)
        response = await self.client.patch(f"/api/users/{user['id']}/update", json={
            "username": "alice_new", "password": "Changed2",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["image_path"], "/static/profile_pics/default.jpg")
        for password, code in (("Password1", 401), ("Changed2", 200)):
            response = await self.client.post("/api/users/login", json={
                "username": "alice_new", "password": password,
            })
            self.assertEqual(response.status_code, code, response.text)
        response = await self.client.patch(f"/api/users/{user['id']}/update",
                                           json={"image_file": None})
        self.assertEqual(response.json()["image_path"], "/static/profile_pics/default.jpg")

    async def test_user_deletion_cascades_only_owned_posts(self):
        alice = await self.register()
        bob = await self.register("bob")
        await self.create_post(alice["id"])
        await self.create_post(alice["id"], "Another post")
        remaining = await self.create_post(bob["id"], "Bob's post")
        await self.login("alice")
        response = await self.client.delete(f"/api/users/{alice['id']}/delete")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual((await self.client.get("/api/posts/")).json(), [remaining])
        response = await self.client.get(f"/api/users/{alice['id']}/profile")
        self.assertEqual(response.status_code, 404)

    async def test_errors_empty_results_and_ownership_checks(self):
        user = await self.register()
        self.assertEqual((await self.client.get("/api/posts/")).json(), [])
        response = await self.client.get(f"/api/users/{user['id']}/posts")
        self.assertEqual(response.json(), [])
        response = await self.client.post("/api/users/register", json={
            "username": "alice", "email": "alice@example.com", "password": "Password1",
        })
        self.assertEqual(response.status_code, 400)
        post = await self.create_post(user["id"])
        url = f"/api/posts/{post['id']}"
        other = await self.register("bob")
        for method, body in (("PATCH", {"title": "Forbidden"}), ("DELETE", None)):
            response = await self.client.request(method, url,
                params={"user_id": user["id"]}, json=body)
            self.assertEqual(response.status_code, 403, response.text)
        for url in ("/api/posts/9999", "/api/users/9999/profile", "/api/users/9999/posts",
                    "/posts/9999", "/users/9999/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.post("/api/posts/", json={
            "title": "Missing user", "content": "Content", "user_id": 9999,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user_id"], other["id"])
        response = await self.client.get("/api/posts/not-an-int")
        self.assertEqual(response.status_code, 422)
        response = await self.client.get("/posts/not-an-int")
        self.assertEqual(response.status_code, 422)
        response = await self.client.post("/api/users/login", json={
            "username": "unknown", "password": "Wrong1",
        })
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    async def test_concurrent_requests_use_independent_sessions(self):
        user = await self.register()
        post = await self.create_post(user["id"])
        responses = await asyncio.gather(*(
            self.client.get(f"/api/posts/{post['id']}") for _ in range(8)
        ))
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), post)

    async def test_dependency_rolls_back_uncommitted_work_on_error(self):
        dependency = database.get_db()
        session = await anext(dependency)
        session.add(User(username="rollback", email="rollback@example.com", password="unused"))
        await session.flush()
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            await dependency.athrow(RuntimeError("request failed"))
        async with database.SessionLocal() as fresh_session:
            self.assertIsNone(await fresh_session.scalar(select(User)))

    async def test_password_work_runs_outside_event_loop_thread(self):
        event_loop_thread = threading.get_ident()
        worker_threads = []

        def hash_in_worker(password):
            worker_threads.append(threading.get_ident())
            return "test-hash"

        def verify_in_worker(password, hashed):
            worker_threads.append(threading.get_ident())
            return True

        with patch("app.api.endpoints.user.hash_password", hash_in_worker), \
             patch("app.api.endpoints.user.verify_password", verify_in_worker):
            user = await self.register(login=False)
            response = await self.client.post("/api/users/login", json={
                "username": "alice", "password": "Password1",
            })
            self.assertEqual(response.status_code, 200, response.text)
            response = await self.client.patch(f"/api/users/{user['id']}/update",
                                               json={"password": "Changed2"})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(worker_threads), 3)
        self.assertTrue(all(thread != event_loop_thread for thread in worker_threads))


    async def test_missing_resources_for_mutations(self):
        await self.register()
        cases = [
            ("PATCH", "/api/posts/9999?user_id=1", {"title": "Missing"}, "Post not found"),
            ("DELETE", "/api/posts/9999?user_id=1", None, "Post not found"),
            ("PATCH", "/api/users/9999/update", {"username": "missing"}, "User not found"),
            ("DELETE", "/api/users/9999/delete", None, "User not found"),
        ]
        for method, url, body, detail in cases:
            with self.subTest(method=method, url=url):
                response = await self.client.request(method, url, json=body)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json(), {"detail": detail})

    async def test_invalid_path_and_query_parameters(self):
        await self.register()
        cases = [
            ("GET", "/api/posts/bad", None),
            ("PATCH", "/api/posts/bad?user_id=1", {"title": "Valid"}),
            ("DELETE", "/api/posts/bad?user_id=1", None),
            ("GET", "/api/users/bad/profile", None),
            ("GET", "/api/users/bad/posts", None),
            ("PATCH", "/api/users/bad/update", {"username": "valid"}),
            ("DELETE", "/api/users/bad/delete", None),
            ("GET", "/posts/bad", None),
            ("GET", "/users/bad/posts", None),
        ]
        for method, url, body in cases:
            with self.subTest(method=method, url=url):
                response = await self.client.request(method, url, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                if url.startswith("/api/"):
                    self.assertIsInstance(response.json()["detail"], list)
                else:
                    self.assertIn("text/html", response.headers["content-type"])

    async def test_invalid_request_bodies(self):
        await self.register()
        registration = {"username": "valid", "email": "valid@example.com", "password": "Password1"}
        invalid_users = [
            {},
            {**registration, "username": "a"},
            {**registration, "username": "invalid name"},
            {**registration, "email": ""},
            {**registration, "password": "password1"},
            {**registration, "password": "PASSWORD1"},
            {**registration, "password": "Password"},
            {**registration, "password": "Aa1" + "é" * 35},
        ]
        cases = [("POST", "/api/users/register", body) for body in invalid_users]
        cases += [
            ("POST", "/api/users/login", {}),
            ("POST", "/api/users/login", {"username": "ab", "password": "abcd"}),
            ("PATCH", "/api/users/1/update", {"username": "bad name"}),
            ("PATCH", "/api/users/1/update", {"password": "weak"}),
            ("PATCH", "/api/users/1/update", {"email": ""}),
            ("PATCH", "/api/users/1/update", {"image_file": ""}),
            ("POST", "/api/posts/", {}),
            ("POST", "/api/posts/", {"title": "", "content": "Body", "user_id": 1}),
            ("POST", "/api/posts/", {"title": "a" * 101, "content": "Body", "user_id": 1}),
            ("POST", "/api/posts/", {"title": "Valid", "content": "", "user_id": 1}),
            ("PATCH", "/api/posts/1?user_id=1", {"title": ""}),
            ("PATCH", "/api/posts/1?user_id=1", {"content": ""}),
        ]
        for method, url, body in cases:
            with self.subTest(method=method, url=url, body=body):
                response = await self.client.request(method, url, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIsInstance(response.json()["detail"], list)

    async def test_registration_rejects_username_and_email_conflicts(self):
        await self.register()
        for username, email in (("alice", "other@example.com"), ("other", "alice@example.com")):
            with self.subTest(username=username, email=email):
                response = await self.client.post("/api/users/register", json={
                    "username": username, "email": email, "password": "Password1",
                })
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"], "Username or email already exists.")

    async def test_partial_and_empty_updates_preserve_other_fields(self):
        user = await self.register()
        post = await self.create_post(user["id"])
        user_url = f"/api/users/{user['id']}/update"
        post_url = f"/api/posts/{post['id']}?user_id={user['id']}"
        response = await self.client.patch(user_url, json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), user)
        response = await self.client.patch(post_url, json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), post)
        response = await self.client.patch(user_url, json={"email": "new@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {**user, "email": "new@example.com"})
        response = await self.client.patch(post_url, json={"content": "Changed content"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {**post, "content": "Changed content"})
        response = await self.client.get(f"/api/posts/{post['id']}")
        self.assertEqual(response.json()["content"], "Changed content")

    async def test_user_posts_exclude_other_users_posts(self):
        alice = await self.register()
        bob = await self.register("bob")
        first = await self.create_post(alice["id"], "Alice first")
        second = await self.create_post(alice["id"], "Alice second")
        await self.create_post(bob["id"], "Bob private listing")
        response = await self.client.get(f"/api/users/{alice['id']}/posts")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({item["id"] for item in response.json()}, {first["id"], second["id"]})
        self.assertTrue(all(item["author"] == "alice" for item in response.json()))
        response = await self.client.get(f"/users/{alice['id']}/posts")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Alice first", response.text)
        self.assertIn("Alice second", response.text)
        self.assertNotIn("Bob private listing", response.text)

    async def test_empty_pages_and_deleting_user_without_posts(self):
        user = await self.register()
        for url in ("/", "/posts", f"/users/{user['id']}/posts"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("text/html", response.headers["content-type"])
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 401)

    async def test_documentation_static_files_and_unknown_routes(self):
        for url in ("/docs", "/redoc", "/openapi.json", "/static/css/main.css", "/static/js/api.js",
                    "/static/profile_pics/default.jpg"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 200)
        schema = (await self.client.get("/openapi.json")).json()
        operations = sum(len(methods) for methods in schema["paths"].values())
        self.assertEqual(operations, 16)
        for url in ("/api/missing", "/missing", "/static/missing.css", "/media/missing.jpg"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 404)
        response = await self.client.put("/api/posts/", json={})
        self.assertEqual(response.status_code, 405)
        response = await self.client.get("/api/posts", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    async def assert_update_conflict_rejected(self, field):
        alice = await self.register()
        bob = await self.register("bob")
        # Observe the HTTP 500 response if an unhandled database exception occurs.
        async with AsyncClient(
            transport=ASGITransport(app=main.app, raise_app_exceptions=False),
            base_url="http://test", cookies=self.client.cookies,
        ) as client:
            response = await client.patch(f"/api/users/{bob['id']}/update",
                                          json={field: alice[field]})
        profile = await self.client.get(f"/api/users/{bob['id']}/profile")
        self.assertEqual(profile.json(), bob, "A failed update must leave the profile unchanged")
        self.assertIn(response.status_code, (400, 409),
                      f"Conflicting {field} should be a client error, got {response.status_code}: {response.text}")

    async def test_update_rejects_duplicate_username(self):
        await self.assert_update_conflict_rejected("username")

    async def test_update_rejects_duplicate_email(self):
        await self.assert_update_conflict_rejected("email")

    async def test_jwt_survives_new_client_and_logout_revokes_it(self):
        user = await self.register(login=False)
        self.assertEqual((await self.client.get("/api/users/me")).status_code, 401)
        login = await self.login()
        cookie = self.client.cookies.get(COOKIE_NAME)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertIn("SameSite=lax", login.headers["set-cookie"])
        self.assertEqual(login.json()["id"], user["id"])
        self.assertEqual(login.json()["access_token"], cookie)
        self.assertEqual(login.json()["refresh_token"], self.client.cookies.get(REFRESH_COOKIE_NAME))
        self.assertEqual(login.json()["token_type"], "bearer")
        self.assertEqual(login.json()["expires_in"], 1800)
        self.assertEqual(login.headers["cache-control"], "no-store")
        claims = decode_access_token(cookie)
        self.assertEqual(claims["sub"], str(user["id"]))
        self.assertEqual(claims["exp"] - claims["iat"], 1800)
        self.assertNotIn("login_sessions", database.Base.metadata.tables)
        async with database.SessionLocal() as db:
            self.assertIsNone(await db.scalar(select(RevokedToken)))
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test",
                               cookies=self.client.cookies) as browser:
            profile = await browser.get("/api/users/me")
            self.assertEqual(profile.json(), user)
            self.assertEqual(profile.headers["cache-control"], "no-store")
            self.assertEqual((await self.client.post("/api/users/logout")).status_code, 204)
            self.assertEqual((await browser.get("/api/users/me")).status_code, 401)
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))

    async def test_invalid_jwts_are_rejected(self):
        await self.register()
        token = self.client.cookies.get(COOKIE_NAME)
        claims = decode_access_token(token)
        key = settings.JWT_SECRET_KEY.get_secret_value()
        invalid_claims = [
            {**claims, "exp": int(datetime.now(UTC).timestamp()) - 1},
            {**claims, "nbf": int(datetime.now(UTC).timestamp()) + 3600},
            {**claims, "iat": int(datetime.now(UTC).timestamp()) + 3600},
            {**claims, "iss": "another-app"},
            {**claims, "aud": "another-api"},
            {**claims, "sub": "not-a-user"},
            {**claims, "sub": "99999999999999999999999999999"},
            {**claims, "sub": "99999"},
            {**claims, "sub": 1},
            {**claims, "jti": ""},
            {**claims, "ver": "0" * 64},
            {**claims, "ver": 1},
            {**claims, "sid": []},
            {**claims, "sid": ""},
            {**claims, "sid": "x" * 65},
            {**claims, "exp": "tomorrow"},
            {**claims, "iat": None},
        ]
        for required in ("sub", "ver", "jti", "iat", "nbf", "exp", "iss", "aud"):
            invalid_claims.append({name: value for name, value in claims.items() if name != required})
        invalid_tokens = [jwt.encode(payload, key, algorithm=JWT_ALGORITHM) for payload in invalid_claims]
        invalid_tokens.extend([
            "forged-token",
            jwt.encode(claims, "different-signing-key-at-least-32-bytes", algorithm=JWT_ALGORITHM),
            jwt.encode(claims, key, algorithm="HS384"),
            jwt.encode(claims, "", algorithm="none"),
        ])
        # Change the subject without recomputing the signature.
        forged = jwt.encode({**claims, "sub": "99999"}, key, algorithm=JWT_ALGORITHM)
        invalid_tokens.append(forged.rsplit(".", 1)[0] + "." + token.rsplit(".", 1)[1])
        self.client.cookies.clear()
        for index, invalid in enumerate(invalid_tokens):
            with self.subTest(case=index):
                for headers, cookies in [({"Authorization": f"Bearer {invalid}"}, {}),
                                         ({}, {COOKIE_NAME: invalid})]:
                    self.client.cookies.clear()
                    self.client.cookies.update(cookies)
                    response = await self.client.get("/api/users/me", headers=headers)
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")

    async def test_bearer_authentication_and_logout(self):
        user = await self.register()
        token = self.client.cookies.get(COOKIE_NAME)
        self.client.cookies.clear()
        headers = {"Authorization": f"Bearer {token}"}
        response = await self.client.get("/api/users/me", headers=headers)
        self.assertEqual(response.json(), user)
        response = await self.client.post("/api/posts/", headers=headers,
                                          json={"title": "JWT post", "content": "Body"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["user_id"], user["id"])
        for _ in range(2):
            response = await self.client.post("/api/users/logout", headers=headers)
            self.assertEqual(response.status_code, 204, response.text)
        response = await self.client.get("/api/users/me", headers=headers)
        self.assertEqual(response.status_code, 401)
        async with database.SessionLocal() as db:
            self.assertIsNotNone(await db.get(RevokedToken, decode_access_token(token)["jti"]))

    async def test_invalid_authorization_does_not_fall_back_to_cookie(self):
        await self.register()
        for authorization in ("Bearer bad-token", "Basic invalid", "Bearer", ""):
            response = await self.client.get("/api/users/me", headers={"Authorization": authorization})
            self.assertEqual(response.status_code, 401, response.text)

    async def test_logout_with_invalid_cookie_still_clears_it(self):
        self.client.cookies.set(COOKIE_NAME, "old-opaque-session", domain="test.local", path="/")
        response = await self.client.post("/api/users/logout")
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))

    async def test_password_change_invalidates_existing_jwts(self):
        user = await self.register()
        token = self.client.cookies.get(COOKIE_NAME)
        refresh_token = self.client.cookies.get(REFRESH_COOKIE_NAME)
        response = await self.client.patch(f"/api/users/{user['id']}/update",
                                           json={"password": "Changed2"})
        self.assertEqual(response.status_code, 200)
        response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)
        response = await self.client.post("/api/users/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(response.status_code, 401)
        await self.login(password="Changed2")
        self.assertEqual((await self.client.get("/api/users/me")).status_code, 200)

    async def test_deleted_account_tokens_cannot_access_reused_user_id(self):
        user = await self.register()
        old_token = self.client.cookies.get(COOKIE_NAME)
        old_refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        # Log in independently so deletion only sees the second token.
        self.client.cookies.clear()
        await self.login()
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 204)
        self.client.cookies.clear()
        replacement = await self.register("replacement")
        self.assertEqual(replacement["id"], user["id"])
        response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {old_token}"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual((await self.client.get("/api/users/me")).json(), replacement)
        response = await self.client.post("/api/users/refresh", json={"refresh_token": old_refresh})
        self.assertEqual(response.status_code, 401)

    async def test_mutations_require_login_and_ignore_claimed_author(self):
        user = await self.register()
        response = await self.client.post("/api/posts/", json={
            "title": "Session author", "content": "Body", "user_id": 9999,
        })
        self.assertEqual(response.status_code, 201, response.text)
        post = response.json()
        self.assertEqual(post["user_id"], user["id"])
        await self.client.post("/api/users/logout")
        cases = [
            ("POST", "/api/posts/", {"title": "No login", "content": "Body", "user_id": user["id"]}),
            ("PATCH", f"/api/posts/{post['id']}?user_id={user['id']}", {"title": "No login"}),
            ("DELETE", f"/api/posts/{post['id']}?user_id={user['id']}", None),
            ("PATCH", f"/api/users/{user['id']}/update", {"username": "hijacked"}),
            ("DELETE", f"/api/users/{user['id']}/delete", None),
        ]
        for method, url, body in cases:
            with self.subTest(method=method, url=url):
                response = await self.client.request(method, url, json=body)
                self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual((await self.client.get(f"/api/posts/{post['id']}")).json(), post)

    async def test_users_cannot_modify_other_accounts(self):
        alice = await self.register()
        await self.register("bob")
        response = await self.client.patch(f"/api/users/{alice['id']}/update",
                                           json={"password": "Hijacked1"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.delete(f"/api/users/{alice['id']}/delete")
        self.assertEqual(response.status_code, 403)
        await self.login("alice")

    async def test_cross_origin_writes_rejected(self):
        await self.register()
        for path, body in [
            ("/api/users/login", {"username": "alice", "password": "Password1"}),
            ("/api/users/register", {"username": "mallory", "email": "m@example.com", "password": "Password1"}),
            ("/api/users/logout", None),
            ("/api/users/refresh", None),
            ("/api/posts/", {"title": "CSRF", "content": "Body"}),
        ]:
            response = await self.client.post(path, json=body, headers={"Origin": "https://other.example"})
            self.assertEqual(response.status_code, 403, response.text)
        response = await self.client.post("/api/posts/", json={"title": "Allowed", "content": "Body"},
                                          headers={"Origin": "http://test"})
        self.assertEqual(response.status_code, 201, response.text)

    async def test_new_login_rotates_jwt_and_https_cookie_is_secure(self):
        await self.register()
        old_cookie = self.client.cookies.get(COOKIE_NAME)
        old_refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        await self.login()
        self.assertNotEqual(old_cookie, self.client.cookies.get(COOKIE_NAME))
        response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {old_cookie}"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual((await self.client.get("/api/users/me")).status_code, 200)
        response = await self.client.post("/api/users/refresh", json={"refresh_token": old_refresh})
        self.assertEqual(response.status_code, 401)
        self.assertEqual((await self.client.get("/api/users/me")).status_code, 200)
        response = await self.client.post("https://test/api/users/login", json={
            "username": "alice", "password": "Password1",
        })
        self.assertIn("Secure", response.headers["set-cookie"])
        for cookie in response.headers.get_list("set-cookie"):
            self.assertIn("Secure", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=lax", cookie)

    async def test_refresh_after_access_expiry_rotates_and_restores_access(self):
        user = await self.register()
        old_access = self.client.cookies.get(COOKIE_NAME)
        old_refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        async with database.SessionLocal() as db:
            stored = await db.get(RefreshToken, refresh_token_hash(old_refresh))
            self.assertIsNotNone(stored)
            self.assertNotEqual(stored.token_hash, old_refresh)
            expiry = stored.expires_at
        claims = decode_access_token(old_access)
        now = int(datetime.now(UTC).timestamp())
        expired = jwt.encode({**claims, "iat": now - 3600, "nbf": now - 3600, "exp": now - 1},
                             settings.JWT_SECRET_KEY.get_secret_value(), algorithm=JWT_ALGORITHM)
        self.client.cookies.set(COOKIE_NAME, expired, domain="test.local", path="/")
        self.assertEqual((await self.client.get("/api/users/me")).status_code, 401)
        response = await self.client.post("/api/users/refresh")
        self.assertEqual(response.status_code, 200, response.text)
        tokens = response.json()
        self.assertNotEqual(tokens["access_token"], old_access)
        self.assertNotEqual(tokens["refresh_token"], old_refresh)
        self.assertEqual(self.client.cookies.get(REFRESH_COOKIE_NAME), tokens["refresh_token"])
        self.assertEqual(tokens["token_type"], "bearer")
        self.assertEqual(tokens["expires_in"], 1800)
        self.assertGreater(tokens["refresh_expires_in"], 6 * 86400)
        self.assertLessEqual(tokens["refresh_expires_in"], 7 * 86400)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual((await self.client.get("/api/users/me")).json(), user)
        response = await self.client.post("/api/posts/", json={"title": "Renewed", "content": "Body"})
        self.assertEqual(response.status_code, 201, response.text)
        async with database.SessionLocal() as db:
            self.assertTrue((await db.get(RefreshToken, refresh_token_hash(old_refresh))).used)
            new = await db.get(RefreshToken, refresh_token_hash(tokens["refresh_token"]))
            self.assertEqual(new.expires_at, expiry)  # Rotation does not extend the session indefinitely.
            self.assertEqual(new.session_id, claims["sid"])

    async def test_replaying_refresh_revokes_whole_session_only(self):
        await self.register()
        old_access = self.client.cookies.get(COOKIE_NAME)
        old_refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        rotated = await self.client.post("/api/users/refresh")
        new_access = rotated.json()["access_token"]
        new_refresh = rotated.json()["refresh_token"]
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as other:
            await other.post("/api/users/login", json={"username": "alice", "password": "Password1"})
            replay = await self.client.post("/api/users/refresh", json={"refresh_token": old_refresh})
            self.assertEqual(replay.status_code, 401)
            self.assertEqual(replay.headers["cache-control"], "no-store")
            for token in (old_access, new_access):
                response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(response.status_code, 401)
            response = await self.client.post("/api/users/refresh", json={"refresh_token": new_refresh})
            self.assertEqual(response.status_code, 401)
            self.assertEqual((await other.get("/api/users/me")).status_code, 200)

    async def test_refresh_rejects_missing_invalid_and_access_tokens(self):
        await self.register()
        access = self.client.cookies.get(COOKIE_NAME)
        refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {refresh}"})
        self.assertEqual(response.status_code, 401)
        # Oversized credentials fail request validation before authentication.
        for invalid, expected_status in ((access, 422), ("invalid-refresh", 401)):
            # An explicit body must not fall back to the valid browser cookie.
            response = await self.client.post("/api/users/refresh", json={"refresh_token": invalid})
            self.assertEqual(response.status_code, expected_status)
        self.client.cookies.clear()
        self.assertEqual((await self.client.post("/api/users/refresh")).status_code, 401)
        response = await self.client.post("/api/users/refresh", json={"refresh_token": refresh})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.cookies.clear()
        response = await self.client.get("/api/users/me", headers={
            "Authorization": f"Bearer {response.json()['access_token']}",
        })
        self.assertEqual(response.status_code, 200)

    async def test_expired_refresh_token_requires_login(self):
        await self.register()
        refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        async with database.SessionLocal() as db:
            stored = await db.get(RefreshToken, refresh_token_hash(refresh))
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
        response = await self.client.post("/api/users/refresh")
        self.assertEqual(response.status_code, 401)

    async def test_logout_without_access_cookie_revokes_refresh(self):
        await self.register()
        old_access = self.client.cookies.get(COOKIE_NAME)
        refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        self.client.cookies.delete(COOKIE_NAME)
        response = await self.client.post("/api/users/logout")
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))
        self.assertIsNone(self.client.cookies.get(REFRESH_COOKIE_NAME))
        response = await self.client.post("/api/users/refresh", json={"refresh_token": refresh})
        self.assertEqual(response.status_code, 401)
        response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {old_access}"})
        self.assertEqual(response.status_code, 401)

    async def test_api_logout_revokes_rotated_session_tokens(self):
        await self.register()
        old_access = self.client.cookies.get(COOKIE_NAME)
        response = await self.client.post("/api/users/refresh")
        access, refresh = response.json()["access_token"], response.json()["refresh_token"]
        self.client.cookies.clear()
        response = await self.client.post("/api/users/logout", json={"refresh_token": refresh})
        self.assertEqual(response.status_code, 204)
        for token in (old_access, access):
            response = await self.client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 401)
        response = await self.client.post("/api/users/refresh", json={"refresh_token": refresh})
        self.assertEqual(response.status_code, 401)

    async def test_concurrent_refresh_cannot_use_token_twice(self):
        await self.register()
        refresh = self.client.cookies.get(REFRESH_COOKIE_NAME)
        async def rotate():
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                return await client.post("/api/users/refresh", json={"refresh_token": refresh})
        responses = await asyncio.gather(rotate(), rotate())
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401])
        winner = next(response.json() for response in responses if response.status_code == 200)
        # The duplicate request is a replay, so even the newly issued token is revoked.
        response = await self.client.post("/api/users/refresh", json={"refresh_token": winner["refresh_token"]})
        self.assertEqual(response.status_code, 401)

    def picture(self, format="PNG", size=(800, 400)):
        output = BytesIO()
        Image.new("RGB", size, "steelblue").save(output, format=format)
        return output.getvalue()

    async def upload_picture(self, data=None, filename="portrait.png", content_type="image/png", **kwargs):
        return await self.client.put("/api/users/me/image", files={
            "image": (filename, self.picture() if data is None else data, content_type),
        }, **kwargs)

    async def test_upload_replace_and_reset_profile_picture(self):
        user = await self.register()
        post = await self.create_post(user["id"])
        previous = None
        for format, content_type in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
            with self.subTest(format=format):
                response = await self.upload_picture(self.picture(format), "../../avatar.jpg", content_type)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
                profile = response.json()
                self.assertEqual(profile["id"], user["id"])
                self.assertRegex(profile["image_file"], r"^[a-f0-9]{32}\.png$")
                self.assertNotEqual(profile["image_file"], previous)
                self.assertNotIn("password", profile)
                self.assertEqual((await self.client.get("/api/users/me")).json(), profile)
                self.assertEqual((await self.login()).json()["image_path"], profile["image_path"])
                served = await self.client.get(profile["image_path"])
                self.assertEqual(served.status_code, 200)
                self.assertEqual(served.headers["content-type"], "image/png")
                with Image.open(BytesIO(served.content)) as image:
                    self.assertEqual(image.size, (512, 256))
                for url in ("/", f"/posts/{post['id']}", f"/users/{user['id']}/posts"):
                    page = await self.client.get(url)
                    self.assertIn(profile["image_path"], page.text)
                    self.assertIn('href="http://test/account"', page.text)
                if previous:
                    self.assertFalse((self.profile_directory / previous).exists())
                self.assertEqual(len(list(self.profile_directory.iterdir())), 1)
                previous = profile["image_file"]
        for _ in range(2):
            reset = await self.client.delete("/api/users/me/image")
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertEqual(reset.json()["image_path"], "/static/profile_pics/default.jpg")
            self.assertIsNone(reset.json()["image_file"])
        self.assertEqual(list(self.profile_directory.iterdir()), [])
        self.assertEqual((await self.client.get(reset.json()["image_path"])).status_code, 200)
        self.assertEqual((await self.client.get(profile["image_path"])).status_code, 404)

    async def test_invalid_uploads_preserve_existing_picture(self):
        await self.register()
        profile = (await self.upload_picture()).json()
        invalid = [b"", b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                   self.picture("GIF"), self.picture()[:40]]
        for data in invalid:
            response = await self.upload_picture(data)
            self.assertEqual(response.status_code, 400, response.text)
        response = await self.upload_picture(b"x" * (profile_images.MAX_IMAGE_BYTES + 1))
        self.assertEqual(response.status_code, 413, response.text)
        with patch.object(profile_images, "MAX_IMAGE_PIXELS", 100):
            response = await self.upload_picture(self.picture(size=(11, 10)))
            self.assertEqual(response.status_code, 400, response.text)
        missing = await self.client.put("/api/users/me/image")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual((await self.client.get("/api/users/me")).json(), profile)
        self.assertEqual([path.name for path in self.profile_directory.iterdir()], [profile["image_file"]])

    async def test_picture_updates_require_login_and_same_origin(self):
        alice = await self.register()
        original = (await self.upload_picture()).json()
        token = self.client.cookies.get(COOKIE_NAME)
        self.client.cookies.clear()
        self.assertEqual((await self.upload_picture()).status_code, 401)
        self.assertEqual((await self.client.delete("/api/users/me/image")).status_code, 401)
        headers = {"Authorization": f"Bearer {token}", "Origin": "https://other.example"}
        self.assertEqual((await self.upload_picture(headers=headers)).status_code, 403)
        self.assertEqual((await self.client.delete("/api/users/me/image", headers=headers)).status_code, 403)
        headers["Origin"] = "http://test"
        self.assertEqual((await self.upload_picture(headers=headers)).status_code, 200)
        alice_profile = (await self.client.get(f"/api/users/{alice['id']}/profile")).json()
        await self.register("bob")
        await self.upload_picture()
        await self.client.delete("/api/users/me/image")
        self.assertEqual((await self.client.get(f"/api/users/{alice['id']}/profile")).json(), alice_profile)
        self.assertTrue((self.profile_directory / alice_profile["image_file"]).exists())
        self.assertFalse((self.profile_directory / original["image_file"]).exists())

    async def test_picture_database_failure_cleans_new_upload(self):
        await self.register()
        original = (await self.upload_picture()).json()
        for operation in ("upload", "reset"):
            with patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=RuntimeError("commit failed"))):
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    if operation == "upload":
                        await self.upload_picture()
                    else:
                        await self.client.delete("/api/users/me/image")
            self.assertEqual((await self.client.get("/api/users/me")).json(), original)
            self.assertEqual([path.name for path in self.profile_directory.iterdir()], [original["image_file"]])

    async def test_picture_processing_runs_in_worker_and_strips_metadata(self):
        await self.register()
        event_loop_thread = threading.get_ident()
        worker_threads = []
        original_save = profile_images.save_profile_image

        def save(data):
            worker_threads.append(threading.get_ident())
            return original_save(data)

        source = Image.new("RGB", (80, 40), "red")
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise.
        exif[315] = "Private author metadata"
        output = BytesIO()
        source.save(output, format="JPEG", exif=exif)
        with patch("app.api.endpoints.user.save_profile_image", side_effect=save):
            response = await self.upload_picture(output.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(worker_threads)
        self.assertNotIn(event_loop_thread, worker_threads)
        with Image.open(self.profile_directory / response.json()["image_file"]) as image:
            self.assertEqual(image.size, (40, 80))
            self.assertFalse(image.getexif())

    async def test_filename_assignment_rejected_and_account_changes_clean_uploads(self):
        user = await self.register()
        for filename in ("../../secret", "another-users-picture.png"):
            response = await self.client.patch(f"/api/users/{user['id']}/update", json={"image_file": filename})
            self.assertEqual(response.status_code, 422)
            response = await self.client.post("/api/users/register", json={
                "username": "bob", "email": "bob@example.com", "password": "Password1", "image_file": filename,
            })
            self.assertEqual(response.status_code, 422)
        await self.upload_picture()
        response = await self.client.patch(f"/api/users/{user['id']}/update", json={"image_file": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(list(self.profile_directory.iterdir()), [])
        await self.upload_picture()
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(list(self.profile_directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
