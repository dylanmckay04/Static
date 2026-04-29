from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_operator, get_db
from app.core.limiter import limiter
from app.models.operator import Operator
from app.realtime.hub import hub
from app.schemas.transmission import TransmissionCreate, TransmissionPage, TransmissionResponse
from app.services import transmission_service

router = APIRouter(prefix="/channels", tags=["transmissions"])


@router.post("/{channel_id}/transmissions", response_model=TransmissionResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def send_transmission(
    request: Request, channel_id: int, payload: TransmissionCreate,
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    transmission = transmission_service.create_transmission(channel_id, current_operator, payload.content, db)
    response = TransmissionResponse.from_orm_redacted(transmission)
    await hub.broadcast(channel_id, {"op": "transmission", **response.model_dump(mode="json")})
    return response


@router.get("/{channel_id}/transmissions", response_model=TransmissionPage)
@limiter.limit("60/minute")
async def list_transmissions(
    request: Request, channel_id: int,
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=50),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    return transmission_service.list_transmissions(channel_id, current_operator, before_id, limit, db)


@router.delete("/{channel_id}/transmissions/{transmission_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def redact_transmission(
    request: Request, channel_id: int, transmission_id: int,
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller/relay: soft-delete a transmission. Broadcasts redact op to the channel."""
    transmission = transmission_service.redact_transmission(channel_id, transmission_id, current_operator, db)
    await hub.broadcast(channel_id, {"op": "redact", "transmission_id": transmission.id})
