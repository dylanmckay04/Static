from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SeanceCreate(BaseModel):
    name:                str      = Field(..., min_length=1, max_length=100)
    description:         str | None = Field(None, max_length=300)
    is_sealed:           bool     = False
    whisper_ttl_seconds: int | None = Field(None, ge=60, description="Soft-delete whispers older than this many seconds. Null = never.")


class SeanceResponse(BaseModel):
    id:                  int
    name:                str
    description:         str | None
    is_sealed:           bool
    whisper_ttl_seconds: int | None
    created_at:          datetime

    model_config = ConfigDict(from_attributes=True)


class SeanceDetail(SeanceResponse):
    presence_count: int


class InviteResponse(BaseModel):
    """Returned once when an invite is minted. The token is shown once only."""
    invite_id: int
    token:     str
    expires_at: datetime
