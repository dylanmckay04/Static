from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.presence import PresenceRole


class PresenceResponse(BaseModel):
    """A Presence as visible to other participants in the Seance."""
    sigil:      str
    role:       PresenceRole
    entered_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OwnPresenceResponse(PresenceResponse):
    """Returned to the Seeker themselves when they enter a Seance."""
    seance_id: int
