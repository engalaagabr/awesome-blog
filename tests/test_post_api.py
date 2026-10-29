from tests._async_app_test_base import (
    AsyncAppTestCase,
    Post,
    UTC,
    User,
    database,
    datetime,
    timedelta,
)

class PostAPITests(AsyncAppTestCase):
    async def test_post_crud_and_api_relationships(self):
        user = await self.register()
        post = await self.create_post(user["id"])
        self.assertEqual(post["author"], "alice")
        post_url = f"/api/posts/{post['id']}"
        response = await self.client.get(post_url)
        self.assertEqual(response.json(), {**post, "likes_count": 0, "comments_count": 0})
        for url in ("/api/posts/", f"/api/users/{user['id']}/posts"):
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), [post])
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

    async def test_post_pagination(self):
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
