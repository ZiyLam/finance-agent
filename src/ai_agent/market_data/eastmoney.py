"""Read-only, token-free A-share security-name search adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EASTMONEY_SEARCH_API = "https://searchapi.eastmoney.com/api/suggest/get"
EASTMONEY_INDUSTRY_API = "https://push2.eastmoney.com/api/qt/clist/get"
# Eastmoney's public suggestion endpoint expects this documented browser-client
# identifier; it is not a user credential and cannot access an account.
_PUBLIC_SEARCH_TOKEN = "D43BF722C4047D6E6D99A9CC5A5E9B0B"


class EastmoneySearchError(RuntimeError):
    """Safe A-share security-search error without request internals."""


@dataclass(frozen=True, slots=True)
class EastmoneySecurityMatch:
    code: str
    name: str
    exchange: str


@dataclass(frozen=True, slots=True)
class EastmoneyIndustry:
    code: str
    name: str
    change_percent: float
    main_net_inflow: float | None


class EastmoneySecuritySearchClient:
    """Resolve a Chinese A-share name into bounded exchange-labelled matches."""

    def __init__(self, *, timeout_seconds: float = 4.0, transport: Callable[[str], bytes] | None = None) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._default_transport

    def search(self, query: str, limit: int = 5) -> tuple[EastmoneySecurityMatch, ...]:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
            raise ValueError("A-share security query must contain 1 to 100 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ValueError("A-share search limit must be between 1 and 10")
        raw = self._get_json({"input": query.strip(), "type": "14", "count": str(limit), "market": "0", "token": _PUBLIC_SEARCH_TOKEN})
        data = raw.get("QuotationCodeTable", {}).get("Data", []) if isinstance(raw, Mapping) else []
        if not isinstance(data, list):
            raise EastmoneySearchError("A-share security search returned an unexpected response")
        matches: list[EastmoneySecurityMatch] = []
        for item in data:
            if not isinstance(item, Mapping) or item.get("Classify") != "AStock":
                continue
            code, name, exchange = item.get("Code"), item.get("Name"), item.get("JYS")
            if not (isinstance(code, str) and code.isdigit() and len(code) == 6 and isinstance(name, str)):
                continue
            if exchange == "2":
                matches.append(EastmoneySecurityMatch(code, name, "SH"))
            elif exchange == "1":
                matches.append(EastmoneySecurityMatch(code, name, "SZ"))
        return tuple(matches[:limit])

    def leading_industries(self, limit: int = 8, *, descending: bool = True) -> tuple[EastmoneyIndustry, ...]:
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("industry ranking limit must be between 1 and 20")
        parameters = {"pn": "1", "pz": str(limit), "po": "1" if descending else "0", "np": "1", "fltt": "2", "invt": "2", "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3,f62"}
        payload = self._get_json_from_url(f"{EASTMONEY_INDUSTRY_API}?{urlencode(parameters)}")
        rows = payload.get("data", {}).get("diff", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list):
            raise EastmoneySearchError("Industry ranking returned an unexpected response")
        result = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("f12"), str) or not isinstance(row.get("f14"), str):
                continue
            try:
                result.append(EastmoneyIndustry(row["f12"], row["f14"], float(row["f3"]), float(row["f62"]) if row.get("f62") is not None else None))
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def _get_json(self, parameters: Mapping[str, str]) -> Any:
        return self._get_json_from_url(f"{EASTMONEY_SEARCH_API}?{urlencode(parameters)}")

    def _get_json_from_url(self, url: str) -> Any:
        try:
            raw = self._transport(url)
            return json.loads(raw.decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise EastmoneySearchError("Could not reach the A-share security-search service") from None

    def _default_transport(self, url: str) -> bytes:
        with urlopen(
            Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            ),
            timeout=self._timeout_seconds,
        ) as response:
            return response.read()
