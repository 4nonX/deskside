"""API for the NetBox proposal queue."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from .api import _audit, _db, _engine
from .auth import current_user, require
from .db import Device, Proposal, User, now
from .netbox import NetboxError

router = APIRouter(prefix="/api")


def _netbox(request: Request):
    nb = _engine(request).netbox
    if nb is None:
        raise HTTPException(400, "NetBox is not configured.")
    return nb


@router.get("/proposals")
def list_proposals(request: Request, status: str = "open", user: User = Depends(current_user)) -> dict[str, Any]:
    nb = _engine(request).netbox
    with _db(request).session() as s:
        stmt = select(Proposal).order_by(Proposal.updated_at.desc())
        if status != "all":
            wanted = ("open", "failed") if status == "open" else (status,)
            stmt = stmt.where(Proposal.status.in_(wanted))
        names = dict(s.execute(select(Device.id, Device.name)).all())
        rows = [{"id": p.id, "kind": p.kind, "summary": p.summary, "display": (p.payload or {}).get("display", {}),
                 "status": p.status, "error": p.error,
                 "device_id": p.device_id, "device": names.get(p.device_id), "mac": p.mac,
                 "created_at": p.created_at, "updated_at": p.updated_at, "decided_by": p.decided_by}
                for p in s.scalars(stmt.limit(500))]
    return {"configured": nb is not None, "read_only": bool(nb and nb.read_only), "rows": rows}


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(proposal_id: int, request: Request, user: User = Depends(require("admin"))) -> dict[str, Any]:
    nb = _netbox(request)
    with _db(request).session() as s:
        p = s.get(Proposal, proposal_id)
        if p is None:
            raise HTTPException(404, "No such proposal.")
        if p.status not in ("open", "failed"):
            raise HTTPException(409, f"This proposal is {p.status}.")
        s.expunge(p)
    try:
        await nb.apply(p)
        status, error = "applied", ""
    except NetboxError as exc:
        status, error = "failed", str(exc)
    with _db(request).session() as s:
        q = s.get(Proposal, proposal_id)
        q.status, q.error, q.decided_by, q.updated_at = status, error, user.username, now()
        _audit(s, user, f"netbox.{status}", q.summary, kind=q.kind, error=error)
    _engine(request).publish({"type": "refresh"})
    if status == "failed":
        raise HTTPException(502, error)
    # Re-read NetBox in the background so the queue reflects the change right away.
    task = getattr(request.app.state, "netbox_resync", None)
    if task is None or task.done():
        request.app.state.netbox_resync = asyncio.create_task(nb.sync())
    return {"ok": True}


@router.post("/proposals/{proposal_id}/dismiss")
def dismiss_proposal(proposal_id: int, request: Request, user: User = Depends(require("admin"))) -> dict[str, bool]:
    with _db(request).session() as s:
        p = s.get(Proposal, proposal_id)
        if p is None:
            raise HTTPException(404, "No such proposal.")
        p.status, p.decided_by, p.updated_at = "dismissed", user.username, now()
        _audit(s, user, "netbox.dismiss", p.summary, kind=p.kind)
    _engine(request).publish({"type": "refresh"})
    return {"ok": True}


@router.post("/netbox/sync")
async def netbox_sync(request: Request, user: User = Depends(require("admin"))) -> dict[str, Any]:
    nb = _netbox(request)
    ok = await nb.sync()
    _engine(request).publish({"type": "refresh"})
    return {"ok": ok, "error": nb.state.error, "counts": nb.state.counts}
