"""FastAPI application factory for the authenticated mini-program backend."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from os import getenv
from pathlib import Path
from time import monotonic
from typing import Callable, Sequence
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..application.input_parser import ResearchIntentParser
from ..application.narration import ReportNarrator
from ..application.research_service import ResearchService
from ..application.source_connectivity import SourceConnectivityService
from ..application.source_credentials import SourceCredentialService
from ..application.web_workspace import WebWorkspaceService
from ..infrastructure.rate_limit import InMemoryRateLimiter
from ..infrastructure.store import InMemoryApplicationStore
from ..infrastructure.task_queue import InMemoryTaskQueue
from ..observability import bind_request_id, elapsed_milliseconds, log_event, new_request_id, reset_request_id
from ..tools import ToolRegistry
from .auth import (
    AccessPolicy,
    AuthenticationError,
    SessionIdentity,
    SessionTokenCodec,
    WechatIdentityProvider,
    WechatMiniProgramClient,
)
from .mini_program_routes import (
    ConversationMessagePayload,
    WechatLoginPayload,
    create_mini_program_router,
)
from .web_routes import (
    SourceEnabledPayload,
    SourceTokenPayload,
    WebChatPayload,
    WebProfessionalResearchPayload,
    WebResearchPayload,
    create_web_router,
)


@dataclass(slots=True)
class ApplicationComponents:
    """Injected dependencies make HTTP, worker, and integration tests deterministic."""

    research: ResearchService
    sessions: SessionTokenCodec
    wechat: WechatIdentityProvider | None
    limiter: InMemoryRateLimiter
    access_policy: AccessPolicy


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _environment_flag(name: str, *, default: bool) -> bool:
    value = getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of: true, false, 1, 0, yes, no, on, off")


def _web_allowed_origins(configured: Sequence[str] | None) -> tuple[str, ...]:
    raw_origins = configured
    if raw_origins is None:
        raw_origins = getenv("AGENT_WEB_ALLOWED_ORIGINS", "").split(",")

    origins: list[str] = []
    for raw_origin in raw_origins:
        origin = raw_origin.strip()
        if not origin:
            continue
        if origin == "*":
            raise ValueError("AGENT_WEB_ALLOWED_ORIGINS does not allow wildcard origins")

        try:
            parsed = urlsplit(origin)
            parsed.port
        except ValueError as error:
            raise ValueError(f"Invalid Web origin: {origin}") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or any(character.isspace() for character in origin)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.netloc.endswith(":")
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError(f"Web origin must be a complete HTTP(S) origin without a path: {origin}")
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def create_development_components(
    *,
    tool_registry_factory: Callable[[], ToolRegistry] = ToolRegistry,
    session_secret: str | None = None,
    wechat: WechatIdentityProvider | None = None,
    access_policy: AccessPolicy | None = None,
    narrator: ReportNarrator | None = None,
) -> ApplicationComponents:
    """Build local-only components; replace all in-memory pieces before production."""

    store = InMemoryApplicationStore()
    queue = InMemoryTaskQueue()
    research = ResearchService(
        store=store,
        queue=queue,
        parser=ResearchIntentParser(),
        tool_registry_factory=tool_registry_factory,
        narrator=narrator,
    )
    configured_secret = session_secret or getenv("AGENT_SESSION_SECRET", "")
    if getenv("AGENT_ENV", "development").strip().lower() == "production" and not configured_secret:
        raise ValueError("AGENT_SESSION_SECRET is required when AGENT_ENV=production")
    secret = configured_secret or "development-only-secret-change-before-production"
    return ApplicationComponents(
        research=research,
        sessions=SessionTokenCodec(secret),
        wechat=wechat if wechat is not None else WechatMiniProgramClient.from_environment(),
        limiter=InMemoryRateLimiter(),
        access_policy=access_policy or AccessPolicy.from_environment(),
    )


def create_app(
    components: ApplicationComponents | None = None,
    *,
    tool_registry_factory: Callable[[], ToolRegistry] = ToolRegistry,
    narrator: ReportNarrator | None = None,
    web_workspace: WebWorkspaceService | None = None,
    source_credentials: SourceCredentialService | None = None,
    source_connectivity: SourceConnectivityService | None = None,
    serve_web: bool | None = None,
    web_directory: Path | None = None,
    web_allowed_origins: Sequence[str] | None = None,
) -> FastAPI:
    """Create the HTTP app without exposing data-source credentials to clients."""

    app_components = components or create_development_components(
        tool_registry_factory=tool_registry_factory,
        narrator=narrator,
    )
    app = FastAPI(title="Finance Agent API", version="0.3.0")
    app.state.components = app_components
    app.state.web_workspace = web_workspace
    app.state.source_credentials = source_credentials
    app.state.source_connectivity = source_connectivity

    allowed_origins = _web_allowed_origins(web_allowed_origins)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Authorization", "Content-Type", "X-Finance-Agent-Token"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def trace_api_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Attach a correlation ID and log only safe API request metadata."""

        path = request.url.path
        if not (path == "/health" or path.startswith("/v1/")):
            return await call_next(request)
        request_id = new_request_id()
        context_token = bind_request_id(request_id)
        started_at = monotonic()
        log_event("http_request_started", method=request.method, path=path)
        try:
            response = await call_next(request)
        except Exception as error:
            log_event(
                "http_request_failed",
                level=40,
                method=request.method,
                path=path,
                duration_ms=elapsed_milliseconds(started_at),
                error_type=type(error).__name__,
            )
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            log_event(
                "http_request_completed",
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=elapsed_milliseconds(started_at),
            )
            return response
        finally:
            reset_request_id(context_token)

    should_serve_web = serve_web if serve_web is not None else _environment_flag("AGENT_SERVE_WEB", default=True)
    if should_serve_web:
        static_directory = web_directory or Path(__file__).resolve().parents[3] / "web"
        if not static_directory.is_dir():
            raise FileNotFoundError(f"Web workspace directory does not exist: {static_directory}")
        app.mount("/web", StaticFiles(directory=static_directory, html=True), name="web")

        @app.get("/", include_in_schema=False)
        def web_root() -> RedirectResponse:
            return RedirectResponse(url="/web/")

    def current_identity(authorization: str | None = Header(default=None)) -> SessionIdentity:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing session token")
        try:
            return app_components.sessions.verify(authorization.removeprefix("Bearer "))
        except AuthenticationError as error:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error

    def enforce_user_rate_limit(identity: SessionIdentity = Depends(current_identity)) -> SessionIdentity:
        decision = app_components.limiter.acquire(f"user:{identity.user_id}:messages", limit=20, window_seconds=60)
        if not decision.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "request limit reached; retry later",
                headers={"Retry-After": str(max(1, round(decision.retry_after_seconds)))},
            )
        return identity

    def require_web_access(
        request: Request,
        x_finance_agent_token: str | None = Header(default=None),
    ) -> None:
        """Allow local Web use, or require an explicit token off the loopback host."""

        configured_token = getenv("AGENT_WEB_ACCESS_TOKEN", "").strip()
        if configured_token:
            if x_finance_agent_token and compare_digest(x_finance_agent_token, configured_token):
                return
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "a valid Web access token is required")
        client_host = request.client.host if request.client else ""
        if client_host in {"127.0.0.1", "::1", "testclient"}:
            return
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Web API is limited to loopback access; set AGENT_WEB_ACCESS_TOKEN before remote access",
        )

    def require_local_credential_access(
        request: Request,
        x_finance_agent_token: str | None = Header(default=None),
    ) -> None:
        """Keep credential maintenance and temporary token display on loopback.

        The rest of the personal Web app can be deliberately enabled for a
        remote device with ``AGENT_WEB_ACCESS_TOKEN``.  Source tokens are more
        sensitive, so their maintenance API remains local even in that case.
        """

        require_web_access(request, x_finance_agent_token)
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Source credential maintenance and token display are limited to loopback access",
            )

    def active_web_workspace() -> WebWorkspaceService:
        if app.state.web_workspace is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Web workspace runtime is not configured; start ai_agent.api.main",
            )
        return app.state.web_workspace

    def active_source_credentials() -> SourceCredentialService:
        if app.state.source_credentials is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Source credential maintenance is not configured; start ai_agent.api.main",
            )
        return app.state.source_credentials

    def active_source_connectivity() -> SourceConnectivityService:
        if app.state.source_connectivity is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Source connectivity checks are not configured; start ai_agent.api.main",
            )
        return app.state.source_connectivity

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "storage": "in_memory_development_only",
            "wechat_login_configured": app_components.wechat is not None,
            "web_workspace_configured": app.state.web_workspace is not None,
        }

    web_router = create_web_router(
        app,
        require_web_access=require_web_access,
        require_local_credential_access=require_local_credential_access,
        active_web_workspace=active_web_workspace,
        active_source_credentials=active_source_credentials,
        active_source_connectivity=active_source_connectivity,
    )
    mini_program_router = create_mini_program_router(
        app_components,
        current_identity=current_identity,
        enforce_user_rate_limit=enforce_user_rate_limit,
    )
    # FastAPI 0.128 keeps include_router entries lazy in app.routes.  These
    # already-compiled APIRoutes stay flat for existing endpoint inspection.
    app.router.routes.extend(web_router.routes)
    app.router.routes.extend(mini_program_router.routes)

    return app
