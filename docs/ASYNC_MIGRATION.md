# Sync to async migration

The database dependency, API endpoints, HTML routes, and application startup now use SQLAlchemy's async API. While a database operation is waiting, the event loop can serve other requests. This does not make individual queries faster or remove SQLite's write concurrency limits.

Your existing partial conversion in `app/core/database.py` and the `aiosqlite` dependency were retained and completed. Your `.env` already selected `sqlite+aiosqlite`, so it did not need editing. The database schema and existing data do not need conversion.

## What changed and why

| File | Change | Reason |
| --- | --- | --- |
| `app/core/database.py` | Uses `create_async_engine`, `async_sessionmaker`, and a typed async `get_db()` dependency. | Each request gets its own session, closed by `async with` afterward. |
| `app/core/database.py` | Sets `expire_on_commit=False`. | Keeps loaded attributes available after commit without triggering implicit database reads during serialization. |
| `app/core/database.py` | Removes the SQLite-specific `check_same_thread` argument and redundant `autocommit=False`. | Uses the async driver's defaults and keeps connection configuration free of a synchronous SQLite workaround. |
| `app/api/endpoints/post.py` | Converts all handlers to `async def`, uses `select()` or awaited `get()`, and awaits writes. | The handlers now use the async session correctly. A 204 delete response returns no object. |
| `app/api/endpoints/user.py` | Converts registration, login, profile, posts, update, and deletion to async database access. | Completes the request flow instead of mixing async sessions with synchronous queries. |
| `app/main.py` | Converts database-backed HTML routes to async. | Pages use the same async session dependency as the API. |
| `app/main.py` | Creates tables through `await connection.run_sync(Base.metadata.create_all)` and disposes the engine in `finally`. | Schema creation uses the async connection correctly, and shutdown releases pooled connections. |
| `app/models/post.py` | Sets `Post.author` to `lazy="joined"`. | Every post response and template reads its author; fetching both together prevents a hidden database read during rendering. |
| `app/api/endpoints/user.py`, `app/main.py` | Uses `selectinload(User.posts)` for user-post lists. | Loads the collection during an awaited query before code accesses `user.posts`. The posts also load their authors. |
| `app/api/endpoints/user.py` | Wraps password hashing and verification in `await run_in_threadpool(...)`. | bcrypt is synchronous and expensive; worker threads keep it off the event loop. |
| `app/api/endpoints/user.py` | Removes `db.delete(user.posts)` and awaits deletion of the user. | A list cannot be passed to `delete()`. The existing `all, delete-orphan` relationship cascade deletes that user's posts. |
| `requirements.txt` | Uses `SQLAlchemy[asyncio]==2.1.5`; keeps `aiosqlite==0.22.1`. | Installs async support, including `greenlet`, which was missing from the local environment. |
| `requirements.txt`, `tests/test_async_app.py` | Adds HTTPX and async integration tests using standard-library `unittest`. | Verifies real database operations, serialization, and page rendering against temporary SQLite databases. |

## Before and after

A list query previously looked like this:

```python
def get_posts(db: Session = Depends(get_db)):
    return db.query(Post).all()
```

It now looks like this:

```python
async def get_posts(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Post))).all()
```

`await db.scalars(...)` performs the database operation. Its buffered result can then use `.all()` without another `await`.

Writes now use:

```python
db.add(new_post)
await db.commit()
await db.refresh(new_post)
```

`add()` only tracks an object in memory, so it remains synchronous. `commit()` writes the transaction; `refresh()` reloads database values and, with the configured eager relationship, the author. `get()` and `delete()` also need `await` with `AsyncSession`; deletion may need database reads for cascades.

Only the code that needs async execution changed to `async def`. Models, Pydantic validators, password helper implementations, and exception handlers remain ordinary synchronous functions. Password helpers are called through the thread pool. Jinja rendering remains synchronous and receives already-loaded database objects.

## Relationship loading matters

`PostResponse` reads `post.author.username`, and the HTML templates read the author's name and image. Without eager loading, these ordinary attribute accesses could attempt database I/O outside an awaited operation and fail with `MissingGreenlet`. Joined loading handles the author; select-in loading handles a user's post collection. New queries that expose other relationships should load them explicitly before returning ORM objects.

Each request owns a session. Do not share a single `AsyncSession` between concurrent tasks. The dependency closes its session even when an error occurs, rolling back uncommitted work. Commits are still explicit in the endpoints.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

For SQLite, `.env` must use the async driver:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./blog.db
```

This points to the same SQLite file; there is no need to delete it. Run from the project root because the database and static/template paths are relative. The existing `app/media` directory must also be present for the media mount.

## Verify the conversion

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests exercise startup/shutdown, post CRUD, author serialization, all database-backed HTML pages, login and password changes, profile updates, duplicate registration, missing resources, validation and ownership errors, user deletion cascades, concurrent reads, rollback after errors, and password work on worker threads. They use temporary database files and do not open your `blog.db`.

Current test status: 15 of 17 tests pass. The two duplicate username/email update tests fail because the update endpoint returns HTTP 500 instead of a handled client error. These failures remain visible until conflict handling is implemented.

References: [SQLAlchemy asyncio documentation](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html) and [Starlette thread pool documentation](https://starlette.dev/threadpool/).
