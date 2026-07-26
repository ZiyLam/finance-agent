"""Minimal local entry point used to prove the composition layer."""

from __future__ import annotations

from getpass import getpass
from os import getenv
from pathlib import Path
import sys
from typing import Callable, Sequence

from .agent import Agent
from .config import AgentSettings
from .memory import ConversationMemory
from .providers.echo import EchoModelClient
from .secrets import SecretStoreError, TokenStore, resolve_token
from .skills import compose_system_prompt, load_skills
from .tools import ToolRegistry, create_alltick_market_data_tool, create_echo_tool


_TOKEN_SOURCES = {"alltick": "ALLTICK_API_TOKEN"}


def _print_source_help(output: Callable[[str], None]) -> None:
    output("Usage: ai-agent source {status|set-token|delete-token} [alltick]")
    output("  status                 Show whether each source is configured; never prints tokens.")
    output("  set-token alltick      Prompt securely and save the token for this Windows user.")
    output("  delete-token alltick   Remove the saved token after confirmation.")


def run_source_command(
    arguments: Sequence[str],
    *,
    store: TokenStore | None = None,
    secret_input: Callable[[str], str] = getpass,
    confirmation_input: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
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
            if token:
                origin = "environment variable" if token == getenv(environment_variable) else "secure local store"
                output(f"{source}: configured via {origin}")
            else:
                output(f"{source}: not configured")
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
