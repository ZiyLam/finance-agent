"""Read-only market-data adapters exposed through the Agent tool protocol."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any

from .core import FunctionTool


def create_alltick_market_data_tool(client: "AllTickClient") -> FunctionTool:
    """Expose bounded AllTick quote and candle reads to a model provider."""

    from ..market_data.alltick import AllTickAssetClass, AllTickKlineType

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "latest_quotes")
        asset_class = AllTickAssetClass(str(arguments.get("asset_class", "stock")))

        if action == "latest_quotes":
            codes = arguments.get("codes")
            if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
                raise ValueError("'codes' must be a list of product-code strings")
            quotes = client.latest_quotes(codes, asset_class=asset_class)
            return json.dumps(
                {
                    "source": "AllTick",
                    "quotes": [
                        {
                            "code": quote.code,
                            "timestamp_ms": quote.timestamp_ms,
                            "price": str(quote.price),
                            "volume": str(quote.volume),
                            "turnover": str(quote.turnover),
                            "trade_direction": quote.trade_direction,
                        }
                        for quote in quotes
                    ],
                },
                ensure_ascii=False,
            )

        if action == "historical_candles":
            code = arguments.get("code")
            if not isinstance(code, str):
                raise ValueError("'code' must be a product-code string")
            candles = client.historical_candles(
                code,
                asset_class=asset_class,
                kline_type=AllTickKlineType(int(arguments.get("kline_type", 8))),
                count=int(arguments.get("count", 30)),
                timestamp_end=int(arguments.get("timestamp_end", 0)),
            )
            return json.dumps(
                {
                    "source": "AllTick",
                    "code": code,
                    "candles": [
                        {
                            "timestamp_seconds": candle.timestamp_seconds,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "volume": str(candle.volume),
                            "turnover": str(candle.turnover),
                        }
                        for candle in candles
                    ],
                },
                ensure_ascii=False,
            )

        raise ValueError("'action' must be 'latest_quotes' or 'historical_candles'")

    return FunctionTool(
        name="alltick_market_data",
        description=(
            "Reads AllTick latest quotes or historical candles. Inputs: action "
            "('latest_quotes' or 'historical_candles'), asset_class ('stock' or 'other'), "
            "and documented product codes. This tool never trades."
        ),
        handler=market_data,
    )


def create_alphavantage_market_data_tool(client: "AlphaVantageClient") -> FunctionTool:
    """Expose bounded Alpha Vantage reads to a model without exposing its API key."""

    from ..market_data.alphavantage import AlphaVantageError

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "daily_candles")
        if action == "daily_candles":
            symbol = arguments.get("symbol")
            if not isinstance(symbol, str):
                raise ValueError("'symbol' must be a global ticker string")
            limit = arguments.get("limit", 100)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
                raise ValueError("'limit' must be an integer between 1 and 100")
            try:
                candles = client.daily_candles(symbol)
            except AlphaVantageError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "Alpha Vantage",
                    "symbol": symbol,
                    "series": "TIME_SERIES_DAILY (raw, compact)",
                    "returned_rows": len(candles),
                    "shown_rows": min(len(candles), limit),
                    "candles": [
                        {
                            "date": candle.date,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "volume": str(candle.volume),
                        }
                        for candle in candles[-limit:]
                    ],
                },
                ensure_ascii=False,
            )
        if action == "global_quote":
            symbol = arguments.get("symbol")
            if not isinstance(symbol, str):
                raise ValueError("'symbol' must be a global ticker string")
            try:
                quote = client.global_quote(symbol)
            except AlphaVantageError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "Alpha Vantage",
                    "symbol": quote.symbol,
                    "latest_trading_day": quote.latest_trading_day,
                    "price": str(quote.price),
                    "change": str(quote.change),
                    "change_percent": str(quote.change_percent),
                    "open": str(quote.open_price),
                    "high": str(quote.high_price),
                    "low": str(quote.low_price),
                    "previous_close": str(quote.previous_close),
                    "volume": str(quote.volume),
                    "data_freshness": "end-of-day by default; real-time or delayed US data requires provider entitlement",
                },
                ensure_ascii=False,
            )
        if action == "symbol_search":
            keywords = arguments.get("keywords")
            if not isinstance(keywords, str):
                raise ValueError("'keywords' must be a search string")
            limit = arguments.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
                raise ValueError("'limit' must be an integer between 1 and 20")
            try:
                matches = client.symbol_search(keywords, limit)
            except AlphaVantageError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "Alpha Vantage",
                    "matches": [
                        {
                            "symbol": match.symbol,
                            "name": match.name,
                            "type": match.asset_type,
                            "region": match.region,
                            "currency": match.currency,
                            "match_score": str(match.match_score),
                        }
                        for match in matches
                    ],
                },
                ensure_ascii=False,
            )
        raise ValueError("'action' must be 'daily_candles', 'global_quote', or 'symbol_search'")

    return FunctionTool(
        name="alphavantage_market_data",
        description=(
            "Reads Alpha Vantage global stock data. Inputs: action ('daily_candles', 'global_quote', "
            "or 'symbol_search'), symbol or keywords, and optional limit. Daily candles are raw "
            "compact data (up to 100 rows); free quotes are normally end-of-day. Never trades."
        ),
        handler=market_data,
    )


def create_eodhd_market_data_tool(client: "EODHDClient") -> FunctionTool:
    """Expose bounded EODHD historical and ticker-search reads to a model."""

    from ..market_data.eodhd import EODHDError

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "historical_candles")
        if action == "historical_candles":
            symbol = arguments.get("symbol")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            if not all(isinstance(value, str) for value in (symbol, start_date, end_date)):
                raise ValueError("'symbol', 'start_date', and 'end_date' must be strings")
            period = arguments.get("period", "d")
            if not isinstance(period, str):
                raise ValueError("'period' must be a string")
            limit = arguments.get("limit", 120)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
                raise ValueError("'limit' must be an integer between 1 and 120")
            try:
                candles = client.historical_candles(
                    symbol, start_date=start_date, end_date=end_date, period=period
                )
            except EODHDError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "EOD Historical Data (EODHD)",
                    "symbol": symbol,
                    "period": period,
                    "start_date": start_date,
                    "end_date": end_date,
                    "returned_rows": len(candles),
                    "shown_rows": min(len(candles), limit),
                    "candles": [
                        {
                            "date": candle.date,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "adjusted_close": str(candle.adjusted_close)
                            if candle.adjusted_close is not None
                            else None,
                            "volume": str(candle.volume) if candle.volume is not None else None,
                        }
                        for candle in candles[-limit:]
                    ],
                },
                ensure_ascii=False,
            )
        if action == "search":
            query = arguments.get("query")
            if not isinstance(query, str):
                raise ValueError("'query' must be a ticker or company-name search string")
            limit = arguments.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
                raise ValueError("'limit' must be an integer between 1 and 20")
            try:
                matches = client.search(query, limit)
            except EODHDError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "EOD Historical Data (EODHD)",
                    "matches": [
                        {
                            "symbol": match.symbol,
                            "code": match.code,
                            "exchange": match.exchange,
                            "name": match.name,
                            "type": match.asset_type,
                            "country": match.country,
                            "currency": match.currency,
                        }
                        for match in matches
                    ],
                },
                ensure_ascii=False,
            )
        raise ValueError("'action' must be 'historical_candles' or 'search'")

    return FunctionTool(
        name="eodhd_market_data",
        description=(
            "Reads EODHD end-of-day historical OHLCV or active-instrument search results. Inputs: "
            "action ('historical_candles' or 'search'); EODHD symbol such as AAPL.US; date range "
            "(YYYY-MM-DD); period ('d', 'w', 'm'); or query and optional limit. Never trades."
        ),
        handler=market_data,
    )


def create_biying_market_data_tool(client: "BiyingClient") -> FunctionTool:
    """Expose bounded 必盈 A-share reads without exposing the certificate."""

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "realtime_quote")
        if action == "realtime_quote":
            code = arguments.get("code")
            if not isinstance(code, str):
                raise ValueError("'code' must be a six-digit A-share code")
            quote = client.realtime_quote(code)
            return json.dumps(
                {
                    "source": "必盈 API",
                    "code": quote.code,
                    "updated_at": quote.updated_at,
                    "price": str(quote.price),
                    "change_percent": str(quote.change_percent) if quote.change_percent is not None else None,
                    "open": str(quote.open_price) if quote.open_price is not None else None,
                    "high": str(quote.high_price) if quote.high_price is not None else None,
                    "low": str(quote.low_price) if quote.low_price is not None else None,
                    "volume_lots": str(quote.volume_lots) if quote.volume_lots is not None else None,
                    "turnover": str(quote.turnover) if quote.turnover is not None else None,
                    "dynamic_pe": str(quote.dynamic_pe) if quote.dynamic_pe is not None else None,
                    "pb": str(quote.pb) if quote.pb is not None else None,
                },
                ensure_ascii=False,
            )
        if action == "find_stocks":
            query = arguments.get("query")
            if not isinstance(query, str):
                raise ValueError("'query' must be a stock code or Chinese stock-name fragment")
            stocks = client.find_stocks(query, int(arguments.get("limit", 10)))
            return json.dumps(
                {
                    "source": "必盈 API",
                    "matches": [
                        {"code": stock.code, "name": stock.name, "exchange": stock.exchange}
                        for stock in stocks
                    ],
                },
                ensure_ascii=False,
            )
        raise ValueError("'action' must be 'realtime_quote' or 'find_stocks'")

    return FunctionTool(
        name="biying_market_data",
        description=(
            "Reads documented 必盈 API沪深 A 股 code lookups or public real-time quotes. "
            "Inputs: action ('find_stocks' or 'realtime_quote') and query/code. Never trades."
        ),
        handler=market_data,
    )


def create_eastmoney_security_search_tool(client: "EastmoneySecuritySearchClient") -> FunctionTool:
    """Expose a bounded token-free Chinese A-share name search."""

    from ..market_data.eastmoney import EastmoneySearchError

    def search(arguments: Mapping[str, Any]) -> str:
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        if not isinstance(query, str) or not isinstance(limit, int):
            raise ValueError("'query' must be text and 'limit' must be an integer")
        try:
            matches = client.search(query, limit)
        except EastmoneySearchError as error:
            return f"ERROR: {error}"
        return json.dumps(
            {
                "source": "Eastmoney A-share security search",
                "matches": [{"code": item.code, "name": item.name, "exchange": item.exchange} for item in matches],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        name="eastmoney_security_search",
        description="Searches Chinese A-share names or codes and returns bounded exchange-labelled matches. Never trades.",
        handler=search,
    )


def create_eastmoney_market_scan_tool(client: "EastmoneySecuritySearchClient") -> FunctionTool:
    """Expose a bounded all-A-share industry performance scan to the Agent."""

    from ..market_data.eastmoney import EastmoneySearchError

    def scan(arguments: Mapping[str, Any]) -> str:
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int):
            raise ValueError("'limit' must be an integer")
        try:
            # Both rankings are independent reads. Running them together caps
            # the normal path near one provider timeout instead of two.
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="eastmoney-sector") as executor:
                leaders_future = executor.submit(client.leading_industries, limit)
                laggards_future = executor.submit(client.leading_industries, limit, descending=False)
                leaders = leaders_future.result()
                laggards = laggards_future.result()
        except EastmoneySearchError as error:
            return f"ERROR: {error}"
        leader_average = sum(item.change_percent for item in leaders) / len(leaders) if leaders else 0.0
        laggard_average = sum(item.change_percent for item in laggards) / len(laggards) if laggards else 0.0
        sentiment = (
            "普遍偏强" if laggard_average >= 0 else "结构性分化" if leader_average > 0 else "整体偏弱"
        )
        return json.dumps(
            {
                "source": "Eastmoney A-share industry ranking",
                "freshness": "current_or_delayed",
                "market_sentiment": {
                    "label": sentiment,
                    "leader_average_change_percent": round(leader_average, 2),
                    "laggard_average_change_percent": round(laggard_average, 2),
                    "basis": "Top and bottom sampled A-share industry change percentages; not a full-market breadth or investor-position measure.",
                },
                "leading_industries": [{"code": item.code, "name": item.name, "change_percent": item.change_percent, "main_net_inflow": item.main_net_inflow} for item in leaders],
                "lagging_industries": [{"code": item.code, "name": item.name, "change_percent": item.change_percent, "main_net_inflow": item.main_net_inflow} for item in laggards],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        name="eastmoney_market_scan",
        description="Returns current or delayed A-share leading and lagging industry samples plus a disclosed, sample-based market-sentiment assessment. Never trades.",
        handler=scan,
    )

def create_aktools_market_data_tool(client: "AkToolsClient") -> FunctionTool:
    """Expose a bounded, read-only A-share K-line query backed by AkTools."""

    from ..market_data.aktools import AkToolsError

    def market_data(arguments: Mapping[str, Any]) -> str:
        symbol = arguments.get("symbol")
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        if not all(isinstance(value, str) for value in (symbol, start_date, end_date)):
            raise ValueError("'symbol', 'start_date', and 'end_date' must be strings")
        period = arguments.get("period", "daily")
        adjust = arguments.get("adjust", "")
        if not isinstance(period, str) or not isinstance(adjust, str):
            raise ValueError("'period' and 'adjust' must be strings")
        limit = arguments.get("limit", 120)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
            raise ValueError("'limit' must be an integer between 1 and 120")
        try:
            candles = client.stock_zh_a_hist(
                symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        except AkToolsError as error:
            return f"ERROR: {error}"
        return json.dumps(
            {
                "source": "AkTools (local AKShare service)",
                "symbol": symbol,
                "period": period,
                "adjust": adjust or "none",
                "returned_rows": len(candles),
                "shown_rows": min(len(candles), limit),
                "candles": [
                    {
                        "date": candle.date,
                        "open": str(candle.open_price),
                        "close": str(candle.close_price),
                        "high": str(candle.high_price),
                        "low": str(candle.low_price),
                        "volume": str(candle.volume) if candle.volume is not None else None,
                        "turnover": str(candle.turnover) if candle.turnover is not None else None,
                        "amplitude_percent": str(candle.amplitude_percent)
                        if candle.amplitude_percent is not None
                        else None,
                        "change_percent": str(candle.change_percent)
                        if candle.change_percent is not None
                        else None,
                        "change_amount": str(candle.change_amount)
                        if candle.change_amount is not None
                        else None,
                        "turnover_rate_percent": str(candle.turnover_rate_percent)
                        if candle.turnover_rate_percent is not None
                        else None,
                    }
                    for candle in candles[-limit:]
                ],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        name="aktools_market_data",
        description=(
            "Reads A-share historical K lines from an operator-started local AkTools service. "
            "Inputs: symbol (six digits), start_date/end_date (YYYYMMDD), period "
            "('daily', 'weekly', 'monthly'), adjust ('', 'qfq', 'hfq'), and optional limit "
            "(1-120). The tool never trades and does not require an API token."
        ),
        handler=market_data,
    )


def create_baostock_market_data_tool(client: "BaoStockClient") -> FunctionTool:
    """Expose bounded historical A-share K-line reads from BaoStock."""

    from ..market_data.baostock import BaoStockError

    def market_data(arguments: Mapping[str, Any]) -> str:
        code = arguments.get("code")
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        if not all(isinstance(value, str) for value in (code, start_date, end_date)):
            raise ValueError("'code', 'start_date', and 'end_date' must be strings")
        frequency = arguments.get("frequency", "d")
        adjustflag = arguments.get("adjustflag", "3")
        if not isinstance(frequency, str) or not isinstance(adjustflag, str):
            raise ValueError("'frequency' and 'adjustflag' must be strings")
        limit = arguments.get("limit", 120)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
            raise ValueError("'limit' must be an integer between 1 and 120")
        try:
            candles = client.historical_candles(
                code,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjustflag,
            )
        except BaoStockError as error:
            return f"ERROR: {error}"
        return json.dumps(
            {
                "source": "BaoStock",
                "code": code,
                "frequency": frequency,
                "adjustflag": adjustflag,
                "returned_rows": len(candles),
                "shown_rows": min(len(candles), limit),
                "candles": [
                    {
                        "date": candle.date,
                        "code": candle.code,
                        "open": str(candle.open_price),
                        "close": str(candle.close_price),
                        "high": str(candle.high_price),
                        "low": str(candle.low_price),
                        "previous_close": str(candle.previous_close)
                        if candle.previous_close is not None
                        else None,
                        "volume": str(candle.volume) if candle.volume is not None else None,
                        "amount": str(candle.amount) if candle.amount is not None else None,
                        "turnover_rate_percent": str(candle.turnover_rate_percent)
                        if candle.turnover_rate_percent is not None
                        else None,
                        "change_percent": str(candle.change_percent)
                        if candle.change_percent is not None
                        else None,
                        "trade_status": candle.trade_status,
                        "is_st": candle.is_st,
                    }
                    for candle in candles[-limit:]
                ],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        name="baostock_market_data",
        description=(
            "Reads BaoStock historical A-share K lines. Inputs: code such as 'sh.600000', "
            "start_date/end_date (YYYY-MM-DD), frequency ('d', 'w', 'm'), adjustflag "
            "('1' post-adjusted, '2' pre-adjusted, '3' unadjusted), and optional limit (1-120). "
            "Uses an anonymous read-only BaoStock session and never trades."
        ),
        handler=market_data,
    )


def create_tickflow_market_data_tool(client: "TickFlowClient") -> FunctionTool:
    """Expose bounded TickFlow quotes and daily OHLCV without exposing its API key."""

    from ..market_data.tickflow import TickFlowError

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "historical_candles")
        if action == "quote":
            symbols = arguments.get("symbols")
            if not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols):
                raise ValueError("'symbols' must be a list of TickFlow symbols")
            try:
                quotes = client.quotes(symbols)
            except TickFlowError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "TickFlow",
                    "quotes": [
                        {
                            "symbol": quote.symbol,
                            "timestamp_ms": quote.timestamp_ms,
                            "price": str(quote.last_price),
                            "previous_close": str(quote.previous_close)
                            if quote.previous_close is not None
                            else None,
                            "open": str(quote.open_price) if quote.open_price is not None else None,
                            "high": str(quote.high_price) if quote.high_price is not None else None,
                            "low": str(quote.low_price) if quote.low_price is not None else None,
                            "volume": str(quote.volume) if quote.volume is not None else None,
                            "amount": str(quote.amount) if quote.amount is not None else None,
                            "change_percent": str(quote.change_percent)
                            if quote.change_percent is not None
                            else None,
                        }
                        for quote in quotes
                    ],
                },
                ensure_ascii=False,
            )
        if action == "historical_candles":
            symbol = arguments.get("symbol")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            if not all(isinstance(value, str) for value in (symbol, start_date, end_date)):
                raise ValueError("'symbol', 'start_date', and 'end_date' must be strings")
            limit = arguments.get("limit", 120)
            adjust = arguments.get("adjust", "none")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
                raise ValueError("'limit' must be an integer between 1 and 120")
            if not isinstance(adjust, str):
                raise ValueError("'adjust' must be a string")
            try:
                candles = client.daily_candles(
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    adjust=adjust,
                )
            except TickFlowError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "TickFlow",
                    "symbol": symbol,
                    "period": "1d",
                    "start_date": start_date,
                    "end_date": end_date,
                    "adjust": adjust,
                    "returned_rows": len(candles),
                    "shown_rows": len(candles),
                    "candles": [
                        {
                            "date": candle.date,
                            "timestamp_ms": candle.timestamp_ms,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "volume": str(candle.volume) if candle.volume is not None else None,
                            "amount": str(candle.amount) if candle.amount is not None else None,
                        }
                        for candle in candles
                    ],
                },
                ensure_ascii=False,
            )
        raise ValueError("'action' must be 'quote' or 'historical_candles'")

    return FunctionTool(
        name="tickflow_market_data",
        description=(
            "Reads TickFlow real-time quotes or date-bounded daily OHLCV. Inputs: action ('quote' or "
            "'historical_candles'); TickFlow symbols such as 600000.SH, 0005.HK, or AAPL.US; and, for "
            "history, start_date/end_date (YYYY-MM-DD), adjustment, and limit (1-120). Never trades."
        ),
        handler=market_data,
    )


def create_zhitu_market_data_tool(client: "ZhituClient") -> FunctionTool:
    """Expose documented 智兔数服 A-share and index reads to the Agent."""

    from ..market_data.zhitu import ZhituError

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "index_history")
        if action in {"index_history", "stock_history"}:
            symbol = arguments.get("symbol")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            if not all(isinstance(value, str) for value in (symbol, start_date, end_date)):
                raise ValueError("'symbol', 'start_date', and 'end_date' must be strings")
            limit = arguments.get("limit", 120)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
                raise ValueError("'limit' must be an integer between 1 and 120")
            try:
                candles = (
                    client.index_daily_candles(
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                        limit=limit,
                    )
                    if action == "index_history"
                    else client.stock_daily_candles(
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                        limit=limit,
                    )
                )
            except ZhituError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "智兔数服",
                    "symbol": symbol,
                    "period": "1d",
                    "start_date": start_date,
                    "end_date": end_date,
                    "returned_rows": len(candles),
                    "shown_rows": len(candles),
                    "candles": [
                        {
                            "date": candle.date,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "previous_close": str(candle.previous_close)
                            if candle.previous_close is not None
                            else None,
                            "volume": str(candle.volume) if candle.volume is not None else None,
                            "amount": str(candle.amount) if candle.amount is not None else None,
                        }
                        for candle in candles
                    ],
                },
                ensure_ascii=False,
            )
        if action in {"index_quote", "stock_quote"}:
            symbol = arguments.get("symbol")
            if not isinstance(symbol, str):
                raise ValueError("'symbol' must be a string")
            try:
                quote = client.index_quote(symbol) if action == "index_quote" else client.stock_quote(symbol)
            except ZhituError as error:
                return f"ERROR: {error}"
            return json.dumps(
                {
                    "source": "智兔数服",
                    "quotes": [
                        {
                            "symbol": quote.symbol,
                            "timestamp": quote.timestamp,
                            "price": str(quote.last_price),
                            "previous_close": str(quote.previous_close)
                            if quote.previous_close is not None
                            else None,
                            "open": str(quote.open_price) if quote.open_price is not None else None,
                            "high": str(quote.high_price) if quote.high_price is not None else None,
                            "low": str(quote.low_price) if quote.low_price is not None else None,
                            "volume": str(quote.volume) if quote.volume is not None else None,
                            "amount": str(quote.amount) if quote.amount is not None else None,
                            "change": str(quote.change) if quote.change is not None else None,
                            "change_percent": str(quote.change_percent)
                            if quote.change_percent is not None
                            else None,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        raise ValueError("'action' must be 'index_history', 'stock_history', 'index_quote', or 'stock_quote'")

    return FunctionTool(
        name="zhitu_market_data",
        description=(
            "Reads documented 智兔数服 A-share or 沪深指数 real-time quotes and bounded daily history. "
            "Inputs: action ('index_history', 'stock_history', 'index_quote', or 'stock_quote'), symbol "
            "such as 000905.SH, and for history start_date/end_date (YYYY-MM-DD) with limit (1-120). "
            "Never trades."
        ),
        handler=market_data,
    )


def create_yfinance_market_data_tool(client: "YFinanceClient") -> FunctionTool:
    """Expose bounded Yahoo Finance historical OHLCV reads to a model."""

    from ..market_data.yfinance import YFinanceError

    def market_data(arguments: Mapping[str, Any]) -> str:
        symbol = arguments.get("symbol")
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        if not all(isinstance(value, str) for value in (symbol, start_date, end_date)):
            raise ValueError("'symbol', 'start_date', and 'end_date' must be strings")
        interval = arguments.get("interval", "1d")
        auto_adjust = arguments.get("auto_adjust", True)
        if not isinstance(interval, str):
            raise ValueError("'interval' must be a string")
        if not isinstance(auto_adjust, bool):
            raise ValueError("'auto_adjust' must be a boolean")
        limit = arguments.get("limit", 120)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 120:
            raise ValueError("'limit' must be an integer between 1 and 120")
        try:
            candles = client.historical_candles(
                symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                auto_adjust=auto_adjust,
            )
        except YFinanceError as error:
            return f"ERROR: {error}"
        return json.dumps(
            {
                "source": "yfinance (Yahoo Finance)",
                "symbol": symbol,
                "interval": interval,
                "auto_adjust": auto_adjust,
                "end_date_exclusive": end_date,
                "returned_rows": len(candles),
                "shown_rows": min(len(candles), limit),
                "candles": [
                    {
                        "date": candle.date,
                        "open": str(candle.open_price),
                        "close": str(candle.close_price),
                        "high": str(candle.high_price),
                        "low": str(candle.low_price),
                        "adjusted_close": str(candle.adjusted_close)
                        if candle.adjusted_close is not None
                        else None,
                        "volume": str(candle.volume) if candle.volume is not None else None,
                    }
                    for candle in candles[-limit:]
                ],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        name="yfinance_market_data",
        description=(
            "Reads Yahoo Finance historical OHLCV through yfinance for one Yahoo symbol, such as "
            "AAPL, 0700.HK, 600000.SS, ^GSPC, or BTC-USD. Inputs: symbol, start_date/end_date "
            "(YYYY-MM-DD; end is exclusive), interval ('1d', '1wk', '1mo'), auto_adjust, and "
            "optional limit (1-120). Personal research use only; never trades."
        ),
        handler=market_data,
    )
