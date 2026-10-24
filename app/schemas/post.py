from pydantic import AliasPath, BaseModel, Field, ConfigDict
from datetime import datetime

class PostBase(BaseModel):
    title : str = Field(..., min_length=1, max_length=100)
    content : str = Field(..., min_length=1)

class PostCreate(PostBase):
    user_id : int


# inherit from PostBase and add id and date_posted fields
class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    author : str = Field(validation_alias=AliasPath("author", "username"))
    id : int
    date_posted : datetime
    user_id : int

