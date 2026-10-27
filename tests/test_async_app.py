"""Exercise real async database I/O without opening the project's blog.db."""

import asyncio
import os
import tempfile
import threading
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Keep importing the application independent of local .env credentials.
with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
    from app import main
    from app.core import database
    from app.models.user import User


class AsyncAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(directory) / 'test.db'}"
        )
        factory = async_sessionmaker(
            self.engine, autoflush=False, expire_on_commit=False
        )
        self.stack.enter_context(patch.object(main, "engine", self.engine))
        self.stack.enter_context(patch.object(database, "SessionLocal", factory))
        # Exercise the real startup, shutdown, and request session dependency.
        await self.stack.enter_async_context(main.app.router.lifespan_context(main.app))
        self.client = await self.stack.enter_async_context(
            AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")
        )

    async def register(self, username="alice"):
        response = await self.client.post("/api/users/register", json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Password1",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("password", response.json())
        return response.json()

    async def create_post(self, user_id, title="Async post"):
        response = await self.client.post("/api/posts/", json={
            "title": title, "content": "Async content", "user_id": user_id,
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

    async def test_login_profile_and_password_update(self):
        user = await self.register()
        response = await self.client.post("/api/users/login", json={
            "username": "alice", "password": "Password1",
        })
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.get(f"/api/users/{user['id']}/profile")
        self.assertEqual(response.json(), user)
        response = await self.client.patch(f"/api/users/{user['id']}/update", json={
            "username": "alice_new", "password": "Changed2", "image_file": "avatar.jpg",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["image_path"], "/media/profile_pics/avatar.jpg")
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
        for method, body in (("PATCH", {"title": "Forbidden"}), ("DELETE", None)):
            response = await self.client.request(method, url,
                params={"user_id": user["id"] + 1}, json=body)
            self.assertEqual(response.status_code, 403, response.text)
        for url in ("/api/posts/9999", "/api/users/9999/profile", "/api/users/9999/posts",
                    "/posts/9999", "/users/9999/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.post("/api/posts/", json={
            "title": "Missing user", "content": "Content", "user_id": 9999,
        })
        self.assertEqual(response.status_code, 404)
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
            user = await self.register()
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
        cases = [
            ("GET", "/api/posts/bad", None),
            ("PATCH", "/api/posts/bad?user_id=1", {"title": "Valid"}),
            ("DELETE", "/api/posts/bad?user_id=1", None),
            ("PATCH", "/api/posts/1", {"title": "Valid"}),
            ("DELETE", "/api/posts/1", None),
            ("PATCH", "/api/posts/1?user_id=bad", {"title": "Valid"}),
            ("DELETE", "/api/posts/1?user_id=bad", None),
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
        self.assertEqual(response.status_code, 404)

    async def test_documentation_static_files_and_unknown_routes(self):
        for url in ("/docs", "/redoc", "/openapi.json", "/static/css/main.css",
                    "/static/profile_pics/default.jpg"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 200)
        schema = (await self.client.get("/openapi.json")).json()
        operations = sum(len(methods) for methods in schema["paths"].values())
        self.assertEqual(operations, 11)
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
            base_url="http://test",
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


if __name__ == "__main__":
    unittest.main()
