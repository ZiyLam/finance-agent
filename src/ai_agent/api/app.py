"""FastAPI application factory for the authenticated mini-program backend."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from typing import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..application.input_parser import ResearchIntentParser
from ..application.narration import ReportNarrator
from ..application.research_service import ResearchService
from ..infrastructure.rate_limit import InMemoryRateLimiter
from ..infrastructure.store import InMemoryApplicationStore
from ..infrastructure.task_queue import InMemoryTaskQueue
from ..tools import ToolRegistry
from .auth import (
    AccessDeniedError,
    AccessPolicy,
    AuthenticationError,
    SessionIdentity,
    SessionTokenCodec,
    WechatIdentityProvider,
    WechatMiniProgramClient,
)


class WechatLoginPayload(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class ConversationMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=4_000)


@dataclass(slots=True)
class ApplicationComponents:
    """Injected dependencies make HTTP, worker, and integration tests deterministic."""

    research: ResearchService
    sessions: SessionTokenCodec
    wechat: WechatIdentityProvider | None
    limiter: InMemoryRateLimiter
    access_policy: AccessPolicy


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
) -> FastAPI:
    """Create the HTTP app without exposing data-source credentials to clients."""

    app_components = components or create_development_components(
        tool_registry_factory=tool_registry_factory,
        narrator=narrator,
    )
    app = FastAPI(title="Finance Agent Mini-program API", version="0.2.0")
    app.state.components = app_components

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

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "storage": "in_memory_development_only",
            "wechat_login_configured": app_components.wechat is not None,
        }

    @app.post("/v1/auth/wechat/login")
    def login(payload: WechatLoginPayload) -> dict[str, object]:
        if app_components.wechat is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "WeChat login is not configured; set WECHAT_APP_ID and WECHAT_APP_SECRET on the server",
            )
        try:
            user_id = app_components.wechat.exchange_code(payload.code)
            app_components.access_policy.assert_allowed(user_id)
            token, identity = app_components.sessions.issue(user_id)
        except AuthenticationError as error:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
        except AccessDeniedError as error:
            status_code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if "no owner user" in str(error)
                else status.HTTP_403_FORBIDDEN
            )
            raise HTTPException(status_code, str(error)) from error
        response = {"access_token": token, "token_type": "Bearer", "expires_at": identity.expires_at.isoformat()}
        # The opaque ID is helpful for a one-time owner allow-list bootstrap in
        # development.  It is never emitted in a production response.
        if getenv("AGENT_ENV", "development").strip().lower() != "production":
            response["user_id"] = identity.user_id
        return response

    @app.post("/v1/conversations", status_code=status.HTTP_201_CREATED)
    def create_conversation(identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        conversation = app_components.research.create_conversation(identity.user_id)
        return {"id": conversation.id, "created_at": conversation.created_at.isoformat()}

    @app.post("/v1/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    def submit_message(
        conversation_id: str,
        payload: ConversationMessagePayload,
        background_tasks: BackgroundTasks,
        identity: SessionIdentity = Depends(enforce_user_rate_limit),
    ) -> dict[str, object]:
        try:
            submission = app_components.research.submit_message(identity.user_id, conversation_id, payload.content)
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation was not found") from error
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        if submission.task_id:
            # Local development convenience.  Production workers must consume a
            # distributed queue and must not run inside API request workers.
            background_tasks.add_task(app_components.research.run_next_task)
        return submission.to_dict()

    @app.get("/v1/tasks/{task_id}")
    def get_task(task_id: str, identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        task = app_components.research.get_task(identity.user_id, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task was not found")
        return task.to_dict()

    @app.get("/v1/reports/{report_id}")
    def get_report(report_id: str, identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        report = app_components.research.get_report(identity.user_id, report_id)
        if report is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "report was not found")
        return {"id": report.id, "task_id": report.task_id, "created_at": report.created_at.isoformat(), "report": report.payload}

    return app
