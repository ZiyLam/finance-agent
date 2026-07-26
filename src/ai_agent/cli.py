"""Minimal local entry point used to prove the composition layer."""

from __future__ import annotations

from pathlib import Path

from .agent import Agent
from .config import AgentSettings
from .memory import ConversationMemory
from .providers.echo import EchoModelClient
from .skills import compose_system_prompt, load_skills
from .tools import ToolRegistry, create_echo_tool


def main() -> None:
    settings = AgentSettings.from_environment()
    if settings.provider != "echo":
        raise SystemExit(
            f"Provider '{settings.provider}' is not configured yet. "
            "Add an adapter under ai_agent.providers first."
        )

    project_root = Path(__file__).resolve().parents[2]
    skills = load_skills(project_root / "skills")
    system_prompt = compose_system_prompt(settings.system_prompt, skills)
    agent = Agent(
        model=EchoModelClient(),
        memory=ConversationMemory(system_prompt, settings.memory_window),
        tools=ToolRegistry((create_echo_tool(),)),
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
