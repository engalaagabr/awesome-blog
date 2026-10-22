from pydantic import BaseModel, Field, ConfigDict
import datetime

class PostBase(BaseModel):
    title : str = Field(..., min_length=1, max_length=100)
    author : str = Field(..., min_length=1, max_length=100)
    content : str = Field(..., min_length=1)

class PostCreate(PostBase):
    user_id : int


# inherit from PostBase and add id and date_posted fields
class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id : int
    date_posted : datetime
    user_id : int

