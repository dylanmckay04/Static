from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChannelCreate(BaseModel):
    name:                     str      = Field(..., min_length=1, max_length=100)
    description:              str | None = Field(None, max_length=300)
    is_encrypted:             bool     = False
    transmission_ttl_seconds: int | None = Field(None, ge=60, description="Soft-delete transmissions older than this many seconds. Null = never.")


class ChannelResponse(BaseModel):
    id:                       int
    name:                     str
    description:              str | None
    is_encrypted:             bool
    transmission_ttl_seconds: int | None
    created_at:               datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelDetail(ChannelResponse):
    contact_count: int


class CipherKeyResponse(BaseModel):
    """Returned once when a cipher key is minted. The token is shown once only."""
    cipher_key_id: int
    token:         str
    expires_at:    datetime
