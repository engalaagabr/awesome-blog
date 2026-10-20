from fastapi import APIRouter, HTTPException, status
from app.schemas.post import PostCreate, PostResponse
import random
from datetime import date, timedelta

router = APIRouter()

# سننقل قائمة الـ posts المؤقتة هنا مؤقتاً أو نجعلها مشتركة لاحقاً
posts: list[dict] = [
    {
        "id": 1,
        "author": "Corey Schafer",
        "title": "FastAPI is Awesome",
        "content": "This framework is really easy to use and super fast.",
        "date_posted": "April 20, 2025",
    },
    {
        "id": 2,
        "author": "Jane Doe",
        "title": "Python is Great for Web Development",
        "content": "Python is a great language for web development, and FastAPI makes it even better.",
        "date_posted": "April 21, 2025",
    },
]

@router.get("/", response_model=list[PostResponse])
def get_posts():
    return posts

@router.post("/", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def create_post(post: PostCreate):
    new_id = max(p["id"] for p in posts) + 1 if posts else 1

    random_date = date(2022, 1, 1) + timedelta(days=random.randint(0, (date(2026, 12, 31) - date(2022, 1, 1)).days))
    formatted_date = random_date.strftime("%B %d, %Y")

    new_post = {
        "id": new_id,
        "author": post.author,
        "title": post.title,
        "content": post.content,
        "date_posted": formatted_date,
    }
    posts.append(new_post)
    return new_post

@router.get("/{post_id}", response_model=PostResponse)
def get_post(post_id: int):
    for post in posts:
        if post.get("id") == post_id:
            return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")