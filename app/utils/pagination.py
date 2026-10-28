from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post


@dataclass
class PaginationParams:
    page: int = Query(1, ge=1, le=2_147_483_647)
    per_page: int = Query(10, ge=1, le=100)


@dataclass
class PostPage:
    items: list[Post]
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return (self.total + self.per_page - 1) // self.per_page

    @property
    def page_numbers(self) -> list[int]:
        return sorted({1, self.pages} | set(
            range(max(1, self.page - 2), min(self.pages, self.page + 2) + 1)
        )) if self.pages else []

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Total-Count": str(self.total),
            "X-Total-Pages": str(self.pages),
            "X-Page": str(self.page),
            "X-Per-Page": str(self.per_page),
        }


async def paginate_posts(
    db: AsyncSession, params: PaginationParams, user_id: int | None = None
) -> PostPage:
    query = select(Post)
    count_query = select(func.count()).select_from(Post)
    if user_id is not None:
        query = query.where(Post.user_id == user_id)
        count_query = count_query.where(Post.user_id == user_id)
    total = await db.scalar(count_query)
    # The ID breaks timestamp ties so posts do not repeat between pages.
    query = query.order_by(Post.date_posted.desc(), Post.id.desc()).offset(
        (params.page - 1) * params.per_page
    ).limit(params.per_page)
    posts = list((await db.scalars(query)).all())
    return PostPage(posts, params.page, params.per_page, total or 0)
