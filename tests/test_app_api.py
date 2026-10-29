from tests._async_app_test_base import (
    AsyncAppTestCase,
    User,
    asyncio,
    database,
    select,
)

class AppAPITests(AsyncAppTestCase):
    async def test_pagination_validation_and_empty_results(self):
        user = await self.register(login=False)
        urls = ("/api/posts/", f"/api/users/{user['id']}/posts")
        for url in urls:
            for params in ({"page": 0}, {"page": -1}, {"page": "bad"},
                           {"per_page": 0}, {"per_page": 101}, {"per_page": "bad"}):
                with self.subTest(url=url, params=params):
                    response = await self.client.get(url, params=params)
                    self.assertEqual(response.status_code, 422, response.text)
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), [])
            self.assertEqual(response.headers["x-total-count"], "0")
            self.assertEqual(response.headers["x-total-pages"], "0")

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
        for url in ("/api/posts/9999", "/api/users/9999/profile", "/api/users/9999/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.post("/api/posts/", json={
            "title": "Missing user", "content": "Content", "user_id": 9999,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user_id"], other["id"])
        response = await self.client.get("/api/posts/not-an-int")
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
            self.assertEqual(response.json(), {**post, "likes_count": 0, "comments_count": 0})

    async def test_dependency_rolls_back_uncommitted_work_on_error(self):
        dependency = database.get_db()
        session = await anext(dependency)
        session.add(User(username="rollback", email="rollback@example.com", password="unused"))
        await session.flush()
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            await dependency.athrow(RuntimeError("request failed"))
        async with database.SessionLocal() as fresh_session:
            self.assertIsNone(await fresh_session.scalar(select(User)))

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
        ]
        for method, url, body in cases:
            with self.subTest(method=method, url=url):
                response = await self.client.request(method, url, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIsInstance(response.json()["detail"], list)

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

    async def test_deleting_user_without_posts(self):
        user = await self.register()
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        response = await self.client.delete(f"/api/users/{user['id']}/delete")
        self.assertEqual(response.status_code, 401)

    async def test_api_documentation_static_avatar_and_unknown_routes(self):
        for url in ("/docs", "/redoc", "/openapi.json", "/static/profile_pics/default.jpg"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 200)
        schema = (await self.client.get("/openapi.json")).json()
        operations = sum(len(methods) for methods in schema["paths"].values())
        self.assertEqual(operations, 24)
        for url in ("/api/missing", "/missing", "/media/missing.jpg"):
            with self.subTest(url=url):
                response = await self.client.get(url)
                self.assertEqual(response.status_code, 404)
        response = await self.client.put("/api/posts/", json={})
        self.assertEqual(response.status_code, 405)
        response = await self.client.get("/api/posts", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

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
