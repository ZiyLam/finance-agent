"""Minimal, read-only client for the official Tencent ima knowledge-base API."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

IMA_API_BASE_URL = "https://ima.qq.com/openapi/wiki/v1"


class ImaKnowledgeBaseError(RuntimeError):
    """A safe IMA integration error that never contains credentials or raw bodies."""


@dataclass(frozen=True, slots=True)
class ImaKnowledgeBaseInfo:
    """One IMA knowledge base available to the configured account."""

    identifier: str
    name: str


@dataclass(frozen=True, slots=True)
class ImaKnowledgeSnippet:
    """One bounded IMA search hit safe to pass through the Agent tool boundary."""

    title: str
    snippet: str
    media_type: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "snippet": self.snippet,
            "media_type": self.media_type,
        }


ImaTransport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class ImaKnowledgeBaseClient:
    """Search one explicitly configured, user-owned Tencent ima knowledge base.

    This client deliberately exposes only listing and bounded search.  It does
    not upload, mutate, download, or execute content from the knowledge base.
    """

    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        knowledge_base_id: str | None = None,
        knowledge_base_name: str | None = None,
        timeout_seconds: float = 10.0,
        transport: ImaTransport | None = None,
    ) -> None:
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValueError("IMA client ID must be configured")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("IMA API key must be configured")
        if knowledge_base_id is not None and (not isinstance(knowledge_base_id, str) or not knowledge_base_id.strip()):
            raise ValueError("IMA knowledge-base ID must be non-blank when supplied")
        if knowledge_base_name is not None and (
            not isinstance(knowledge_base_name, str) or not knowledge_base_name.strip()
        ):
            raise ValueError("IMA knowledge-base name must be non-blank when supplied")
        if timeout_seconds <= 0:
            raise ValueError("IMA timeout_seconds must be positive")
        self._client_id = client_id.strip()
        self._api_key = api_key.strip()
        self._knowledge_base_id = knowledge_base_id.strip() if knowledge_base_id else None
        self._knowledge_base_name = knowledge_base_name.strip() if knowledge_base_name else None
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport
        self._target_lock = Lock()

    def list_knowledge_bases(self, *, limit: int = 20) -> tuple[ImaKnowledgeBaseInfo, ...]:
        """List accessible knowledge bases for setup; callers keep IDs server-side."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("IMA knowledge-base list limit must be an integer between 1 and 20")
        payload = self._post("search_knowledge_base", {"query": "", "cursor": "", "limit": limit})
        data = payload.get("data")
        rows = data.get("info_list") if isinstance(data, Mapping) else None
        if not isinstance(rows, list):
            raise ImaKnowledgeBaseError("IMA returned an unexpected knowledge-base list")
        return self._parse_knowledge_base_infos(rows)

    @staticmethod
    def _parse_knowledge_base_infos(rows: list[object]) -> tuple[ImaKnowledgeBaseInfo, ...]:
        """Normalize documented and currently observed IMA list response fields."""

        result: list[ImaKnowledgeBaseInfo] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            # The published API reference documents ``id`` / ``name``.  The
            # current IMA service returns the equivalent ``kb_id`` /
            # ``kb_name`` fields, so support both without leaking either ID
            # past this setup-only client boundary.
            identifier = row.get("id") if isinstance(row.get("id"), str) and row.get("id") else row.get("kb_id")
            name = row.get("name") if isinstance(row.get("name"), str) and row.get("name") else row.get("kb_name")
            if isinstance(identifier, str) and identifier and isinstance(name, str) and name:
                result.append(ImaKnowledgeBaseInfo(identifier=identifier, name=name))
        return tuple(result)

    def search(self, query: str, *, limit: int = 8) -> tuple[ImaKnowledgeSnippet, ...]:
        """Return a bounded set of reference snippets from the selected knowledge base."""

        knowledge_base_id = self._resolve_knowledge_base_id()
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 400:
            raise ValueError("IMA knowledge query must contain 1 to 400 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("IMA knowledge search limit must be an integer between 1 and 20")
        payload = self._post(
            "search_knowledge",
            {
                "query": query.strip(),
                "knowledge_base_id": knowledge_base_id,
                "cursor": "",
            },
        )
        data = payload.get("data")
        rows = data.get("info_list") if isinstance(data, Mapping) else None
        if not isinstance(rows, list):
            raise ImaKnowledgeBaseError("IMA returned an unexpected knowledge search response")
        results: list[ImaKnowledgeSnippet] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            title = _bounded_text(row.get("title"), 300)
            snippet = _bounded_text(row.get("highlight_content"), 1_500)
            media_type = row.get("media_type")
            if not title and not snippet:
                continue
            results.append(
                ImaKnowledgeSnippet(
                    title=title or "Untitled IMA knowledge item",
                    snippet=snippet,
                    media_type=media_type if isinstance(media_type, int) and not isinstance(media_type, bool) else None,
                )
            )
            if len(results) >= limit:
                break
        return tuple(results)

    def _resolve_knowledge_base_id(self) -> str:
        """Resolve an explicit name only on first use, never during startup."""

        if self._knowledge_base_id is not None:
            return self._knowledge_base_id
        if self._knowledge_base_name is None:
            raise ImaKnowledgeBaseError("IMA knowledge-base target is not configured")
        with self._target_lock:
            if self._knowledge_base_id is not None:
                return self._knowledge_base_id
            payload = self._post(
                "search_knowledge_base",
                {"query": self._knowledge_base_name, "cursor": "", "limit": 20},
            )
            data = payload.get("data")
            rows = data.get("info_list") if isinstance(data, Mapping) else None
            if not isinstance(rows, list):
                raise ImaKnowledgeBaseError("IMA returned an unexpected knowledge-base list")
            matches = [item for item in self._parse_knowledge_base_infos(rows) if item.name == self._knowledge_base_name]
            if not matches:
                raise ImaKnowledgeBaseError(f"IMA knowledge base '{self._knowledge_base_name}' was not found")
            if len(matches) > 1:
                raise ImaKnowledgeBaseError(f"IMA knowledge base name '{self._knowledge_base_name}' is ambiguous")
            self._knowledge_base_id = matches[0].identifier
            return self._knowledge_base_id

    def _post(self, endpoint: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "ima-openapi-clientid": self._client_id,
            "ima-openapi-apikey": self._api_key,
        }
        try:
            raw = self._transport(f"{IMA_API_BASE_URL}/{endpoint}", body, headers, self._timeout_seconds)
            response = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            raise ImaKnowledgeBaseError(f"IMA request failed with HTTP status {error.code}") from None
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ImaKnowledgeBaseError("Could not reach the IMA knowledge-base service") from None
        if not isinstance(response, Mapping):
            raise ImaKnowledgeBaseError("IMA returned an unexpected response")
        if response.get("code") != 0:
            raise ImaKnowledgeBaseError("IMA rejected the knowledge-base request")
        return response

    @staticmethod
    def _default_transport(url: str, body: bytes, headers: Mapping[str, str], timeout_seconds: float) -> bytes:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read()


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]
