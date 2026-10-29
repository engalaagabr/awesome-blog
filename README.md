# Awesome Blog API

An async REST API for user accounts, posts, likes, and comments. It uses FastAPI, SQLAlchemy async, PostgreSQL, and Alembic. Interactive API documentation is available at `/docs`.

## Features

- User registration, login, logout, refresh-token rotation, and profile management.
- Create, list, update, and delete posts with paginated collections.
- Like and unlike posts; browse and manage comments.
- HttpOnly cookie sessions for browser clients and Bearer tokens for API clients.
- PostgreSQL migrations, health checks, and Docker Compose setup.
- Profile image uploads with format, size, and image-processing limits.

## Run with Docker Compose

Copy the example settings and create private values for the database password and JWT secret:

```bash
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set `POSTGRES_PASSWORD` to a URL-safe password and put the generated value in `JWT_SECRET_KEY` in `.env`. Keep `.env` private; it is ignored by Git. Then start the stack:

```bash
docker compose config --quiet
docker compose up --build -d --wait
```

The API listens on `http://localhost:8082` by default. Open `http://localhost:8082/docs` for Swagger UI, `http://localhost:8082/redoc` for ReDoc, or `http://localhost:8082/health` for readiness status. Set `BLOG_PORT` to change the host port.

Stop the services while keeping database and uploaded images:

```bash
docker compose down
```

`docker compose down --volumes` also deletes persisted data.

## Run locally

Create `.env` as above, then install development dependencies and start PostgreSQL:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

The local `DATABASE_URL` in `.env.example` points to PostgreSQL on `localhost`. Compose overrides it with the database service address for containers.

## API overview

All resources are documented in `/docs` and `/openapi.json`. Main routes include:

| Route | Purpose |
| --- | --- |
| `GET /health` | Check application and database readiness. |
| `POST /api/users/register` | Create an account. |
| `POST /api/users/login` | Start a session and receive access/refresh tokens. |
| `POST /api/users/refresh` | Rotate a refresh token. |
| `GET /api/users/me` | Read the authenticated user's profile. |
| `GET /api/posts/` | Browse posts with pagination. |
| `POST /api/posts/` | Create a post as the authenticated user. |
| `GET /api/posts/{post_id}` | Read a post and its like/comment counts. |
| `GET /api/posts/{post_id}/comments` | Browse paginated comments. |
| `PUT /api/posts/{post_id}/like` | Like a post. |

Protected routes accept the `blog_session` cookie or an `Authorization: Bearer <access-token>` header. Browser write requests must be same-origin. Collection routes accept `page` and `per_page`; post lists include pagination totals in response headers.

## Migrations

Create and review a migration after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

Use `alembic current` to display the database revision. Read generated migrations before applying them to important data.

## Tests

The Python test suite uses isolated SQLite databases and does not require the Compose database:

```bash
python -m unittest discover -s tests -v
```

## Project layout

- `app/api/` — REST endpoints and routers.
- `app/core/` — configuration, authentication, database sessions, and error handling.
- `app/models/` and `app/schemas/` — SQLAlchemy models and Pydantic schemas.
- `alembic/` — database migrations.
- `tests/` — API integration tests.
- `docs/` — additional Arabic setup and authentication guides.

## Configuration

See `.env.example` for the required environment variables. Never commit `.env`, production credentials, database files, or uploaded profile images.
