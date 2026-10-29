from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import Comment, Like, Post, User
from app.schemas.interaction import (
    CommentCreate, CommentPage, CommentResponse, LikeCount, LikeResponse,
)
from app.utils.pagination import PaginationParams

router = APIRouter()


async def require_post(post_id: int, db: AsyncSession) -> None:
    if await db.scalar(select(Post.id).where(Post.id == post_id)) is None:
        raise HTTPException(status_code=404, detail="Post not found")


async def count_likes(post_id: int, db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(Like).where(Like.post_id == post_id)) or 0


async def like_state(post_id: int, user_id: int, db: AsyncSession) -> LikeResponse:
    return LikeResponse(
        count=await count_likes(post_id, db),
        liked=await db.get(Like, (post_id, user_id)) is not None,
    )


@router.get(
    "/{post_id}/likes", response_model=LikeCount, summary="Get a post's like count",
    description="Public endpoint that returns the total number of likes.",
)
async def get_likes(post_id: int, db: AsyncSession = Depends(get_db)):
    await require_post(post_id, db)
    return LikeCount(count=await count_likes(post_id, db))


@router.get(
    "/{post_id}/like", response_model=LikeResponse, summary="Get my like status",
    description="Returns the current like count and whether the signed-in user has liked this post.",
)
async def get_my_like(
    post_id: int, response: Response, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    await require_post(post_id, db)
    return await like_state(post_id, current_user.id, db)


@router.put(
    "/{post_id}/like", response_model=LikeResponse, summary="Like a post",
    description="Adds a like for the signed-in user. Repeating the request does not create duplicate likes.",
)
async def like_post(
    post_id: int, response: Response, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    await require_post(post_id, db)
    user_id = current_user.id
    try:
        async with db.begin_nested():
            db.add(Like(post_id=post_id, user_id=user_id))
            await db.flush()
    except IntegrityError:
        # Only tolerate an existing like; do not mask other constraint failures.
        if await db.get(Like, (post_id, user_id)) is None:
            raise
    await db.commit()
    return await like_state(post_id, user_id, db)


@router.delete(
    "/{post_id}/like", response_model=LikeResponse, summary="Remove my like",
    description="Removes the signed-in user's like, if present, and returns the updated count.",
)
async def unlike_post(
    post_id: int, response: Response, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    await require_post(post_id, db)
    await db.execute(delete(Like).where(Like.post_id == post_id, Like.user_id == current_user.id))
    await db.commit()
    return await like_state(post_id, current_user.id, db)


@router.get(
    "/{post_id}/comments", response_model=CommentPage, summary="List post comments",
    description="Public, newest-first, paginated comments with author and total count.",
)
async def get_comments(
    post_id: int, pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    await require_post(post_id, db)
    total = await db.scalar(select(func.count()).select_from(Comment).where(Comment.post_id == post_id)) or 0
    items = (await db.scalars(
        select(Comment).where(Comment.post_id == post_id).order_by(Comment.id.desc())
        .offset((pagination.page - 1) * pagination.per_page).limit(pagination.per_page)
    )).all()
    return CommentPage(items=items, page=pagination.page, per_page=pagination.per_page, total=total)


@router.post(
    "/{post_id}/comments", response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED, summary="Add a comment",
    description="Adds a comment as the signed-in user. Content must be between 1 and 2,000 characters.",
)
async def create_comment(
    post_id: int, comment_in: CommentCreate, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_post(post_id, db)
    comment = Comment(post_id=post_id, user_id=current_user.id, content=comment_in.content)
    db.add(comment)
    await db.commit()
    return await db.scalar(select(Comment).where(Comment.id == comment.id))


@router.delete(
    "/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a comment", description="Only the comment's author can delete it.",
)
async def delete_comment(
    post_id: int, comment_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_post(post_id, db)
    comment = await db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")
    await db.delete(comment)
    await db.commit()
