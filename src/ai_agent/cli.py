"""Minimal local entry point used to prove the composition layer."""

from __future__ import annotations

import json
import sys
from getpass import getpass
from os import getenv
from pathlib import Path
from typing import Any, Callable, Sequence

from .analysis_execution import SecurityAnalysisExecutor
from .analysis_tags import AnalysisScenario, Market
from .config import AgentSettings
from .data_sources import data_source_names, get_data_source, ordered_data_sources
from .langchain.agent import Agent
from .langchain.memory import ConversationMemory
from .provider_activation import ProviderActivationStore
from .providers.codex_cli import CodexCliError, CodexCliModelClient
from .providers.echo import EchoModelClient
from .providers.qianfan import QianfanError, QianfanModelClient
from .research_planning import (
    SecurityAnalysisRequest,
    build_security_analysis_plan,
    catalog_snapshot,
)
from .research_report import SecurityResearchReportBuilder
from .runtime import build_market_data_tool_registry
from .secrets import SecretStoreError, TokenStore, resolve_token
from .skills import compose_system_prompt, load_skills
from .tools import (
    ToolRegistry,
)


def _print_source_help(output: Callable[[str], None]) -> None:
    names = "|".join(data_source_names())
    output(f"Usage: finance-agent source {{list|status|check|set-token|delete-token}} [{names}]")
    output("  list                   List all catalogued source-maintenance entries; never prints tokens.")
    output("  status                 Show source configuration; never prints tokens or URLs.")
    output("  check aktools          Show the current version reported by the running AkTools service.")
    output("  set-token <source>     Prompt securely for a credential or token backup for any source.")
    output("  delete-token <source>  Remove a saved data-source credential after confirmation.")


def _print_route_help(output: Callable[[str], None]) -> None:
    output("Usage: finance-agent route {catalog|scenarios|plan}")
    output("  catalog                                List data-source and model capability tags.")
    output("  scenarios                              List supported deterministic research scenarios.")
    output("  plan <scenario> <market> <symbol> [provider] [start_date end_date]")
    output("                                         Build a read-only security-analysis plan as JSON.")


def _print_analyze_help(output: Callable[[str], None]) -> None:
    output("Usage: finance-agent analyze <scenario> <market> <symbol> [start_date end_date]")
    output("  Execute a read-only plan with configured local data tools and return evidence JSON.")


def _print_report_help(output: Callable[[str], None]) -> None:
    output("Usage: finance-agent report <market> <symbol> <start_date> <end_date>")
    output("  Create a read-only report after a two-source historical cross-check, as JSON and Markdown.")


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
    if command == "list":
        if sources:
            _print_source_help(output)
            return 2
        for definition in ordered_data_sources():
            usage = "required by current adapter" if definition.token_required_by_adapter else "maintenance only"
            tags = ",".join(sorted(tag.value for tag in definition.tags)) or "none"
            output(
                f"{definition.name}: {definition.display_name}; "
                f"credential slot {usage} ({definition.token_environment_variable}); tags [{tags}]"
                f"; routing priority {definition.routing_priority}; latency class {definition.latency_class.value}"
            )
        return 0

    if command == "status":
        selected = sources or list(data_source_names())
        for source in selected:
            definition = get_data_source(source)
            if definition is None:
                output(f"Unknown source: {source}")
                return 2
            try:
                token = resolve_token(definition.name, definition.token_environment_variable, store)
            except SecretStoreError:
                output(f"{definition.name}: saved token cannot be read; delete and set it again.")
                return 1
            token_status = (
                f"configured via {'environment variable' if token == getenv(definition.token_environment_variable) else 'secure local store'}"
                if token
                else "not configured"
            )
            if not definition.token_required_by_adapter:
                if definition.base_url_environment_variable:
                    configuration_variable = definition.base_url_environment_variable
                    origin = "environment variable" if getenv(configuration_variable) else "default local address"
                    output(
                        f"{definition.name}: base URL from {origin} (checked on demand); "
                        f"optional token {token_status} (not used by current adapter)"
                    )
                else:
                    output(
                        f"{definition.name}: {definition.status_description}; "
                        f"optional token {token_status} (not used by current adapter)"
                    )
                continue
            output(f"{definition.name}: {token_status}")
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

    if len(sources) != 1 or (definition := get_data_source(sources[0])) is None:
        _print_source_help(output)
        return 2
    source = definition.name
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


