from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers.post import router as posts_router
from app.api.routers.user import router as users_router
from app.api.endpoints.health import router as health_router
from app.core.exceptions import exception_handlers
from app.core.lifespan import lifespan
from app.web.routes import router as pages_router
from app.utils.profile_images import MEDIA_DIR

OPENAPI_TAGS = [
    {
        "name": "Posts",
        "description": "Browse posts. Creating, editing, and deleting posts requires sign-in; only the author can change or delete a post.",
    },
    {
        "name": "Engagement",
        "description": "Read public like counts and comments. A signed-in user can like once, remove their like, comment, and delete their own comments.",
    },
    {
        "name": "Users",
        "description": "Create an account, manage your session and profile, and browse public user profiles and posts.",
    },
    {
        "name": "Health",
        "description": "Application readiness checks, including the database connection.",
    },
]

app = FastAPI(
    title="Awesome Blog API",
    summary="Posts, profiles, likes, and comments",
    description=(
        "API for the Awesome Blog application.\n\n"
        "### Authentication\n"
        "Protected routes accept the `blog_session` HttpOnly cookie or a Bearer access token. "
        "Use the login and refresh routes to manage a session. Browser write requests must be same-origin.\n\n"
        "### Pagination\n"
        "Collection routes accept `page` (default `1`) and `per_page` (default `10`, maximum `100`). "
        "Post collections also report totals in `X-Total-Count`, `X-Total-Pages`, `X-Page`, and `X-Per-Page`."
    ),
    version="1.0.0",
    openapi_tags=OPENAPI_TAGS,
    docs_url=None,
    swagger_ui_parameters={
        "deepLinking": True,
        "displayRequestDuration": True,
        "docExpansion": "list",
        "filter": True,
        "operationsSorter": "method",
        "persistAuthorization": False,
        "tagsSorter": "alpha",
    },
    lifespan=lifespan,
    exception_handlers=exception_handlers,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

app.include_router(posts_router)
app.include_router(users_router)
app.include_router(health_router)
app.include_router(pages_router)


@app.get("/docs", include_in_schema=False)
async def swagger_docs() -> HTMLResponse:
    docs = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — API Documentation",
        swagger_favicon_url="/static/icons/favicon.ico",
        swagger_ui_parameters=app.swagger_ui_parameters,
    )
    html = docs.body.decode("utf-8")
    html = html.replace(
        '<div id="swagger-ui">',
        '<header class="docs-hero">'
        '<div class="docs-hero-inner">'
        '<span class="docs-kicker">AWESOME BLOG · DEVELOPER PORTAL</span>'
        '<h1>Awesome Blog API</h1>'
        '<p>Explore the API, review request formats, and try endpoints against your local app.</p>'
        '<span class="docs-version">REST API <b>·</b> v1.0.0 <b>·</b> OpenAPI</span>'
        '</div></header>'
        '<div id="swagger-ui">',
    )
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/static/css/api-docs.css"></head>',
    )
    return HTMLResponse(html)
