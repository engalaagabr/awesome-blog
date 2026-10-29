# Awesome Blog API — Project Guide

## Overview

Awesome Blog is an asynchronous REST API for user accounts, posts, likes, and comments. It is built with FastAPI, SQLAlchemy's async ORM, PostgreSQL, and Alembic. The repository contains the API and its developer documentation; it does not include a blog website or frontend application.

FastAPI exposes interactive Swagger UI at `/docs`, ReDoc at `/redoc`, and the OpenAPI schema at `/openapi.json`.

## Features

- Account registration, login, logout, profile updates, and account deletion.
- HttpOnly cookie sessions and Bearer access tokens for API clients.
- Short-lived access tokens with rotating refresh tokens and replay detection.
- Public post and profile browsing, with owner-only post mutations.
- Post likes and paginated comments.
- Profile picture uploads with format, size, and pixel limits.
- Async database sessions, PostgreSQL migrations, health checks, and Docker Compose.
- Integration tests that use isolated temporary SQLite databases.

## Requirements

- Python 3.14 for local development.
- Docker Engine with the Docker Compose plugin for the containerized setup.
- PostgreSQL 17 when running the database outside the provided Compose stack.

The container image uses `python:3.14-slim`. Python packages are pinned in `requirements.txt`; `requirements-dev.txt` adds SQLite's async driver for tests.

## Configuration

Create a local environment file from the example:

```bash
cp .env.example .env
```

Set the PostgreSQL password and generate a private signing key:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Put the generated value in `JWT_SECRET_KEY`. Use a URL-safe PostgreSQL password because Compose interpolates it into `DATABASE_URL`. Never commit `.env` or use example credentials in a deployed environment.

| Variable | Purpose | Default or constraint |
| --- | --- | --- |
| `POSTGRES_DB` | PostgreSQL database name used by Compose. | Required by Compose. |
| `POSTGRES_USER` | PostgreSQL username used by Compose. | Required by Compose. |
| `POSTGRES_PASSWORD` | PostgreSQL password used by Compose. | Required by Compose; choose a URL-safe value. |
| `DATABASE_URL` | SQLAlchemy async database connection string. | Required by the app; `.env.example` points to local PostgreSQL. |
| `POSTGRES_PORT` | Host port for PostgreSQL. | `5432` |
| `BLOG_PORT` | Host port for the API. | `8082` |
| `JWT_SECRET_KEY` | HS256 signing secret. | Required; at least 32 characters. |
| `JWT_ACCESS_TOKEN_MINUTES` | Access token lifetime. | `30`; allowed range 1–10,080. |
| `REFRESH_TOKEN_DAYS` | Absolute session lifetime. | `7`; allowed range 1–90. |

Compose overrides `DATABASE_URL` inside the migration and API containers to use the `db` service hostname. The host-side value in `.env` remains useful for Alembic and local Uvicorn commands.

## Run with Docker Compose

After creating and editing `.env`, validate and start the services:

```bash
docker compose config --quiet
docker compose up --build -d --wait
```

The startup order is:

1. PostgreSQL starts and passes its `pg_isready` health check.
2. The `migrate` service applies all pending Alembic revisions.
3. The `web` service starts after migrations succeed.

The API is available at `http://localhost:8082` by default. Change `BLOG_PORT` to select another host port. The published ports bind to loopback by default.

Useful URLs:

- `http://localhost:8082/docs` — Swagger UI.
- `http://localhost:8082/redoc` — ReDoc.
- `http://localhost:8082/openapi.json` — OpenAPI JSON.
- `http://localhost:8082/health` — API and database readiness.

Stop the services without deleting persisted data:

```bash
docker compose down
```

Remove the PostgreSQL and uploaded-media volumes only when you intend to delete their data:

```bash
docker compose down --volumes
```

## Run locally

Create a Python environment, install development requirements, and start PostgreSQL through Compose:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

The app listens on `http://127.0.0.1:8000` in this setup. Stop the local server with `Ctrl+C`; stop the database with `docker compose stop db`.

## API reference

All API routes are under `/api`. The complete request and response schemas are available at `/docs` and `/openapi.json`.

