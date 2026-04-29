from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.contact import ContactRole


class ContactResponse(BaseModel):
    """A Contact as visible to other participants in the Channel."""
    callsign:   str
    role:       ContactRole
    entered_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OwnContactResponse(ContactResponse):
    """Returned to the Operator themselves when they enter a Channel."""
    channel_id: int
