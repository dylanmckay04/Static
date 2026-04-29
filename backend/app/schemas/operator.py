from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class OperatorCreate(BaseModel):
    email: EmailStr
    password: str


class OperatorResponse(BaseModel):
    """Returned to the Operator about themselves (e.g. after registration)."""

    id: int
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
