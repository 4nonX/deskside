"""Notifications: send events to chat webhooks, other HTTP endpoints or e-mail.

Events are collected for ``batch_seconds`` (default 60) and sent as one
message per channel, so a switch reboot produces one message, not fifty.
Each channel filters by event kind and, optionally, by whether the device is
known to deskside. A channel that fails keeps its error on the status page and
tries again with the next batch; nothing is retried forever.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import httpx

log = logging.getLogger("deskside.notify")

KINDS = ("new", "online", "offline", "moved", "ip_changed", "scheme", "busy_port", "discovery")
MAX_LINES = 40


class NotifyError(Exception):
    pass


@dataclass
class ChannelState:
    name: str
    type: str
    interval: int = 0
    last_run: float | None = None
    last_ok: float | None = None
    duration: float | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


class Channel:
    def __init__(self, conf: dict[str, Any], index: int) -> None:
        self.conf = conf
        self.type = conf.get("type", "")
        self.name = conf.get("name") or f"{self.type}-{index + 1}"
        kinds = conf.get("events") or ["new", "moved", "offline", "scheme", "busy_port"]
        unknown = set(kinds) - set(KINDS) - {"all"}
        if unknown:
            raise NotifyError(f"notifications.{self.name}: unknown event kind(s) {', '.join(sorted(unknown))}; "
                              f"known: {', '.join(KINDS)}")
        self.kinds = set(KINDS) if "all" in kinds else set(kinds)
        self.only_known = bool(conf.get("only_known", False))
        self.state = ChannelState(name=f"notify: {self.name}", type=f"notify-{self.type}")
        if self.type == "webhook":
            if not conf.get("url"):
                raise NotifyError(f"notifications.{self.name}: url is required")
            if conf.get("format", "text") not in ("text", "json"):
                raise NotifyError(f"notifications.{self.name}: format must be text or json")
        elif self.type == "email":
            for k in ("host", "from", "to"):
                if not conf.get(k):
                    raise NotifyError(f"notifications.{self.name}: {k} is required")
            if conf.get("security", "starttls") not in ("starttls", "ssl", "none"):
                raise NotifyError(f"notifications.{self.name}: security must be starttls, ssl or none")
        else:
            raise NotifyError(f"notifications.{self.name}: type must be webhook or email")

    def wants(self, ev: dict[str, Any]) -> bool:
        if ev["kind"] not in self.kinds:
            return False
        return not (self.only_known and ev.get("mac") and not ev.get("device_id"))


def render_text(events: list[dict[str, Any]], link: str | None) -> tuple[str, str]:
    """Subject and plain-text body for a batch of events."""
    if len(events) == 1:
        subject = events[0]["message"]
    else:
        counts: dict[str, int] = {}
        for e in events:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        subject = f"{len(events)} network events: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    lines = []
    for e in events[:MAX_LINES]:
        when = dt.datetime.fromtimestamp(e["ts"]).strftime("%H:%M")
        lines.append(f"{when}  {e['message']}")
    if len(events) > MAX_LINES:
        lines.append(f"… and {len(events) - MAX_LINES} more")
    if link:
        lines.append("")
        lines.append(link.rstrip("/") + "/")
    return subject, "\n".join(lines)


class Notifier:
    def __init__(self, confs: list[dict[str, Any]] | None, public_url: str | None = None,
                 batch_seconds: int = 60) -> None:
        self.channels = [Channel(c, i) for i, c in enumerate(confs or [])]
        self.public_url = public_url
        self.batch_seconds = batch_seconds
        self._queue: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None
        self.transport: httpx.AsyncBaseTransport | None = None   # tests plug in a fake endpoint here
        self.smtp_factory = smtplib.SMTP                          # and a fake SMTP class here
        self.smtp_ssl_factory = smtplib.SMTP_SSL

    def submit(self, events: list[dict[str, Any]]) -> None:
        if not self.channels or not events:
            return
        self._queue.extend(events)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_later(), name="notify")

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.batch_seconds)
        await self.flush()

    async def flush(self) -> None:
        batch, self._queue = self._queue, []
        await asyncio.gather(*(self._send(ch, [e for e in batch if ch.wants(e)]) for ch in self.channels))

    async def test(self) -> list[dict[str, Any]]:
        ev = {"ts": time.time(), "kind": "new", "mac": None, "device_id": None, "device": None,
              "message": "Test message from deskside: notifications work.", "data": {}}
        results = []
        for ch in self.channels:
            await self._send(ch, [ev])
            results.append({"name": ch.name, "ok": ch.state.error is None, "error": ch.state.error})
        return results

    async def _send(self, ch: Channel, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        st = ch.state
        st.last_run = time.time()
        try:
            if ch.type == "webhook":
                await self._webhook(ch, events)
            else:
                await asyncio.to_thread(self._email, ch, events)
            st.error, st.last_ok = None, time.time()
            st.counts["sent"] = st.counts.get("sent", 0) + 1
            st.counts["events"] = st.counts.get("events", 0) + len(events)
        except Exception as exc:  # a broken channel must not affect the others
            st.error = f"notify {ch.name}: {exc}"
            log.warning("%s", st.error)
        finally:
            st.duration = round(time.time() - st.last_run, 2)

    async def _webhook(self, ch: Channel, events: list[dict[str, Any]]) -> None:
        subject, body = render_text(events, self.public_url)
        if ch.conf.get("format", "text") == "text":
            payload: dict[str, Any] = {"text": body if len(events) > 1 else f"{subject}\n{self.public_url or ''}".strip()}
        else:
            payload = {"source": "deskside", "summary": subject, "events": events}
        async with httpx.AsyncClient(timeout=15, transport=self.transport, verify=ch.conf.get("verify_tls", True),
                                     headers=ch.conf.get("headers") or {}) as cl:
            r = await cl.post(ch.conf["url"], json=payload)
        if r.is_error:
            raise NotifyError(f"the endpoint answered {r.status_code}")

    def _email(self, ch: Channel, events: list[dict[str, Any]]) -> None:
        c = ch.conf
        subject, body = render_text(events, self.public_url)
        msg = EmailMessage()
        msg["Subject"] = f"{c.get('subject_prefix', '[deskside]')} {subject}"[:250]
        msg["From"] = c["from"]
        to = c["to"] if isinstance(c["to"], list) else [c["to"]]
        msg["To"] = ", ".join(to)
        msg.set_content(body)
        security = c.get("security", "starttls")
        port = int(c.get("port", 465 if security == "ssl" else 587 if security == "starttls" else 25))
        ctx = ssl.create_default_context()
        if c.get("verify_tls", True) is False:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        if security == "ssl":
            server = self.smtp_ssl_factory(c["host"], port, timeout=20, context=ctx)
        else:
            server = self.smtp_factory(c["host"], port, timeout=20)
        with server:
            if security == "starttls":
                server.starttls(context=ctx)
            if c.get("user"):
                server.login(c["user"], c.get("password", ""))
            server.send_message(msg)