def run_route_command(
    arguments: Sequence[str],
    *,
    output: Callable[[str], None] = print,
) -> int:
    """Inspect deterministic research routes without reading credentials or using the network."""

    if not arguments or arguments[0] in {"help", "--help", "-h"}:
        _print_route_help(output)
        return 0
    command, *values = arguments
    if command == "catalog" and not values:
        output(json.dumps(catalog_snapshot(), ensure_ascii=False, indent=2))
        return 0
    if command == "scenarios" and not values:
        output(json.dumps({"scenarios": catalog_snapshot()["scenarios"]}, ensure_ascii=False, indent=2))
        return 0
    if command != "plan" or len(values) not in {3, 4, 6}:
        _print_route_help(output)
        return 2
    scenario_text, market_text, symbol, *options = values
    provider = "codex"
    dates: list[str] = []
    if len(options) == 1:
        provider = options[0]
    elif len(options) == 3:
        provider, *dates = options
    try:
        request = SecurityAnalysisRequest(
            symbol=symbol,
            market=Market(market_text),
            scenario=AnalysisScenario(scenario_text),
            start_date=dates[0] if dates else None,
            end_date=dates[1] if dates else None,
        )
        plan = build_security_analysis_plan(request, provider=provider)
    except ValueError as error:
        output(f"Could not build route: {error}")
        return 2
    except RuntimeError as error:
        output(f"Could not build route: {error}")
        return 1
    output(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    return 0


def run_analyze_command(
    arguments: Sequence[str],
    *,
    tools: ToolRegistry,
    output: Callable[[str], None] = print,
) -> int:
    """Execute a bounded security-analysis plan without calling an LLM or trading endpoint."""

    if not arguments or arguments[0] in {"help", "--help", "-h"}:
        _print_analyze_help(output)
        return 0
    if len(arguments) not in {3, 5}:
        _print_analyze_help(output)
        return 2
    scenario_text, market_text, symbol, *dates = arguments
    try:
        request = SecurityAnalysisRequest(
            symbol=symbol,
            market=Market(market_text),
            scenario=AnalysisScenario(scenario_text),
            start_date=dates[0] if dates else None,
            end_date=dates[1] if dates else None,
        )
        result = SecurityAnalysisExecutor(tools).execute(request)
    except ValueError as error:
        output(f"Could not execute analysis: {error}")
        return 2
    except RuntimeError as error:
        output(f"Could not execute analysis: {error}")
        return 1
    output(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def run_report_command(
    arguments: Sequence[str],
    *,
    tools: ToolRegistry,
    output: Callable[[str], None] = print,
) -> int:
    """Create a deterministic single-security market-data research report."""

    if not arguments or arguments[0] in {"help", "--help", "-h"}:
        _print_report_help(output)
        return 0
    if len(arguments) != 4:
        _print_report_help(output)
        return 2
    market_text, symbol, start_date, end_date = arguments
    try:
        request = SecurityAnalysisRequest(
            symbol=symbol,
            market=Market(market_text),
            scenario=AnalysisScenario.CROSS_SOURCE_HISTORY_VALIDATION,
            start_date=start_date,
            end_date=end_date,
        )
        analysis_result = SecurityAnalysisExecutor(tools).execute(request)
        report = SecurityResearchReportBuilder().build(analysis_result)
    except ValueError as error:
        output(f"Could not create research report: {error}")
        return 2
    except RuntimeError as error:
        output(f"Could not create research report: {error}")
        return 1
    output(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _build_registered_tools(*, include_echo: bool = True) -> ToolRegistry:
    """Build read-only local tools without constructing an LLM client."""
    try:
        return build_market_data_tool_registry(include_echo=include_echo)
    except RuntimeError as error:
        raise SystemExit(
            f"Could not load a saved data-source credential: {error}. "
            "Delete and set that credential again."
        ) from error


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] == "source":
            exit_code = run_source_command(arguments[1:])
            if exit_code:
                raise SystemExit(exit_code)
            return
        if arguments[0] == "route":
            exit_code = run_route_command(arguments[1:])
            if exit_code:
                raise SystemExit(exit_code)
            return
        if arguments[0] == "analyze":
            exit_code = run_analyze_command(
                arguments[1:],
                tools=_build_registered_tools(include_echo=False),
            )
            if exit_code:
                raise SystemExit(exit_code)
            return
        if arguments[0] == "report":
            exit_code = run_report_command(
                arguments[1:],
                tools=_build_registered_tools(include_echo=False),
            )
            if exit_code:
                raise SystemExit(exit_code)
            return
        else:
            _print_source_help(print)
            _print_route_help(print)
            _print_analyze_help(print)
            _print_report_help(print)
            raise SystemExit(2)

    settings = AgentSettings.from_environment()
    if settings.provider == "echo":
        model = EchoModelClient()
    elif settings.provider == "codex":
        model = CodexCliModelClient(
            model=settings.model,
            timeout_seconds=settings.codex_timeout_seconds,
        )
    elif settings.provider == "qianfan":
        try:
            qianfan_api_key = resolve_token("qianfan", "QIANFAN_API_KEY")
        except SecretStoreError as error:
            raise SystemExit(
                "Could not read the saved Qianfan API key. "
                "Run 'finance-agent source delete-token qianfan' then set it again."
            ) from error
        if not qianfan_api_key:
            raise SystemExit(
                "Qianfan API key is not configured. Run 'finance-agent source set-token qianfan' "
                "or set QIANFAN_API_KEY for this process."
            )
        model = QianfanModelClient(
            qianfan_api_key,
            model=settings.model,
            timeout_seconds=settings.qianfan_timeout_seconds,
            enabled=lambda: ProviderActivationStore().is_enabled("qianfan"),
        )
    else:
        raise SystemExit(
            f"Provider '{settings.provider}' is not configured. Use 'codex', 'qianfan', or 'echo'."
        )

    project_root = Path(__file__).resolve().parents[2]
    skills = load_skills(project_root / "skills")
    system_prompt = compose_system_prompt(settings.system_prompt, skills)
    tool_registry = _build_registered_tools()
    agent = Agent(
        model=model,
        memory=ConversationMemory(system_prompt, settings.memory_window),
        tools=tool_registry,
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
            try:
                print(agent.run(user_input).text)
            except CodexCliError as error:
                print(f"Codex model request failed: {error}")
            except QianfanError as error:
                print(f"Qianfan model request failed: {error}")


if __name__ == "__main__":
    main()
