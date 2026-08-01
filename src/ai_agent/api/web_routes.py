"""Routes for the personal Web workspace and provider settings."""

from __future__ import annotations

from datetime import date
from typing import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..application.source_connectivity import SourceConnectivityService
from ..application.source_credentials import SourceCredentialError, SourceCredentialService
from ..application.web_workspace import WebWorkspaceError, WebWorkspaceService


class WebChatPayload(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    content: str = Field(min_length=1)


class WebResearchPayload(BaseModel):
    content: str = Field(min_length=1)


class WebProfessionalResearchPayload(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    conversation_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    content: str = ""
    start_date: date
    end_date: date
    markets: list[str] = Field(min_length=1, max_length=5)
    indices: list[str] = Field(min_length=1, max_length=6)
    metrics: list[str] = Field(min_length=1, max_length=6)


class SourceTokenPayload(BaseModel):
    """A write-only token payload whose rejected value is never echoed."""

    model_config = ConfigDict(hide_input_in_errors=True)
    token: str


class SourceEnabledPayload(BaseModel):
    enabled: StrictBool


def create_web_router(
    app: FastAPI,
    *,
    require_web_access: Callable[..., None],
    require_local_credential_access: Callable[..., None],
    active_web_workspace: Callable[[], WebWorkspaceService],
    active_source_credentials: Callable[[], SourceCredentialService],
    active_source_connectivity: Callable[[], SourceConnectivityService],
) -> APIRouter:
    """Build Web routes around dependencies owned by the application factory."""

    router = APIRouter()

    @router.get("/v1/web/status")
    def web_status(
        _: None = Depends(require_web_access),
        workspace: WebWorkspaceService = Depends(active_web_workspace),
    ) -> dict[str, object]:
        try:
            return workspace.status()
        except WebWorkspaceError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post("/v1/web/chat")
    def web_chat(
        payload: WebChatPayload,
        _: None = Depends(require_web_access),
        workspace: WebWorkspaceService = Depends(active_web_workspace),
    ) -> dict[str, object]:
        try:
            return workspace.chat(
                conversation_id=payload.conversation_id,
                content=payload.content,
            ).to_dict()
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        except WebWorkspaceError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post("/v1/web/professional-research")
    def web_professional_research(
        payload: WebProfessionalResearchPayload,
        _: None = Depends(require_web_access),
        workspace: WebWorkspaceService = Depends(active_web_workspace),
    ) -> dict[str, object]:
        """Compare reviewed indices without a model call or unbounded tool loop."""

        try:
            return workspace.professional_research(
                conversation_id=payload.conversation_id,
                content=payload.content,
                start_date=payload.start_date,
                end_date=payload.end_date,
                markets=tuple(payload.markets),
                indices=tuple(payload.indices),
                metrics=tuple(payload.metrics),
            ).to_dict()
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        except WebWorkspaceError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post("/v1/web/reports")
    def web_report(
        payload: WebResearchPayload,
        _: None = Depends(require_web_access),
        workspace: WebWorkspaceService = Depends(active_web_workspace),
    ) -> dict[str, object]:
        try:
            report = workspace.run_report(
                content=payload.content,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        except WebWorkspaceError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
        return {"report": report}

    @router.get("/v1/web/sources")
    def web_sources(
        response: Response,
        _: None = Depends(require_local_credential_access),
        credentials: SourceCredentialService = Depends(active_source_credentials),
    ) -> dict[str, object]:
        """List configuration state without returning credential values."""

        try:
            # Configuration state can change during a session and should not
            # remain in browser/proxy caches.  This response never includes a
            # credential value, even on loopback development hosts.
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            sources = credentials.list_sources()
            connectivity = app.state.source_connectivity
            for source in sources:
                source["connectivity"] = (
                    connectivity.snapshot(str(source["name"]))
                    if connectivity is not None
                    else {
                        "name": source["name"],
                        "status": "untested",
                        "checked_at": None,
                        "duration_ms": None,
                        "category": "not_tested",
                        "message": "尚未执行连通性测试。",
                    }
                )
            return {"sources": sources}
        except SourceCredentialError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post("/v1/web/sources/connectivity")
    def check_all_web_source_connectivity(
        response: Response,
        configuration_group: str | None = None,
        _: None = Depends(require_local_credential_access),
        connectivity: SourceConnectivityService = Depends(active_source_connectivity),
    ) -> dict[str, object]:
        """Run bounded read-only smoke tests in catalog routing order."""

        try:
            response.headers["Cache-Control"] = "no-store, private"
            return {"sources": connectivity.check_all(configuration_group)}
        except ValueError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Unknown source configuration group",
            ) from error

    @router.post("/v1/web/sources/{source}/connectivity")
    def check_web_source_connectivity(
        source: str,
        response: Response,
        _: None = Depends(require_local_credential_access),
        connectivity: SourceConnectivityService = Depends(active_source_connectivity),
    ) -> dict[str, object]:
        """Run one explicit, minimal and read-only source smoke test."""

        try:
            response.headers["Cache-Control"] = "no-store, private"
            return {"source": connectivity.check(source)}
        except ValueError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data source") from error

    @router.put("/v1/web/sources/{source}/token")
    def save_web_source_token(
        source: str,
        payload: SourceTokenPayload,
        _: None = Depends(require_local_credential_access),
        credentials: SourceCredentialService = Depends(active_source_credentials),
    ) -> dict[str, object]:
        """Save one token in the current user's encrypted local store."""

        if not payload.token.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Token cannot be blank")
        if len(payload.token) > 4_096:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Token is too long")
        try:
            result = credentials.set_token(source, payload.token)
            if app.state.source_connectivity is not None:
                app.state.source_connectivity.invalidate(source)
            return {"source": result}
        except ValueError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data source") from error
        except SourceCredentialError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.put("/v1/web/sources/{source}/enabled")
    def set_web_source_enabled(
        source: str,
        payload: SourceEnabledPayload,
        _: None = Depends(require_local_credential_access),
        credentials: SourceCredentialService = Depends(active_source_credentials),
    ) -> dict[str, object]:
        """Enable or disable one provider for every runtime execution path."""

        try:
            result = credentials.set_enabled(source, payload.enabled)
            if app.state.source_connectivity is not None:
                app.state.source_connectivity.invalidate(source)
            return {"source": result}
        except ValueError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data source") from error
        except SourceCredentialError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.delete("/v1/web/sources/{source}/token")
    def delete_web_source_token(
        source: str,
        _: None = Depends(require_local_credential_access),
        credentials: SourceCredentialService = Depends(active_source_credentials),
    ) -> dict[str, object]:
        """Delete only the encrypted local token; environment values remain."""

        try:
            result = credentials.delete_token(source)
            if app.state.source_connectivity is not None:
                app.state.source_connectivity.invalidate(source)
            return {"source": result}
        except ValueError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data source") from error
        except SourceCredentialError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    return router

