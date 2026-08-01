"""Provider-backed, bounded discovery of Chinese A-share securities."""

from __future__ import annotations

import json
import re

from ..tools import ToolRegistry
from .entity_resolution import EntityResolution, SecurityCandidate


class SecurityDiscoveryService:
    """Resolve a bare natural-language A-share name without model guessing."""

    def __init__(self, tool_registry_factory):
        self._tool_registry_factory = tool_registry_factory

    def discover(self, query: str) -> EntityResolution:
        registry: ToolRegistry = self._tool_registry_factory()
        if "eastmoney_security_search" not in {tool.name for tool in registry.definitions()}:
            return EntityResolution(query=query)
        symbol = re.search(r"(?<!\d)[036]\d{5}(?!\d)", query)
        search_query = symbol.group(0) if symbol else query
        raw = registry.execute("eastmoney_security_search", {"query": search_query, "limit": 5})
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return EntityResolution(query=query)
        rows = payload.get("matches") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return EntityResolution(query=query)
        candidates: list[SecurityCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code, name, exchange = row.get("code"), row.get("name"), row.get("exchange")
            if not (isinstance(code, str) and isinstance(name, str) and exchange in {"SH", "SZ"}):
                continue
            is_shanghai = exchange == "SH"
            candidates.append(
                SecurityCandidate(
                    key=f"a_share_{exchange.lower()}_{code}",
                    canonical_name=name,
                    display_name=f"{name}（A 股）",
                    yahoo_symbol=f"{code}.{'SS' if is_shanghai else 'SZ'}",
                    eodhd_symbol=f"{code}.{'SHG' if is_shanghai else 'SHE'}",
                    display_symbol=code,
                    market=f"{'上海' if is_shanghai else '深圳'}证券交易所（A 股）",
                    currency="CNY",
                    instrument_type="普通股",
                    description=f"由 A 股证券检索服务识别为 {exchange} 市场上市证券。",
                    continuation_prompt=f"查看{name} A 股 {code} 的基础概览",
                    tickflow_symbol=f"{code}.{exchange}",
                )
            )
        return EntityResolution(query=query, candidates=tuple(candidates))
