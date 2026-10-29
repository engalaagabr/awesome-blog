from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.post import Post
from app.models import Comment, Like
from app.models.user import User
from app.schemas.post import PostCreate, PostDetailResponse, PostResponse, PostUpdate
from app.utils.pagination import PaginationParams, paginate_posts

router = APIRouter()

@router.get(
    "/", response_model=list[PostResponse], summary="List posts",
    description="Returns posts newest-first. Use `page` and `per_page` to paginate; totals are returned in response headers.",
)
async def get_posts(
    response: Response,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await paginate_posts(db, pagination)
    response.headers.update(result.headers)
    return result.items

@router.post(
    "/", response_model=PostResponse, status_code=status.HTTP_201_CREATED,
    summary="Create a post", description="Creates a post owned by the signed-in user.",
)
async def create_post(
    post_in: PostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_post = Post(
        title=post_in.title,
        content=post_in.content,
        user_id=current_user.id

    )

    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)

    return new_post


@router.get(
    "/{post_id}", response_model=PostDetailResponse, summary="Get a post",
    description="Returns the post, author, like count, and comment count.",
)
async def get_post(post_id: int, db: AsyncSession = Depends(get_db)):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    likes_count = await db.scalar(
        select(func.count()).select_from(Like).where(Like.post_id == post_id)
    ) or 0
    comments_count = await db.scalar(
        select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
    ) or 0
    return PostDetailResponse(
        **PostResponse.model_validate(post).model_dump(),
        likes_count=likes_count,
        comments_count=comments_count,
    )

@router.patch(
    "/{post_id}", response_model=PostResponse, summary="Update a post",
    description="Updates a post. Only its author can make changes.",
)
async def update_post(
    post_id: int, 
    post_update: PostUpdate,  
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await db.get(Post, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this post",
        )
    
    if post_update.title is not None:
        post.title = post_update.title
    if post_update.content is not None:
        post.content = post_update.content

    await db.commit()
    await db.refresh(post)
    
    return post

@router.delete(
    "/{post_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a post",
    description="Deletes a post and its likes and comments. Only its author can delete it.",
)
async def delete_post(
    post_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await db.get(Post, post_id)
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this post",
        )
    
    await db.delete(post)
    
    await db.commit()
    
    return None
