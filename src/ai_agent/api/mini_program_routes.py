"""Authenticated mini-program conversation, task, and report routes."""

from __future__ import annotations

from os import getenv
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .auth import AccessDeniedError, AuthenticationError, SessionIdentity


class WechatLoginPayload(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class ConversationMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=4_000)


def create_mini_program_router(
    components: Any,
    *,
    current_identity: Callable[..., SessionIdentity],
    enforce_user_rate_limit: Callable[..., SessionIdentity],
) -> APIRouter:
    """Build mini-program routes without coupling them to FastAPI app assembly."""

    router = APIRouter()

    @router.post("/v1/auth/wechat/login")
    def login(payload: WechatLoginPayload) -> dict[str, object]:
        if components.wechat is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "WeChat login is not configured; set WECHAT_APP_ID and WECHAT_APP_SECRET on the server",
            )
        try:
            user_id = components.wechat.exchange_code(payload.code)
            components.access_policy.assert_allowed(user_id)
            token, identity = components.sessions.issue(user_id)
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

    @router.post("/v1/conversations", status_code=status.HTTP_201_CREATED)
    def create_conversation(identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        conversation = components.research.create_conversation(identity.user_id)
        return {"id": conversation.id, "created_at": conversation.created_at.isoformat()}

    @router.post("/v1/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    def submit_message(
        conversation_id: str,
        payload: ConversationMessagePayload,
        background_tasks: BackgroundTasks,
        identity: SessionIdentity = Depends(enforce_user_rate_limit),
    ) -> dict[str, object]:
        try:
            submission = components.research.submit_message(identity.user_id, conversation_id, payload.content)
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation was not found") from error
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        if submission.task_id:
            # Local development convenience.  Production workers must consume a
            # distributed queue and must not run inside API request workers.
            background_tasks.add_task(components.research.run_next_task)
        return submission.to_dict()

    @router.get("/v1/tasks/{task_id}")
    def get_task(task_id: str, identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        task = components.research.get_task(identity.user_id, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task was not found")
        return task.to_dict()

    @router.get("/v1/reports/{report_id}")
    def get_report(report_id: str, identity: SessionIdentity = Depends(current_identity)) -> dict[str, object]:
        report = components.research.get_report(identity.user_id, report_id)
        if report is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "report was not found")
        return {"id": report.id, "task_id": report.task_id, "created_at": report.created_at.isoformat(), "report": report.payload}

    return router

