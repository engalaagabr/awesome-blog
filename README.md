# Awesome Blog API

An asynchronous REST API for accounts, posts, likes, and comments, built with FastAPI and PostgreSQL.

## Quick setup

Requires Docker with the Compose plugin. Copy the example environment file and edit `.env`: set a URL-safe `POSTGRES_PASSWORD` and a private `JWT_SECRET_KEY` (at least 32 characters). Generate a key with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Start PostgreSQL, apply migrations, and run the API:

```bash
cp .env.example .env
docker compose up --build -d --wait
```

The API is available at `http://localhost:8082`. Check it with `curl http://localhost:8082/health`; open `http://localhost:8082/docs` to browse and try the endpoints. Use `docker compose down` to stop the services while keeping their data.

## Basic usage

Register a local test account, then log in and save its session cookie:

```bash
curl -X POST http://localhost:8082/api/users/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","email":"demo@example.com","password":"ChangeMe1"}'

curl -i -c cookies.txt http://localhost:8082/api/users/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","password":"ChangeMe1"}'
```

Use the cookie to read your profile or create a post:

```bash
curl -b cookies.txt http://localhost:8082/api/users/me

curl -b cookies.txt -X POST http://localhost:8082/api/posts/ \
  -H 'Content-Type: application/json' \
  -d '{"title":"My first post","content":"Hello from the API."}'
```

See the [Project Guide](docs/PROJECT_GUIDE.md) for local development, all endpoints, authentication details, migrations, and tests.
