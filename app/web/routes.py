from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.web.templates import templates

router = APIRouter(include_in_schema=False)


@router.get("/account", name="account")
async def account(request: Request):
    # Personal details are loaded by the authenticated /api/users/me endpoint.
    return templates.TemplateResponse(request, "account.html", {"title": "Account Settings"})


@router.get("/", name="home")
@router.get("/posts", name="posts")
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    posts = (await db.scalars(select(Post).order_by(Post.date_posted.desc()))).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"posts": posts, "title": "Home"},
    )


@router.get("/posts/{post_id}")
async def post_page(request: Request, post_id: int, db: AsyncSession = Depends(get_db)):
    post = await db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    return templates.TemplateResponse(
        request,
        "post.html",
        {"post": post, "title": post.title[:50]},
    )


@router.get("/users/{user_id}/posts")
async def user_posts(request: Request, user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id, options=[selectinload(User.posts)])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return templates.TemplateResponse(
        request,
        "user_posts.html",
        {"user": user, "posts": user.posts, "title": f"Posts by {user.username}"},
    )
