"""Loading and rendering of project-local agent skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentSkill:
    """A reviewed instruction set that can be added to an agent's system prompt."""

    name: str
    description: str
    instructions: str
    source_path: Path

    def render_for_system_prompt(self) -> str:
        return f"## Active skill: {self.name}\n{self.description}\n\n{self.instructions}"


def load_skill(path: Path) -> AgentSkill:
    """Load one Markdown skill with a minimal YAML-style front matter header."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Skill '{path}' must start with front matter")

    try:
        _, raw_header, instructions = text.split("---\n", maxsplit=2)
    except ValueError as error:
        raise ValueError(f"Skill '{path}' has an incomplete front matter block") from error

    metadata: dict[str, str] = {}
    for line in raw_header.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"Skill '{path}' has invalid metadata: {line!r}")
        metadata[key.strip()] = value.strip().strip('"')

    name = metadata.get("name")
    description = metadata.get("description")
    if not name or not description:
        raise ValueError(f"Skill '{path}' requires name and description metadata")
    if not instructions.strip():
        raise ValueError(f"Skill '{path}' has no instructions")

    return AgentSkill(
        name=name,
        description=description,
        instructions=instructions.strip(),
        source_path=path,
    )


def load_skills(directory: Path) -> tuple[AgentSkill, ...]:
    """Discover skills deterministically, one SKILL.md file per skill directory."""

    if not directory.exists():
        return ()
    return tuple(load_skill(path) for path in sorted(directory.glob("*/SKILL.md")))


def compose_system_prompt(base_prompt: str, skills: tuple[AgentSkill, ...]) -> str:
    """Keep the application-owned prompt first, then append reviewed capabilities."""

    rendered_skills = "\n\n".join(skill.render_for_system_prompt() for skill in skills)
    return f"{base_prompt}\n\n{rendered_skills}" if rendered_skills else base_prompt