### Health

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/health` | Public | Returns `200` when the database responds to a health query, or `503` when the database is unavailable. |

### Users and sessions

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/api/users/register` | Public | Creates an account. |
| `POST` | `/api/users/login` | Public | Starts a session and returns access and refresh tokens; also sets session cookies. |
| `POST` | `/api/users/refresh` | Refresh token | Rotates the refresh token and returns a new token pair. |
| `POST` | `/api/users/logout` | Public; accepts current cookies or an optional refresh token | Revokes the current session and clears cookies. |
| `GET` | `/api/users/me` | Authenticated | Returns the signed-in user's private profile. |
| `PUT` | `/api/users/me/image` | Authenticated | Uploads a profile picture using multipart field `image`. |
| `DELETE` | `/api/users/me/image` | Authenticated | Resets the profile picture to the default image. |
| `GET` | `/api/users/{user_id}/profile` | Public | Returns a user's public profile without email or password fields. |
| `GET` | `/api/users/{user_id}/posts` | Public | Returns the user's paginated posts. |
| `PATCH` | `/api/users/{user_id}/update` | Account owner | Updates the owner's username, email, password, or resets the image. |
| `DELETE` | `/api/users/{user_id}/delete` | Account owner | Deletes the account and its posts, likes, comments, and refresh sessions. |

Registration requires a username of 3–50 letters, digits, or underscores. Passwords must be 8–100 characters and include an uppercase letter, lowercase letter, and digit; the encoded password must not exceed 72 bytes. Username and email values must be unique.

### Posts

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/api/posts/` | Public | Lists posts newest first, with pagination totals in response headers. |
| `POST` | `/api/posts/` | Authenticated | Creates a post owned by the signed-in user. |
| `GET` | `/api/posts/{post_id}` | Public | Returns the post, author name, like count, and comment count. |
| `PATCH` | `/api/posts/{post_id}` | Post owner | Updates the title and/or content. |
| `DELETE` | `/api/posts/{post_id}` | Post owner | Deletes the post and its likes and comments. |

Post titles must contain 1–100 characters; content must contain 1–50,000 characters. Post collection responses use `PostResponse`; the individual detail route also includes `likes_count` and `comments_count`.

### Likes and comments

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/api/posts/{post_id}/likes` | Public | Returns the post's like count. |
| `GET` | `/api/posts/{post_id}/like` | Authenticated | Returns the like count and whether the current user has liked the post. |
| `PUT` | `/api/posts/{post_id}/like` | Authenticated | Likes the post; repeated requests do not create duplicate likes. |
| `DELETE` | `/api/posts/{post_id}/like` | Authenticated | Removes the current user's like, if present. |
| `GET` | `/api/posts/{post_id}/comments` | Public | Returns newest-first comments and pagination metadata. |
| `POST` | `/api/posts/{post_id}/comments` | Authenticated | Adds a comment as the signed-in user. |
| `DELETE` | `/api/posts/{post_id}/comments/{comment_id}` | Comment owner | Deletes the comment. |

Comment text must contain 1–2,000 characters. Users can delete only their own comments. Deleting a post cascades to its comments and likes.

## Authentication and security

### Cookie sessions

Login sets two HttpOnly cookies:

- `blog_session` — the access token.
- `blog_refresh` — the refresh token.

Cookies use `SameSite=Lax`; the `Secure` flag is enabled when the request uses HTTPS. Authenticated browser writes are checked against the request `Origin` when that header is present. Cookie sessions are suitable for same-origin clients.

Example using a cookie jar:

```bash
curl -i -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}' \
  http://localhost:8082/api/users/login

curl -b cookies.txt http://localhost:8082/api/users/me
```

To refresh a cookie session, call `POST /api/users/refresh` with the cookie jar. To sign out, call `POST /api/users/logout` with the same jar.

### Bearer tokens

Login and refresh responses contain `access_token`, `refresh_token`, `token_type`, and expiration values. API clients can use the access token as follows:

```bash
curl -H 'Authorization: Bearer ACCESS_TOKEN' \
  http://localhost:8082/api/users/me
```

To refresh without cookies, send the current refresh token as JSON to `POST /api/users/refresh`:

