"""Kontrak /api/v1/sync, sama dengan routes/api.php Rasentra Laravel."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from odoo.api import Environment

from odoo.addons.fastapi.dependencies import odoo_env

from fastapi import APIRouter, Depends, Header, HTTPException, status

sync_router = APIRouter(tags=["sync"])


def authenticated_device(
    env: Annotated[Environment, Depends(odoo_env)],
    authorization: Annotated[str | None, Header()] = None,
):
    """Padanan middleware AuthenticateDevice: `Authorization: Bearer <token perangkat>`."""
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
    device = env["rasentra.device"].authenticate(token)
    if not device:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, {"error": "unauthenticated", "message": "Token perangkat tidak sah."}
        )
    return device


Device = Annotated[object, Depends(authenticated_device)]
Env = Annotated[Environment, Depends(odoo_env)]


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=500)


class AckItem(BaseModel):
    entity_type: str
    entity_key: str
    status: Literal["received", "applied", "failed"]
    error: str | None = Field(default=None, max_length=2000)


class AckIn(BaseModel):
    cursor: int | None = Field(default=None, ge=0)
    acks: list[AckItem]


class OutboxIn(BaseModel):
    pending: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    parked: int | None = Field(default=None, ge=0)
    oldest_at: str | None = None
    last_sent_at: str | None = None


class HeartbeatIn(BaseModel):
    sent_at: str | None = None
    app_version: str | None = Field(default=None, max_length=40)
    applied_cursor: int | None = Field(default=None, ge=0)
    outbox: OutboxIn | None = None
    open_business_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    open_shifts: int | None = Field(default=None, ge=0)
    last_error: str | None = Field(default=None, max_length=2000)


@sync_router.post("/events")
def events(body: EventsIn, env: Env, device: Device):
    return {"results": env["rasentra.sync.inbox"].receive_batch(device, body.events)}


@sync_router.get("/changes")
def changes(env: Env, device: Device, cursor: int = 0):
    return env["rasentra.sync.publication"].changes_for(device, cursor)


@sync_router.get("/snapshot")
def snapshot(env: Env, device: Device):
    if device.app != "lokal":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Snapshot hanya untuk server Rasentra Lokal.")
    return env["rasentra.sync.publication"].snapshot_for(device)


@sync_router.post("/ack")
def ack(body: AckIn, env: Env, device: Device):
    return env["rasentra.outlet.sync.state"].ack(device, body.model_dump())


@sync_router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, env: Env, device: Device):
    return env["rasentra.outlet.sync.state"].heartbeat(device, body.model_dump(exclude_unset=True))
