from pydantic import BaseModel, Field
from typing import Optional


class User(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    auth_provider: Optional[str] = None
    session_id: Optional[str] = Field(default=None, exclude=True)
    is_admin: bool = False
