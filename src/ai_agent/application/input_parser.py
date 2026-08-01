"""Deterministic first-pass parsing for Chinese financial research requests.

The parser intentionally recognizes only high-confidence conventions.  It does
not guess an issuer from a company name, an exchange from an ambiguous ticker,
or a date range that the user did not state.  Those cases become structured
clarification items for the mini-program.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
import re
from typing import Callable

from ..analysis_tags import AnalysisScenario, Market
from .contracts import Clarification, ResearchIntent


_A_SHARE_CODE = re.compile(r"(?<![A-Za-z0-9])(?:(?:sh|sz|bj)\.)?(\d{6})(?:\.(?:SS|SZ))?(?![A-Za-z0-9])", re.I)
_GLOBAL_SYMBOL = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9.-]{0,15}\.(?:US|HK))(?![A-Za-z0-9])", re.I)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2})\b")
_CHINESE_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日?")
_RECENT_RANGE = re.compile(r"(?:最近|近)([一二三四五六七八九十\d]+)(个?月|天|年)")


class ResearchIntentParser:
    """Parse a bounded research intent without calling an LLM or data provider."""

    def __init__(self, *, today: Callable[[], date] = date.today) -> None:
        self._today = today

    def parse(self, user_input: str) -> ResearchIntent:
        text = user_input.strip()
        if not text:
            raise ValueError("user_input cannot be blank")

        symbol, market = self._instrument_for(text)
        scenario = self._scenario_for(text, market)
        date_range_invalid = False
        try:
            start_date, end_date, assumptions = self._date_range_for(text)
        except ValueError:
            date_range_invalid = True
            start_date, end_date, assumptions = None, None, ["检测到无效日期；需要用户重新确认日期区间"]
        clarifications: list[Clarification] = []

        if symbol is None:
            clarifications.append(
                Clarification(
                    "symbol",
                    "未能可靠识别标的。请提供股票代码，或先搜索并选择公司。",
                )
            )
        if market is None:
            clarifications.append(
                Clarification(
                    "market",
                    "请确认市场：A 股、港股、美股或其他全球市场。",
                    ("A 股", "港股/美股等全球市场"),
                )
            )

        if market is Market.GLOBAL and scenario is AnalysisScenario.A_SHARE_VALUATION_SNAPSHOT:
            clarifications.append(
                Clarification(
                    "scenario",
                    "当前估值快照仅支持 A 股；请改为 A 股标的，或选择全球市场的历史行情研究。",
                )
            )

        requires_date_range = scenario in {
            AnalysisScenario.A_SHARE_PRICE_HISTORY,
            AnalysisScenario.GLOBAL_PRICE_HISTORY,
            AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
            AnalysisScenario.RESEARCH_BRIEF,
        }
        if requires_date_range and start_date is None and end_date is None and not date_range_invalid:
            start_date = (self._today() - timedelta(days=7)).isoformat()
            end_date = self._today().isoformat()
            assumptions.append(f"未指定时间范围，默认使用过去一周（{start_date}）至 T0（{end_date}）")
        elif requires_date_range and (start_date is None or end_date is None):
            clarifications.append(
                Clarification(
                    "date_range",
                    "请提供分析区间，例如“最近三个月”或“2026-01-01 至 2026-03-31”。",
                )
            )

        return ResearchIntent(
            original_text=text,
            scenario=scenario,
            market=market,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            assumptions=tuple(assumptions),
            clarifications=tuple(clarifications),
        )

    @staticmethod
    def _scenario_for(text: str, market: Market | None) -> AnalysisScenario:
        normalized = text.lower()
        if any(word in normalized for word in ("报告", "研报", "完整研究", "研究一下")):
            return AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION
        if any(word in normalized for word in ("实时", "最新价", "现价", "报价", "多少钱")):
            return (
                AnalysisScenario.GLOBAL_MARKET_SNAPSHOT
                if market is Market.GLOBAL
                else AnalysisScenario.A_SHARE_REALTIME_QUOTE
            )
        if any(word in normalized for word in ("估值", "市盈", "市净", "pe", "pb")):
            return AnalysisScenario.A_SHARE_VALUATION_SNAPSHOT
        if any(word in normalized for word in ("搜索", "查代码", "代码是什么", "找股票")):
            return AnalysisScenario.SECURITY_LOOKUP
        if any(word in normalized for word in ("走势", "历史", "k线", "k 线", "涨跌", "近", "过去")):
            return (
                AnalysisScenario.GLOBAL_PRICE_HISTORY
                if market is Market.GLOBAL
                else AnalysisScenario.A_SHARE_PRICE_HISTORY
            )
        return (
            AnalysisScenario.RESEARCH_BRIEF
            if market is not Market.GLOBAL
            else AnalysisScenario.GLOBAL_PRICE_HISTORY
        )

    @staticmethod
    def _instrument_for(text: str) -> tuple[str | None, Market | None]:
        a_share = _A_SHARE_CODE.search(text)
        if a_share:
            return a_share.group(1), Market.A_SHARE
        global_symbol = _GLOBAL_SYMBOL.search(text)
        if global_symbol:
            return global_symbol.group(1).upper(), Market.GLOBAL
        normalized = text.lower()
        if any(word in normalized for word in ("美股", "港股", "纳斯达克", "纽交所", "加密", "外汇")):
            return None, Market.GLOBAL
        if any(word in normalized for word in ("a股", "a 股", "沪", "深", "北交")):
            return None, Market.A_SHARE
        return None, None

    def _date_range_for(self, text: str) -> tuple[str | None, str | None, list[str]]:
        assumptions: list[str] = []
        dates = [_normalise_date(value) for value in _ISO_DATE.findall(text)]
        if len(dates) >= 2:
            return dates[0], dates[1], assumptions
        chinese_dates = [date(int(year), int(month), int(day)).isoformat() for year, month, day in _CHINESE_DATE.findall(text)]
        if len(chinese_dates) >= 2:
            return chinese_dates[0], chinese_dates[1], assumptions

        today = self._today()
        recent = _RECENT_RANGE.search(text)
        if recent:
            quantity = _chinese_number(recent.group(1))
            unit = recent.group(2)
            if quantity is not None and quantity > 0:
                if "月" in unit:
                    start = _subtract_months(today, quantity)
                elif unit == "年":
                    start = _subtract_months(today, quantity * 12)
                else:
                    start = today - timedelta(days=quantity)
                assumptions.append(f"“{recent.group(0)}”按截至 {today.isoformat()} 的自然日区间解析")
                return start.isoformat(), today.isoformat(), assumptions
        if "本月" in text:
            assumptions.append(f"“本月”按 {today.year}-{today.month:02d}-01 至 {today.isoformat()} 解析")
            return date(today.year, today.month, 1).isoformat(), today.isoformat(), assumptions
        if "今年" in text:
            assumptions.append(f"“今年”按 {today.year}-01-01 至 {today.isoformat()} 解析")
            return date(today.year, 1, 1).isoformat(), today.isoformat(), assumptions
        named_range = _named_time_range(text, today)
        if named_range is not None:
            start, end, explanation = named_range
            assumptions.append(explanation)
            return start.isoformat(), end.isoformat(), assumptions
        return None, None, assumptions


def _named_time_range(text: str, today: date) -> tuple[date, date, str] | None:
    """Resolve common unquantified time phrases before applying the T-1/T0 default.

    The resolved range is retained as an assumption, preventing “近期” or
    “最近” from silently falling back to the much narrower default window.
    """

    normalized = text.casefold()
    if any(phrase in normalized for phrase in ("近期", "最近", "近来", "近段时间", "recent", "lately")):
        start = today - timedelta(days=30)
        return start, today, f"检测到近期/最近等时间表达，按最近 30 个自然日（{start.isoformat()} 至 {today.isoformat()}）解析"
    if "短期" in normalized:
        start = today - timedelta(days=30)
        return start, today, f"‘短期’按最近 30 个自然日（{start.isoformat()} 至 {today.isoformat()}）解析"
    if "中期" in normalized:
        start = _subtract_months(today, 6)
        return start, today, f"‘中期’按最近六个月（{start.isoformat()} 至 {today.isoformat()}）解析"
    if "长期" in normalized:
        start = _subtract_months(today, 12)
        return start, today, f"‘长期’按最近一年（{start.isoformat()} 至 {today.isoformat()}）解析"
    if "本周" in normalized:
        start = today - timedelta(days=today.weekday())
        return start, today, f"‘本周’按本周一至 T0（{start.isoformat()} 至 {today.isoformat()}）解析"
    if "上周" in normalized:
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end, f"‘上周’按自然周（{start.isoformat()} 至 {end.isoformat()}）解析"
    if "上月" in normalized:
        first_of_month = today.replace(day=1)
        end = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
        return start, end, f"‘上月’按自然月（{start.isoformat()} 至 {end.isoformat()}）解析"
    if "去年" in normalized:
        return (
            date(today.year - 1, 1, 1),
            date(today.year - 1, 12, 31),
            f"‘去年’按自然年（{today.year - 1}-01-01 至 {today.year - 1}-12-31）解析",
        )
    return None


def _normalise_date(value: str) -> str:
    year, month, day = (int(part) for part in value.split("-"))
    return date(year, month, day).isoformat()


def _subtract_months(value: date, months: int) -> date:
    year = value.year - (months // 12)
    month = value.month - (months % 12)
    if month <= 0:
        year -= 1
        month += 12
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if len(value) == 2 and value.endswith("十") and value[0] in digits:
        return digits[value[0]] * 10
    if len(value) == 2 and value.startswith("十") and value[1] in digits:
        return 10 + digits[value[1]]
    if len(value) == 3 and value[1] == "十" and value[0] in digits and value[2] in digits:
        return digits[value[0]] * 10 + digits[value[2]]
    return None
