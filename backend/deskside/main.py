"""Application entry point: ``deskside`` starts the web server and the collectors."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from .api import router
from .api_people import router as people_router
from .api_remote import router as remote_router
from .api_netbox import router as netbox_router
from .api_map import router as map_router
from . import naming, remote
from .auth import Sessions, ensure_admin
from .oidc import Oidc
from .db import Database
from .engine import Engine

log = logging.getLogger("deskside")
STATIC = Path(os.environ.get("DESKSIDE_STATIC", Path(__file__).parent / "static"))


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_url)
        db.create_schema()
        msg = ensure_admin(db, settings.admin_password, settings.local_login)
        if msg:
            log.warning(msg)
        app.state.db = db
        app.state.settings = settings
        app.state.naming = naming.load(settings.naming)
        app.state.remote_tools = remote.load(settings.raw.get("remote_tools"))
        app.state.sessions = Sessions(settings.secret_key)
        app.state.oidc = Oidc(settings.oidc, settings.secret_key, settings.public_url) if settings.oidc else None
        app.state.engine = Engine(settings, db)
        app.state.engine.start()
        log.info("deskside %s started with %d source(s)", __version__, len(app.state.engine.sources))
        yield
        await app.state.engine.stop()

    app = FastAPI(title="deskside", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.include_router(router)
    app.include_router(people_router)
    app.include_router(remote_router)
    app.include_router(netbox_router)
    app.include_router(map_router)

    if (STATIC / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (STATIC / path).resolve()
            if path and candidate.is_file() and STATIC.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(STATIC / "index.html")
    return app


OUI_URL = "https://standards-oui.ieee.org/oui/oui.csv"


def update_oui(target: str) -> None:
    """Download the IEEE vendor prefix registry. deskside never does this on its own."""
    import httpx

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {OUI_URL} ...")
    # IEEE answers 418 to clients that do not say who they are.
    headers = {"User-Agent": f"deskside/{__version__} (+https://github.com/4nonX/deskside)"}
    with httpx.stream("GET", OUI_URL, headers=headers, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    tmp.replace(path)
    print(f"saved to {path}; set oui_file: {path} in the configuration and restart")


USAGE = """usage: deskside                       start the server (configuration from DESKSIDE_CONFIG / config.yaml)
       deskside update-oui [PATH]     download the IEEE vendor list (default data/oui.csv)"""


def run() -> None:
    import uvicorn

    args = sys.argv[1:]
    if args and args[0] == "update-oui":
        update_oui(args[1] if len(args) > 1 else "data/oui.csv")
        return
    if args:  # anything else (--help, typos) prints usage instead of starting a second server
        print(USAGE, file=sys.stdout if args[0] in ("-h", "--help", "help") else sys.stderr)
        sys.exit(0 if args[0] in ("-h", "--help", "help") else 2)
    logging.basicConfig(level=os.environ.get("DESKSIDE_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        app = create_app()
    except config.ConfigError as exc:  # show configuration problems plainly, without a traceback
        print(f"deskside: configuration problem: {exc}", file=sys.stderr)
        sys.exit(2)
    uvicorn.run(app, host=os.environ.get("DESKSIDE_HOST", "0.0.0.0"), port=int(os.environ.get("DESKSIDE_PORT", "8080")),
                proxy_headers=True, forwarded_allow_ips=os.environ.get("DESKSIDE_TRUSTED_PROXIES", "127.0.0.1"))


if __name__ == "__main__":
    run()
