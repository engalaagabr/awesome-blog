from fastapi import APIRouter, Depends, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status
from app.models.user import User
from app.schemas.post import PostResponse
from app.schemas.user import UserCreate, UserResponse, UserLogin
from app.core.database import get_db
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user_schema: UserCreate, db: Session = Depends(get_db)):
    # Check if the username or email already exists in the database
    existing_user = db.query(User).filter(
        (User.username == user_schema.username) | (User.email == user_schema.email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists.",
        )

    hashed_pwd = hash_password(user_schema.password)

    # Create a new user instance
    new_user = User(
        username=user_schema.username,
        email=user_schema.email,
        password=hashed_pwd,  
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user
    


@router.post("/login", status_code=status.HTTP_200_OK)
def login_user(user_login_schema: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_login_schema.username).first()

    if not user or not verify_password(user_login_schema.password, user.password):
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
def get_user_posts(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user.posts

@router.get("/profile")
def get_user_profile():
    pass

@router.put("/profile")
def update_user_profile():
    pass

@router.delete("/profile")
def delete_user_profile():
    pass

