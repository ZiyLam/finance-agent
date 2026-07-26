"""Minimal local entry point used to prove the composition layer."""

from __future__ import annotations

from getpass import getpass
from os import getenv
from pathlib import Path
import sys
from typing import Any, Callable, Sequence

from .agent import Agent
from .config import AgentSettings
from .memory import ConversationMemory
from .providers.echo import EchoModelClient
from .secrets import SecretStoreError, TokenStore, resolve_token
from .skills import compose_system_prompt, load_skills
from .tools import (
    ToolRegistry,
    create_aktools_market_data_tool,
    create_alltick_market_data_tool,
    create_alphavantage_market_data_tool,
    create_baostock_market_data_tool,
    create_biying_market_data_tool,
    create_eodhd_market_data_tool,
    create_echo_tool,
    create_yfinance_market_data_tool,
)


_TOKEN_SOURCES = {
    "alltick": "ALLTICK_API_TOKEN",
    "alphavantage": "ALPHAVANTAGE_API_KEY",
    "biying": "BIYING_API_LICENCE",
    "eodhd": "EODHD_API_TOKEN",
    # The following adapters currently have no provider token requirement, but
    # retain a source-specific maintenance slot for future provider changes or
    # for the operator's own credential backup.
    "aktools": "AKTOOLS_API_TOKEN",
    "baostock": "BAOSTOCK_API_TOKEN",
    "yfinance": "YFINANCE_API_TOKEN",
}

_LOCAL_SOURCES = {
    "aktools": "AKTOOLS_BASE_URL",
    "baostock": None,
    "yfinance": None,
}


def _print_source_help(output: Callable[[str], None]) -> None:
    output("Usage: finance-agent source {status|check|set-token|delete-token} [alltick|alphavantage|biying|eodhd|aktools|baostock|yfinance]")
    output("  status                 Show source configuration; never prints tokens or URLs.")
    output("  check aktools          Show the current version reported by the running AkTools service.")
    output("  set-token <source>     Prompt securely for a credential or token backup for any source.")
    output("  delete-token <source>  Remove a saved data-source credential after confirmation.")
    output("  alphavantage           Free keys are locally guarded at 25 requests/day and 15-second spacing.")
    output("  eodhd                  Free keys are locally guarded at 20 requests/day and 3-second spacing.")
    output("  aktools                Has an optional credential-maintenance slot; configure URL with AKTOOLS_BASE_URL.")
    output("  baostock               Has an optional credential-maintenance slot; anonymous requests stay below 50,000/IP/day.")
    output("  yfinance               Has an optional credential-maintenance slot; Yahoo Finance data is personal-research only.")


