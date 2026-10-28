from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.auth import COOKIE_NAME, check_origin, get_current_user, revoke_request_tokens, start_login
from app.core.settings import settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.post import PostResponse
from app.schemas.user import UserCreate, UserResponse, UserLogin, UserUpdate
from app.utils.profile_images import MAX_IMAGE_BYTES, remove_profile_image, save_profile_image
from app.utils.pagination import PaginationParams, paginate_posts

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

    token = await start_login(request, response, user, db)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        "message": "Login successful",
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "image_file": user.image_file,
        "image_path": user.image_path,
    }


@router.get("/me", response_model=UserResponse)
async def current_profile(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user


async def replace_profile_image(user: User, filename: str | None, db: AsyncSession):
    previous_image = user.image_file
    user.image_file = filename
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(remove_profile_image, filename)
        raise
    await run_in_threadpool(remove_profile_image, previous_image)
    return user


@router.put("/me/image", response_model=UserResponse)
async def upload_profile_image(
    response: Response,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        if image.size is not None and image.size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Profile pictures must be 5 MB or smaller.")
        data = await image.read(MAX_IMAGE_BYTES + 1)
    finally:
        await image.close()
    filename = await run_in_threadpool(save_profile_image, data)
    response.headers["Cache-Control"] = "no-store"
    return await replace_profile_image(user, filename, db)


@router.delete("/me/image", response_model=UserResponse)
async def reset_profile_image(
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return await replace_profile_image(user, None, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(check_origin)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await revoke_request_tokens(request, db)
    await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax",
                           secure=request.url.scheme == "https")

# get user posts
@router.get("/{user_id}/posts", response_model=list[PostResponse])
async def get_user_posts(
    user_id: int,
    response: Response,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    result = await paginate_posts(db, pagination, user_id=user_id)
    response.headers.update(result.headers)
    return result.items

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

    previous_image = user.image_file
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
    if "image_file" in user_update.model_fields_set:
        await run_in_threadpool(remove_profile_image, previous_image)

    return user

@router.delete("/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user.id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this user")

    await revoke_request_tokens(request, db)
    previous_image = user.image_file
    # The User.posts relationship cascades deletion to this user's posts.
    await db.delete(user)
    await db.commit()
    await run_in_threadpool(remove_profile_image, previous_image)
