"""The web app: paste a job description from a phone, get the resume PDF back.

One password (hashed, in the environment), a signed session cookie, runs
worked in the background (jobs.py), and no JavaScript: a run's page refreshes
itself until the PDF is ready.
"""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from resume_maxer.auth import LoginLimiter, verify_password
from resume_maxer.claude import find_claude
from resume_maxer.compile import find_tectonic
from resume_maxer.jobs import MAX_POSTING_CHARS, PostingError, RunStore
from resume_maxer.judge import JUDGES
from resume_maxer.load import MASTER_FILENAME, data_dir, load_master
from resume_maxer.pipeline import Tailored, tailor
from resume_maxer.writer import BACKENDS

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates" / "web"
STATIC = HERE / "static"

PASSWORD_HASH_ENV = "RESUME_WEB_PASSWORD_HASH"
SECRET_ENV = "RESUME_WEB_SECRET"
RUNS_DIR_ENV = "RESUME_RUNS_DIR"
INSECURE_COOKIES_ENV = "RESUME_WEB_INSECURE_COOKIES"  # "1" only for local http testing
BACKEND_ENV = "RESUME_BACKEND"
DEFAULT_RUNS_DIR = Path("out/web")

# A posting form is a few KB; refuse anything far larger before parsing it.
MAX_BODY_BYTES = MAX_POSTING_CHARS * 4 + 4096
SESSION_DAYS = 14

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class ConfigError(RuntimeError):
    """The web app is missing a setting it cannot run without."""


@dataclass(frozen=True)
class WebConfig:
    password_hash: str
    session_secret: str
    runs_dir: Path = DEFAULT_RUNS_DIR
    secure_cookies: bool = True

    @classmethod
    def from_env(cls) -> "WebConfig":
        missing = [name for name in (PASSWORD_HASH_ENV, SECRET_ENV) if not os.environ.get(name)]
        if missing:
            raise ConfigError(
                f"set {' and '.join(missing)} before serving; "
                "`resume-maxer hash-password` prints both lines to paste into your env file"
            )
        if len(os.environ[SECRET_ENV]) < 32:
            raise ConfigError(f"{SECRET_ENV} must be at least 32 characters of random text")
        return cls(
            password_hash=os.environ[PASSWORD_HASH_ENV],
            session_secret=os.environ[SECRET_ENV],
            runs_dir=Path(os.environ.get(RUNS_DIR_ENV) or DEFAULT_RUNS_DIR),
            secure_cookies=os.environ.get(INSECURE_COOKIES_ENV) != "1",
        )


def tailor_with(backend: str) -> Callable[[str], Tailored]:
    """What a web run does: read the master fresh (edits apply), check tools, tailor."""

    def run(posting: str) -> Tailored:
        master_path = data_dir() / MASTER_FILENAME
        master = load_master(master_path)
        find_tectonic()
        if backend == "claude-code":
            find_claude()
        return tailor(
            master,
            master_path.read_text(encoding="utf-8"),
            posting,
            write=BACKENDS[backend],
            judge=JUDGES[backend],
        )

    return run


def create_app(
    config: WebConfig,
    tailor_fn: Callable[[str], Tailored],
    limiter: LoginLimiter | None = None,
) -> FastAPI:
    store = RunStore(config.runs_dir, tailor_fn)
    limiter = limiter or LoginLimiter()
    templates = Jinja2Templates(directory=TEMPLATES)  # autoescapes .html

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        store.close()

    # No /docs, /redoc or /openapi.json: nothing about the app is public.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return Response("Request too large.", status_code=413)
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"  # pages hold personal data
        return response

    # Added after the guard, so it runs first and the session exists inside it.
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie="resume_maxer",
        max_age=SESSION_DAYS * 24 * 3600,
        same_site="strict",  # also stops other sites from posting forms here
        https_only=config.secure_cookies,
    )

    def signed_in(request: Request) -> bool:
        return request.session.get("auth") is True

    def page(request: Request, name: str, status_code: int = 200, **context) -> Response:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def to_login() -> Response:
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/login")
    def login_form(request: Request) -> Response:
        if signed_in(request):
            return RedirectResponse("/", status_code=303)
        return page(request, "login.html", error=None)

    @app.post("/login")
    def login(request: Request, password: str = Form("")) -> Response:
        client = request.client.host if request.client else "unknown"
        if limiter.blocked(client):
            return page(
                request, "login.html", 429, error="Too many attempts. Try again in 15 minutes."
            )
        if not verify_password(password, config.password_hash):
            limiter.record_failure(client)
            return page(request, "login.html", 401, error="Wrong password.")
        limiter.reset(client)
        request.session.clear()  # a fresh session on every sign-in
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return to_login()

    @app.get("/")
    def index(request: Request) -> Response:
        if not signed_in(request):
            return to_login()
        return page(request, "index.html", runs=store.list(), error=None, posting="", label="")

    @app.post("/runs")
    def create_run(request: Request, posting: str = Form(""), label: str = Form("")) -> Response:
        if not signed_in(request):
            return to_login()
        try:
            run = store.create(posting, label)
        except PostingError as exc:
            return page(
                request, "index.html", 400, runs=store.list(), error=f"{str(exc).capitalize()}.",
                posting=posting[:MAX_POSTING_CHARS], label=label,
            )  # fmt: skip
        return RedirectResponse(f"/runs/{run.id}", status_code=303)

    @app.get("/runs/{run_id}")
    def show_run(request: Request, run_id: str) -> Response:
        if not signed_in(request):
            return to_login()
        run = store.get(run_id)
        if run is None:
            return page(request, "missing.html", 404)
        return page(request, "run.html", run=run)

    @app.get("/runs/{run_id}/resume.pdf")
    def download(request: Request, run_id: str) -> Response:
        if not signed_in(request):
            return to_login()
        run, path = store.get(run_id), store.pdf_path(run_id)
        if run is None or path is None:
            return page(request, "missing.html", 404)
        return FileResponse(path, media_type="application/pdf", filename=f"{run.label}.pdf")

    return app
