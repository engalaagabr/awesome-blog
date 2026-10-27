from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette import status
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.auth import COOKIE_NAME, check_origin, get_current_user, revoke_session, start_session
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.session import LoginSession
from app.schemas.post import PostResponse
from app.schemas.user import UserCreate, UserResponse, UserLogin, UserUpdate

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(check_origin)])
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
    


@router.post("/login", status_code=status.HTTP_200_OK, dependencies=[Depends(check_origin)])
async def login_user(user_login_schema: UserLogin, request: Request, response: Response,
                     db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == user_login_schema.username))

    if not user or not await run_in_threadpool(
        verify_password, user_login_schema.password, user.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await start_session(request, response, user, db)
    return {
        "message": "Login successful",
        "id": user.id,
        "username": user.username,
        "email": user.email
    }


@router.get("/me", response_model=UserResponse)
async def current_profile(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(check_origin)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await revoke_session(request, db)
    await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax",
                           secure=request.url.scheme == "https")

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
async def update_user(user_id: int, user_update: UserUpdate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user.id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not authorized to update this user")

    if user_update.username is not None:
        user.username = user_update.username
    if user_update.email is not None:
        user.email = user_update.email
    if "image_file" in user_update.model_fields_set:
        user.image_file = user_update.image_file
    if user_update.password is not None:
        hashed_pwd = await run_in_threadpool(hash_password, user_update.password)
        user.password = hashed_pwd

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists.")
    await db.refresh(user)

    return user

@router.delete("/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user.id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this user")

    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    # The User.posts relationship cascades deletion to this user's posts.
    await db.delete(user)
    await db.commit()
