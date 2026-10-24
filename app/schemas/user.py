from pydantic import BaseModel, Field, field_validator, ConfigDict
import re

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=1, max_length=120)
    image_file: str | None = Field(None, min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not re.match("^[a-zA-Z0-9_]+$", value):
            raise ValueError("Username must contain only letters, numbers, and underscores")
        return value

class UserCreate(UserBase):
    password: str = Field(..., min_length=4, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
        # التأكد من وجود رقم واحد على الأقل
        if not any(char.isdigit() for char in value):
            raise ValueError("Password must contain at least one digit")

        # التأكد من وجود حرف كبير واحد على الأقل
        if not any(char.isupper() for char in value):
            raise ValueError("Password must contain at least one uppercase letter")

        # التأكد من وجود حرف صغير واحد على الأقل
        if not any(char.islower() for char in value):
            raise ValueError("Password must contain at least one lowercase letter")

        return value

class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    image_path: str
    image_file: str | None


class UserLogin(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
