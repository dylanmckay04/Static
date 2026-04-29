from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.transmission import Transmission

_REDACTED = "⸻ redacted ⸻"


class TransmissionCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class TransmissionResponse(BaseModel):
    """A transmission as it should be displayed in the channel.

    When deleted_at is set, content is replaced with a sentinel string and
    is_deleted is True so the client can style it differently.
    """
    id:         int
    channel_id: int
    callsign:   str
    created_at: datetime
    is_deleted: bool = False
    content:    str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_redacted(cls, t: "Transmission") -> "TransmissionResponse":
        """Build a response, replacing content if the transmission is soft-deleted."""
        is_del = t.deleted_at is not None
        return cls(
            id=t.id,
            channel_id=t.channel_id,
            callsign=t.callsign,
            content=_REDACTED if is_del else t.content,
            created_at=t.created_at,
            is_deleted=is_del,
        )


class TransmissionPage(BaseModel):
    items:          list[TransmissionResponse]
    next_before_id: int | None = None
