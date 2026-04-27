from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.whisper import Whisper

_REDACTED = "⸻ withdrawn ⸻"


class WhisperCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class WhisperResponse(BaseModel):
    """A whisper as it should be displayed in the séance.

    When deleted_at is set, content is replaced with a sentinel string and
    is_deleted is True so the client can style it differently.
    """
    id:         int
    seance_id:  int
    sigil:      str
    created_at: datetime
    is_deleted: bool = False

    # content is exposed as a computed field so we can redact it cleanly.
    content: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_redacted(cls, w: "Whisper") -> "WhisperResponse":
        """Build a response, replacing content if the whisper is soft-deleted."""
        is_del = w.deleted_at is not None
        return cls(
            id=w.id,
            seance_id=w.seance_id,
            sigil=w.sigil,
            content=_REDACTED if is_del else w.content,
            created_at=w.created_at,
            is_deleted=is_del,
        )


class WhisperPage(BaseModel):
    items:          list[WhisperResponse]
    next_before_id: int | None = None
