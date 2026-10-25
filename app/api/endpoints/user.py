from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette import status
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.post import PostResponse
from app.schemas.user import UserCreate, UserResponse, UserLogin, UserUpdate

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_schema: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if the username or email already exists in the database
    existing_user = await db.scalar(
        select(User).where(
            (User.username == user_schema.username) | (User.email == user_schema.email)
        ).limit(1)
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists.",
        )

    hashed_pwd = await run_in_threadpool(hash_password, user_schema.password)

    # Create a new user instance
    new_user = User(
        username=user_schema.username,
        email=user_schema.email,
        image_file=user_schema.image_file,
        password=hashed_pwd,  
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user
    


@router.post("/login", status_code=status.HTTP_200_OK)
async def login_user(user_login_schema: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == user_login_schema.username))

    if not user or not await run_in_threadpool(
        verify_password, user_login_schema.password, user.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "message": "Login successful",
        "username": user.username,
        "email": user.email
    }

# get user posts
@router.get("/{user_id}/posts", response_model=list[PostResponse])
async def get_user_posts(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id, options=[selectinload(User.posts)])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user.posts

@router.get("/{user_id}/profile", response_model=UserResponse)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user

@router.patch("/{user_id}/update", response_model=UserResponse)
async def update_user(user_id: int, user_update: UserUpdate, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    if user_update.username is not None:
        user.username = user_update.username
    if user_update.email is not None:
        user.email = user_update.email
    if "image_file" in user_update.model_fields_set:
        user.image_file = user_update.image_file
    if user_update.password is not None:
        hashed_pwd = await run_in_threadpool(hash_password, user_update.password)
        user.password = hashed_pwd

    await db.commit()
    await db.refresh(user)

    return user

@router.delete("/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # The User.posts relationship cascades deletion to this user's posts.
    await db.delete(user)
    await db.commit()