```json
{"refresh_token":"CURRENT_REFRESH_TOKEN"}
```

Replace both stored tokens with the new pair returned by the response. A refresh token can be used once. Replaying a rotated token revokes its session. Refresh rotation does not extend the session's original expiration time.

Access tokens are signed with HS256 and validated for issuer, audience, subject, timestamps, and credential version. Refresh-token digests are stored in the database instead of the raw tokens. Password changes invalidate sessions issued with the previous password; logout revokes the active token/session. Passwords are hashed before storage.

Protected routes accept either the `blog_session` cookie or a Bearer token. An explicit `Authorization` header takes precedence over the access cookie. Do not expose tokens in logs, source control, or client-side storage that is accessible to scripts.

## Profile pictures

Uploads accept JPEG, PNG, and WebP files up to 5 MB. Images larger than 16 megapixels are rejected. Accepted images are orientation-corrected, resized to fit within 512×512 pixels, re-encoded as PNG, and stripped of embedded metadata. The original filename is not used as the stored filename.

Uploaded images are served from `/media/profile_pics/`. The default image is served from `/static/profile_pics/default.jpg`. Docker Compose persists uploaded images in the `blog_media` volume.

## Pagination and errors

Post and user-post collections accept these query parameters:

| Parameter | Default | Allowed range |
| --- | --- | --- |
| `page` | `1` | `1` or greater |
| `per_page` | `10` | `1`–`100` |

Post collection responses include `X-Total-Count`, `X-Total-Pages`, `X-Page`, and `X-Per-Page` headers. Comments use a response object with `items`, `page`, `per_page`, and `total` fields. Invalid request bodies and parameters return `422`; API errors use JSON responses with a `detail` field.

## Database and migrations

The SQLAlchemy models represent these tables:

- `users` — account identity and password hash.
- `posts` — post title, content, author, and creation time.
- `post_likes` — one row per user/post pair; the composite primary key prevents duplicate likes.
- `comments` — comment content, author, post, and creation time.
- `refresh_tokens` — hashed rotating refresh tokens and session state.
- `revoked_tokens` — revoked access-token identifiers retained until expiry.
- `alembic_version` — current migration revision.

The migration history is in `alembic/versions/`. Compose applies migrations before starting the API. To create a migration after changing models:

```bash
alembic revision --autogenerate -m "describe the schema change"
```

Review and edit the generated migration before applying it. Useful commands:

```bash
alembic current
alembic history
alembic upgrade head
alembic downgrade -1
```

Review `downgrade()` before using it on important data because a downgrade can remove schema objects or data. `docker compose down` preserves data; `docker compose down --volumes` deletes the database and uploaded-media volumes.

## Tests

The Python API tests use `unittest.IsolatedAsyncioTestCase`, HTTPX, and a temporary SQLite database. They do not connect to the Compose PostgreSQL database or modify `blog.db`.

Install the development dependency and run the suite:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests are organized by domain in `tests/test_user_api.py`, `tests/test_post_api.py`, and `tests/test_app_api.py`. Shared database and client setup is in `tests/_async_app_test_base.py`.

## Project structure

```text
app/
  api/
    endpoints/       FastAPI endpoint implementations
    routers/         API route prefixes and composition
  core/              Settings, auth, database, errors, and lifespan
  media/             Runtime upload directory placeholder
  models/            SQLAlchemy tables and relationships
  schemas/           Pydantic request and response schemas
  static/            Default profile image served by the API
  utils/             Pagination and image processing
alembic/             Async migration environment and revisions
docs/                Project documentation
tests/               API integration tests
compose.yaml         PostgreSQL, migration, and API services
Dockerfile           Non-root API container image
requirements.txt     Runtime Python dependencies
requirements-dev.txt Development/test dependencies
```

## Operational notes

- The API container runs as an unprivileged user and has a Docker health check against `/health`.
- The Compose PostgreSQL and API ports bind to `127.0.0.1` by default. Configure an appropriate reverse proxy and network policy before exposing a deployment publicly.
- Provide secrets through a secret manager or protected environment variables in deployment. Do not bake secrets into the image or commit them to Git.
- Database backups and volume lifecycle are the operator's responsibility.
