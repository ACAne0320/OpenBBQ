from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Sequence

from ..errors import OpenBBQError

SKILL_NAME = "openbbq-subtitles"
_SKILL_PARTS = ("skills", SKILL_NAME)


class SkillAgent(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    AGENTS = "agents"
    ALL = "all"


SUPPORTED_AGENTS = (SkillAgent.CLAUDE, SkillAgent.CODEX, SkillAgent.AGENTS)


@dataclass(frozen=True)
class SkillInstall:
    path: Path
    files: int


def default_target() -> Path:
    return target_for_agent(SkillAgent.AGENTS)


def target_for_agent(agent: SkillAgent) -> Path:
    home = Path.home()
    match agent:
        case SkillAgent.CLAUDE:
            return home / ".claude" / "skills"
        case SkillAgent.CODEX:
            return home / ".codex" / "skills"
        case SkillAgent.AGENTS:
            return home / ".agents" / "skills"
        case SkillAgent.ALL:
            raise OpenBBQError(
                "invalid_skill_agent",
                agent=agent.value,
                fix="choose one of: claude, codex, agents",
            )


def targets_for_agent(agent: SkillAgent) -> list[Path]:
    if agent is SkillAgent.ALL:
        return [target_for_agent(target) for target in SUPPORTED_AGENTS]
    return [target_for_agent(agent)]


def packaged_skill_dir() -> Traversable:
    root = resources.files("openbbq").joinpath(*_SKILL_PARTS)
    if not root.is_dir():
        raise OpenBBQError(
            "skill_packaging_error",
            path=str(root),
            fix="reinstall openbbq from a wheel that includes package data",
        )
    return root


def packaged_skill_md() -> Traversable:
    path = packaged_skill_dir().joinpath("SKILL.md")
    if not path.is_file():
        raise OpenBBQError(
            "skill_packaging_error",
            path=str(path),
            fix="reinstall openbbq from a wheel that includes package data",
        )
    return path


def packaged_skill_path() -> str:
    return str(packaged_skill_md())


def packaged_skill_content() -> str:
    return packaged_skill_md().read_text(encoding="utf-8")


def installed_skill_path(target: Path | None = None) -> Path:
    root = default_target() if target is None else target.expanduser()
    return root / SKILL_NAME / "SKILL.md"


def _packaged_files() -> list[tuple[Path, Traversable]]:
    files: list[tuple[Path, Traversable]] = []

    def walk(prefix: Path, source: Traversable) -> None:
        for child in sorted(source.iterdir(), key=lambda p: p.name):
            rel = prefix / child.name
            if child.is_dir():
                walk(rel, child)
            elif child.is_file():
                files.append((rel, child))

    walk(Path(), packaged_skill_dir())
    return files


def _install_to_root(root: Path, *, force: bool = False) -> SkillInstall:
    dest = root / SKILL_NAME
    if dest.exists():
        if not force:
            raise OpenBBQError(
                "skill_exists",
                path=str(dest),
                fix="openbbq skill install --force",
            )
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    root.mkdir(parents=True, exist_ok=True)
    dest.mkdir()

    files = 0
    for rel, source in _packaged_files():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(source.read_bytes())
        files += 1

    return SkillInstall(path=dest, files=files)


def install(target: Path | None = None, *, force: bool = False) -> SkillInstall:
    root = default_target() if target is None else target.expanduser()
    return _install_to_root(root, force=force)


def install_for_agent(agent: SkillAgent, *, force: bool = False) -> list[SkillInstall]:
    roots = targets_for_agent(agent)
    return install_targets(roots, force=force)


def install_targets(roots: Sequence[Path], *, force: bool = False) -> list[SkillInstall]:
    if not force:
        for root in roots:
            root = root.expanduser()
            dest = root / SKILL_NAME
            if dest.exists():
                raise OpenBBQError(
                    "skill_exists",
                    path=str(dest),
                    fix="openbbq skill install --force",
                )
    return [_install_to_root(root.expanduser(), force=force) for root in roots]