def run_source_command(
    arguments: Sequence[str],
    *,
    store: TokenStore | None = None,
    secret_input: Callable[[str], str] = getpass,
    confirmation_input: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    aktools_client_factory: Callable[[], Any] | None = None,
) -> int:
    """Maintain local source tokens without ever echoing their values."""

    if not arguments or arguments[0] in {"help", "--help", "-h"}:
        _print_source_help(output)
        return 0

    command, *sources = arguments
    if command == "status":
        selected = sources or list(_TOKEN_SOURCES)
        for source in selected:
            environment_variable = _TOKEN_SOURCES.get(source)
            if environment_variable is None:
                output(f"Unknown source: {source}")
                return 2
            try:
                token = resolve_token(source, environment_variable, store)
            except SecretStoreError:
                output(f"{source}: saved token cannot be read; delete and set it again.")
                return 1
            token_status = (
                f"configured via {'environment variable' if token == getenv(environment_variable) else 'secure local store'}"
                if token
                else "not configured"
            )
            if source in _LOCAL_SOURCES:
                configuration_variable = _LOCAL_SOURCES[source]
                if configuration_variable:
                    origin = "environment variable" if getenv(configuration_variable) else "default local address"
                    output(
                        f"{source}: base URL from {origin} (checked on demand); "
                        f"optional token {token_status} (not used by current adapter)"
                    )
                else:
                    if source == "baostock":
                        output(
                            "baostock: anonymous sessions use a local 5,000 requests/day guard; "
                            f"optional token {token_status} (not used by current adapter)"
                        )
                    else:
                        output(
                            "yfinance: local 1,000 requests/day guard for personal research; "
                            f"optional token {token_status} (not used by current adapter)"
                        )
                continue
            output(f"{source}: {token_status}")
        return 0

    if command == "check":
        if sources != ["aktools"]:
            _print_source_help(output)
            return 2
        from .market_data.aktools import AkToolsClient, AkToolsError

        if aktools_client_factory is None:
            aktools_client_factory = AkToolsClient.from_environment
        try:
            version_report = aktools_client_factory().service_version()
        except (AkToolsError, ValueError) as error:
            output(f"aktools: version check failed: {error}")
            return 1
        output(f"aktools: local service version {version_report.aktools_current}")
        return 0

    if len(sources) != 1 or sources[0] not in _TOKEN_SOURCES:
        _print_source_help(output)
        return 2
    source = sources[0]
    active_store = store or TokenStore()

    if command == "set-token":
        token = secret_input(f"{source} API token (input hidden): ")
        try:
            active_store.set_token(source, token)
        except (ValueError, SecretStoreError) as error:
            output(f"Could not save {source} token: {error}")
            return 1
        output(f"{source}: token saved in the current user's encrypted local store")
        return 0

    if command == "delete-token":
        confirmed = confirmation_input(f"Type '{source}' to delete its saved token: ")
        if confirmed.strip().lower() != source:
            output("Deletion cancelled")
            return 1
        try:
            deleted = active_store.delete_token(source)
        except SecretStoreError as error:
            output(f"Could not delete {source} token: {error}")
            return 1
        output(f"{source}: {'saved token deleted' if deleted else 'no saved token found'}")
        return 0

    _print_source_help(output)
    return 2


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] == "source":
            exit_code = run_source_command(arguments[1:])
            if exit_code:
                raise SystemExit(exit_code)
            return
        _print_source_help(print)
        raise SystemExit(2)

    settings = AgentSettings.from_environment()
    if settings.provider != "echo":
        raise SystemExit(
            f"Provider '{settings.provider}' is not configured yet. "
            "Add an adapter under ai_agent.providers first."
        )

    project_root = Path(__file__).resolve().parents[2]
    skills = load_skills(project_root / "skills")
    system_prompt = compose_system_prompt(settings.system_prompt, skills)
    registered_tools = [create_echo_tool()]
    try:
        alltick_token = resolve_token("alltick", "ALLTICK_API_TOKEN")
    except SecretStoreError as error:
        raise SystemExit(
            "Could not read the saved AllTick token. "
            "Run 'finance-agent source delete-token alltick' then set it again."
        ) from error
    if alltick_token:
        from .market_data.alltick import AllTickClient

        registered_tools.append(create_alltick_market_data_tool(AllTickClient(alltick_token)))
    try:
        alphavantage_key = resolve_token("alphavantage", "ALPHAVANTAGE_API_KEY")
    except SecretStoreError as error:
        raise SystemExit(
            "Could not read the saved Alpha Vantage API key. "
            "Run 'finance-agent source delete-token alphavantage' then set it again."
        ) from error
    if alphavantage_key:
        from .market_data.alphavantage import AlphaVantageClient

        registered_tools.append(create_alphavantage_market_data_tool(AlphaVantageClient(alphavantage_key)))
    try:
        eodhd_token = resolve_token("eodhd", "EODHD_API_TOKEN")
    except SecretStoreError as error:
        raise SystemExit(
            "Could not read the saved EODHD API token. "
            "Run 'finance-agent source delete-token eodhd' then set it again."
        ) from error
    if eodhd_token:
        from .market_data.eodhd import EODHDClient

        registered_tools.append(create_eodhd_market_data_tool(EODHDClient(eodhd_token)))
    try:
        biying_licence = resolve_token("biying", "BIYING_API_LICENCE")
    except SecretStoreError as error:
        raise SystemExit(
            "Could not read the saved 必盈 API certificate. "
            "Run 'finance-agent source delete-token biying' then set it again."
        ) from error
    if biying_licence:
        from .market_data.biying import BiyingClient

        registered_tools.append(create_biying_market_data_tool(BiyingClient(biying_licence)))
    from .market_data.aktools import AkToolsClient
    from .market_data.baostock import BaoStockClient
    from .market_data.yfinance import YFinanceClient

    # Construction does not call the network. The tool reports a clear error if
    # the optional locally managed service is not running when it is invoked.
    registered_tools.append(create_aktools_market_data_tool(AkToolsClient.from_environment()))
    registered_tools.append(create_baostock_market_data_tool(BaoStockClient()))
    registered_tools.append(create_yfinance_market_data_tool(YFinanceClient()))
    agent = Agent(
        model=EchoModelClient(),
        memory=ConversationMemory(system_prompt, settings.memory_window),
        tools=ToolRegistry(tuple(registered_tools)),
    )
    print(f"Finance Agent ready ({len(skills)} skills loaded). Type 'exit' to quit.")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if user_input.lower() in {"exit", "quit"}:
            return
        if user_input:
            print(agent.run(user_input).text)


if __name__ == "__main__":
    main()
