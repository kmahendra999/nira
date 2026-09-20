"""Device enrolment and self-inspection endpoints.

`nira device pair` mints an invitation and shows it as a QR. This is where the
phone redeems it: without these routes the QR pointed nowhere and pairing could
only be completed by running Python on the desktop, which rather defeats the
purpose of putting a code on the screen.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

devices_router = APIRouter(prefix="/v1/devices", tags=["devices"])

# A platform label is free-form and only ever displayed, but it lands in a
# database and a UI, so cap it rather than storing whatever arrives.
_MAX_PLATFORM_LEN = 32


def _store(request: Request) -> Any:
    store = getattr(request.app.state, "device_store", None)
    if store is None:
        raise HTTPException(
            status_code=501,
            detail="Device registry unavailable. Start the server with an API key.",
        )
    return store


@devices_router.post("/enroll")
async def enroll_device(request: Request) -> dict:
    """Exchange a pairing token for this device's own key.

    Deliberately exempt from bearer auth: a device that has not paired yet has
    no key to present, and the enrolment token *is* the credential. It is
    single-use and expires in ten minutes, which is what keeps this from being
    an open door.

    The key is returned exactly once. Only its hash is stored, so a device that
    loses it re-pairs rather than reading it back out of the server.
    """
    store = _store(request)
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Expected a JSON body") from exc

    token = str((body or {}).get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing enrolment token")
    platform = str((body or {}).get("platform") or "unknown")[:_MAX_PLATFORM_LEN]

    try:
        device, key = store.redeem_enrollment(token, platform=platform)
    except ValueError as exc:
        # Unknown, already used, expired. One message for all three on purpose:
        # distinguishing them tells an attacker which tokens ever existed.
        logger.info("Rejected enrolment attempt: %s", exc)
        raise HTTPException(
            status_code=403, detail="Invalid or expired enrolment token"
        ) from exc

    return {
        "device_id": device.id,
        "name": device.name,
        "scopes": device.scopes,
        "key": key,
    }


@devices_router.get("/me")
async def current_device(request: Request) -> dict:
    """Report the device this request authenticated as.

    Lets a client confirm it is still paired, and see what it is allowed to do,
    without having to attempt a scoped action and interpret the failure.
    """
    device = request.scope.get("nira_device")
    if device is None:
        # The machine key authenticates but is not a device.
        return {"device": None, "scopes": ["admin"]}
    return {"device": device.to_dict(), "scopes": device.scopes}


__all__ = ["devices_router"]
