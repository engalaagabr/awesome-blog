from pydantic import BaseModel, Field, ConfigDict

class UserBase(BaseModel):
    username : str = Field(..., min_length=1, max_length=50)
    email : str = Field(..., min_length=1, max_length=120)
    image_file : str | None = Field(None, min_length=1, max_length=200)

class UserCreate(UserBase):
    pass


# inherit from UserBase and add id field
class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id : int
    image_path : str
    image_file : str | None

