from datetime import datetime

from pydantic import AliasPath, BaseModel, ConfigDict, Field


class LikeCount(BaseModel):
    count: int


class LikeResponse(LikeCount):
    liked: bool


class CommentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    user_id: int
    content: str
    date_posted: datetime
    author: str = Field(validation_alias=AliasPath("author", "username"))


class CommentPage(BaseModel):
    items: list[CommentResponse]
    page: int
    per_page: int
    total: int
