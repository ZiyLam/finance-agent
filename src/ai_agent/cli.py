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
    create_baostock_market_data_tool,
    create_biying_market_data_tool,
    create_echo_tool,
    create_yfinance_market_data_tool,
)


_TOKEN_SOURCES = {
    "alltick": "ALLTICK_API_TOKEN",
    "biying": "BIYING_API_LICENCE",
}

_LOCAL_SOURCES = {
    "aktools": "AKTOOLS_BASE_URL",
    "baostock": None,
    "yfinance": None,
}


def _print_source_help(output: Callable[[str], None]) -> None:
    output("Usage: ai-agent source {status|check|set-token|delete-token} [alltick|biying|aktools|baostock|yfinance]")
    output("  status                 Show source configuration; never prints tokens or URLs.")
    output("  check aktools          Show the current version reported by the running AkTools service.")
    output("  set-token <source>     Prompt securely for an AllTick or 必盈 API credential.")
    output("  delete-token <source>  Remove a saved AllTick or 必盈 credential after confirmation.")
    output("  aktools                Needs no token; configure its local URL with AKTOOLS_BASE_URL.")
    output("  baostock               Needs no token; local requests stay below its 50,000/IP/day provider limit.")
    output("  yfinance               Needs no token; Yahoo Finance data is limited to personal research use.")


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
        selected = sources or [*list(_TOKEN_SOURCES), *list(_LOCAL_SOURCES)]
        for source in selected:
            environment_variable = _TOKEN_SOURCES.get(source)
            if environment_variable is None and source not in _LOCAL_SOURCES:
                output(f"Unknown source: {source}")
                return 2
            if source in _LOCAL_SOURCES:
                configuration_variable = _LOCAL_SOURCES[source]
                if configuration_variable:
                    origin = "environment variable" if getenv(configuration_variable) else "default local address"
                    output(f"{source}: no token required; base URL from {origin} (checked on demand)")
                else:
                    if source == "baostock":
                        output(
                            "baostock: no token required; anonymous sessions use a local 5,000 requests/day guard"
                        )
                    else:
                        output("yfinance: no token required; local 1,000 requests/day guard for personal research")
                continue
            try:
                token = resolve_token(source, environment_variable, store)
            except SecretStoreError:
                output(f"{source}: saved token cannot be read; delete and set it again.")
                return 1
            if token:
                origin = "environment variable" if token == getenv(environment_variable) else "secure local store"
                output(f"{source}: configured via {origin}")
            else:
                output(f"{source}: not configured")
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
            "Run 'ai-agent source delete-token alltick' then set it again."
        ) from error
    if alltick_token:
        from .market_data.alltick import AllTickClient

        registered_tools.append(create_alltick_market_data_tool(AllTickClient(alltick_token)))
    try:
        biying_licence = resolve_token("biying", "BIYING_API_LICENCE")
    except SecretStoreError as error:
        raise SystemExit(
            "Could not read the saved 必盈 API certificate. "
            "Run 'ai-agent source delete-token biying' then set it again."
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
    print(f"AI Agent framework ready ({len(skills)} skills loaded). Type 'exit' to quit.")
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
