"""WeChat identity exchange and short-lived signed application sessions."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from os import getenv
from typing import Any, Callable, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen


class AuthenticationError(RuntimeError):
    """Safe identity error that never contains a WeChat code or secret."""


class AccessDeniedError(RuntimeError):
    """The authenticated account is not allowed to use this private service."""


class WechatIdentityProvider(Protocol):
    def exchange_code(self, code: str) -> str: ...


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    user_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Restrict a personal deployment to explicitly approved internal users."""

    personal_mode: bool = False
    allowed_user_ids: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls) -> "AccessPolicy":
        personal_mode = getenv("AGENT_PERSONAL_MODE", "false").strip().lower() in {"1", "true", "yes"}
        allowed = frozenset(
            value.strip()
            for value in getenv("AGENT_ALLOWED_USER_IDS", "").split(",")
            if value.strip()
        )
        return cls(personal_mode=personal_mode, allowed_user_ids=allowed)

    def assert_allowed(self, user_id: str) -> None:
        if not self.personal_mode:
            return
        if not self.allowed_user_ids:
            raise AccessDeniedError("personal mode is enabled but no owner user is configured")
        if user_id not in self.allowed_user_ids:
            raise AccessDeniedError("this WeChat account is not allowed to use the private service")


class SessionTokenCodec:
    """Issue HMAC-signed, short-lived tokens without adding a JWT dependency."""

    def __init__(self, secret: str, *, lifetime_seconds: int = 86_400) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        if lifetime_seconds < 60:
            raise ValueError("session lifetime must be at least 60 seconds")
        self._secret = secret.encode("utf-8")
        self._lifetime = lifetime_seconds

    def issue(self, user_id: str) -> tuple[str, SessionIdentity]:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._lifetime)
        payload = {"sub": user_id, "exp": int(expires_at.timestamp())}
        encoded = _urlsafe_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._secret, encoded.encode("ascii"), "sha256").digest()
        return f"v1.{encoded}.{_urlsafe_encode(signature)}", SessionIdentity(user_id, expires_at)

    def verify(self, token: str) -> SessionIdentity:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            raise AuthenticationError("invalid session token")
        encoded, supplied_signature = parts[1], parts[2]
        expected_signature = _urlsafe_encode(hmac.new(self._secret, encoded.encode("ascii"), "sha256").digest())
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise AuthenticationError("invalid session token")
        try:
            payload = json.loads(_urlsafe_decode(encoded).decode("utf-8"))
            user_id, expires_at = payload["sub"], datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuthenticationError("invalid session token") from error
        if not isinstance(user_id, str) or not user_id or expires_at <= datetime.now(timezone.utc):
            raise AuthenticationError("session token has expired")
        return SessionIdentity(user_id, expires_at)


class WechatMiniProgramClient:
    """Minimal server-side adapter for the documented code-to-session exchange."""

    endpoint = "https://api.weixin.qq.com/sns/jscode2session"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        transport: Callable[[str], bytes] | None = None,
    ) -> None:
        if not app_id.strip() or not app_secret.strip():
            raise ValueError("WeChat app_id and app_secret are required")
        self._app_id = app_id.strip()
        self._app_secret = app_secret.strip()
        self._transport = transport or self._default_transport

    @classmethod
    def from_environment(cls) -> "WechatMiniProgramClient | None":
        app_id, app_secret = getenv("WECHAT_APP_ID", ""), getenv("WECHAT_APP_SECRET", "")
        return cls(app_id, app_secret) if app_id.strip() and app_secret.strip() else None

    def exchange_code(self, code: str) -> str:
        if not isinstance(code, str) or not code.strip() or len(code) > 256:
            raise AuthenticationError("invalid WeChat login code")
        query = urlencode(
            {
                "appid": self._app_id,
                "secret": self._app_secret,
                "js_code": code.strip(),
                "grant_type": "authorization_code",
            }
        )
        try:
            raw = self._transport(f"{self.endpoint}?{query}")
            payload = json.loads(raw.decode("utf-8"))
            open_id = payload.get("openid")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise AuthenticationError("WeChat login could not be verified; try again later") from error
        if not isinstance(open_id, str) or not open_id:
            raise AuthenticationError("WeChat rejected the login code; try logging in again")
        # Do not persist or expose the platform identifier to application callers.
        return "wx_" + sha256(f"{self._app_id}:{open_id}".encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _default_transport(url: str) -> bytes:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - fixed HTTPS endpoint
            return response.read()


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
