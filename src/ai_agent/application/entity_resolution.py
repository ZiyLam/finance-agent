"""Deterministic resolution for a small, reviewed set of common securities.

This is deliberately not a general-purpose security master.  It runs before
the model only where a name has a known ambiguity, so the UI can explain that
ambiguity instead of asking an LLM to guess an exchange or currency.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class SecurityCandidate:
    """One explicitly curated listed-security candidate."""

    key: str
    canonical_name: str
    display_name: str
    yahoo_symbol: str
    eodhd_symbol: str | None
    display_symbol: str
    market: str
    currency: str
    instrument_type: str
    description: str
    continuation_prompt: str
    tickflow_symbol: str | None = None
    zhitu_index_symbol: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "symbol": self.display_symbol,
            "yahoo_symbol": self.yahoo_symbol,
            "eodhd_symbol": self.eodhd_symbol,
            "market": self.market,
            "currency": self.currency,
            "instrument_type": self.instrument_type,
            "description": self.description,
            "continuation_prompt": self.continuation_prompt,
        }


@dataclass(frozen=True, slots=True)
class EntityResolution:
    """The result of matching a request against the reviewed alias directory."""

    query: str
    candidates: tuple[SecurityCandidate, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return len(self.candidates) > 1

    @property
    def is_unique(self) -> bool:
        return len(self.candidates) == 1


HSBC_HK = SecurityCandidate(
    key="hsbc_hk",
    canonical_name="HSBC Holdings plc",
    display_name="汇丰控股（港股）",
    yahoo_symbol="0005.HK",
    eodhd_symbol="0005.HK",
    display_symbol="0005",
    market="香港交易所（港股）",
    currency="HKD",
    instrument_type="普通股",
    description="汇丰控股在香港交易所的普通股上市，交易及报价币种为港币。",
    continuation_prompt="查看汇丰控股港股 0005 的基础概览",
    tickflow_symbol="0005.HK",
)

HSBC_ADR = SecurityCandidate(
    key="hsbc_adr",
    canonical_name="HSBC Holdings plc",
    display_name="汇丰控股（美股 ADR）",
    yahoo_symbol="HSBC",
    eodhd_symbol="HSBC.US",
    display_symbol="HSBC",
    market="纽约证券交易所（美股）",
    currency="USD",
    instrument_type="ADR",
    description="汇丰控股在纽约证券交易所的美国存托凭证（ADR），交易及报价币种为美元。",
    continuation_prompt="查看汇丰控股美股 ADR HSBC 的基础概览",
    tickflow_symbol="HSBC.US",
)

KWEICHOW_MOUTAI = SecurityCandidate(
    key="kweichow_moutai_a_share",
    canonical_name="Kweichow Moutai Co., Ltd.",
    display_name="贵州茅台（A 股）",
    yahoo_symbol="600519.SS",
    eodhd_symbol="600519.SHG",
    display_symbol="600519",
    market="上海证券交易所（A 股）",
    currency="CNY",
    instrument_type="普通股",
    description="贵州茅台在上海证券交易所的 A 股普通股，交易及报价币种为人民币。",
    continuation_prompt="查看贵州茅台 A 股 600519 的基础概览",
    tickflow_symbol="600519.SH",
)


class SecurityEntityResolver:
    """Resolve only reviewed aliases and keep genuine listing ambiguity visible."""

    _generic_aliases = ("汇丰银行", "汇丰控股", "汇丰", "hsbc holdings")
    _moutai_aliases = ("贵州茅台", "贵州茅台酒", "茅台", "kweichow moutai")

    def resolve(self, query: str) -> EntityResolution:
        normalized = _normalize(query)
        if not normalized:
            return EntityResolution(query=query)

        has_hsbc_name = any(alias in normalized for alias in self._generic_aliases)
        has_moutai_name = any(alias in normalized for alias in self._moutai_aliases)
        has_hk_symbol = _contains_ticker(normalized, "0005.hk") or _contains_ticker(normalized, "0005")
        has_us_symbol = _contains_ticker(normalized, "hsbc")
        has_moutai_symbol = _contains_ticker(normalized, "600519")
        has_hk_cue = any(cue in normalized for cue in ("港股", "香港", "港币", "hkd"))
        has_adr_cue = any(cue in normalized for cue in ("adr", "美股", "纽约", "美元", "usd"))

        if has_hk_symbol or (has_hsbc_name and has_hk_cue and not has_adr_cue):
            return EntityResolution(query=query, candidates=(HSBC_HK,))
        if has_us_symbol or (has_hsbc_name and has_adr_cue and not has_hk_cue):
            return EntityResolution(query=query, candidates=(HSBC_ADR,))
        if has_moutai_symbol or has_moutai_name:
            return EntityResolution(query=query, candidates=(KWEICHOW_MOUTAI,))
        if has_hsbc_name:
            return EntityResolution(query=query, candidates=(HSBC_HK, HSBC_ADR))
        return EntityResolution(query=query)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _contains_ticker(text: str, ticker: str) -> bool:
    """Match ASCII symbols without letting a larger word create a false match."""

    return re.search(rf"(?<![a-z0-9.]){re.escape(ticker)}(?![a-z0-9.])", text) is not None
