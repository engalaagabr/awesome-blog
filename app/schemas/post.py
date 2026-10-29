from pydantic import AliasPath, BaseModel, Field, ConfigDict
from datetime import datetime

class PostBase(BaseModel):
    title : str = Field(..., min_length=1, max_length=100)
    content : str = Field(..., min_length=1, max_length=50_000)

class PostCreate(PostBase):
    pass


# inherit from PostBase and add id and date_posted fields
class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    author : str = Field(validation_alias=AliasPath("author", "username"))
    id : int
    date_posted : datetime
    user_id : int


class PostDetailResponse(PostResponse):
    # The base response reads author.username from the ORM object; detail
    # responses are built from the already serialized username string.
    author: str
    likes_count: int
    comments_count: int

class PostUpdate(PostBase):
    title : str | None = Field(None, min_length=1, max_length=100)
    content : str | None = Field(None, min_length=1, max_length=50_000)
