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


class SkillName(StrEnum):
    SUBTITLES = "openbbq-subtitles"
    BILIBILI_COVER_SAFE_AREA = "bilibili-cover-safe-area"


_DEFAULT_SKILL = SkillName.SUBTITLES


class SkillAgent(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    AGENTS = "agents"
    ALL = "all"


class SkillLanguage(StrEnum):
    EN = "en"
    ZH_CN = "zh-CN"


SUPPORTED_AGENTS = (SkillAgent.CLAUDE, SkillAgent.CODEX, SkillAgent.AGENTS)


@dataclass(frozen=True)
class SkillInstall:
    path: Path
    files: int
    language: SkillLanguage


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


def packaged_skill_dir(name: SkillName = _DEFAULT_SKILL) -> Traversable:
    root = resources.files("openbbq").joinpath("skills", name.value)
    if not root.is_dir():
        raise OpenBBQError(
            "skill_packaging_error",
            path=str(root),
            fix="reinstall openbbq from a wheel that includes package data",
        )
    return root


def packaged_skill_md(
    language: SkillLanguage = SkillLanguage.EN,
    *,
    name: SkillName = _DEFAULT_SKILL,
) -> Traversable:
    filename = "SKILL.zh-CN.md" if language is SkillLanguage.ZH_CN else "SKILL.md"
    path = packaged_skill_dir(name).joinpath(filename)
    if not path.is_file():
        raise OpenBBQError(
            "skill_packaging_error",
            path=str(path),
            fix="reinstall openbbq from a wheel that includes package data",
        )
    return path


def packaged_skill_path(
    language: SkillLanguage = SkillLanguage.EN,
    *,
    name: SkillName = _DEFAULT_SKILL,
) -> str:
    return str(packaged_skill_md(language, name=name))


def packaged_skill_content(
    language: SkillLanguage = SkillLanguage.EN,
    *,
    name: SkillName = _DEFAULT_SKILL,
) -> str:
    return packaged_skill_md(language, name=name).read_text(encoding="utf-8")


def packaged_skill_contents(
    name: SkillName = _DEFAULT_SKILL,
) -> dict[SkillLanguage, str]:
    return {
        language: packaged_skill_content(language, name=name)
        for language in SkillLanguage
    }


def installed_skill_path(
    target: Path | None = None,
    *,
    name: SkillName = _DEFAULT_SKILL,
) -> Path:
    root = default_target() if target is None else target.expanduser()
    return root / name.value / "SKILL.md"


def _packaged_files(
    language: SkillLanguage,
    *,
    name: SkillName,
) -> list[tuple[Path, Traversable]]:
    files: list[tuple[Path, Traversable]] = []

    def walk(prefix: Path, source: Traversable) -> None:
        for child in sorted(source.iterdir(), key=lambda p: p.name):
            rel = prefix / child.name
            if child.is_dir():
                walk(rel, child)
            elif child.is_file():
                files.append((rel, child))

    walk(Path(), packaged_skill_dir(name))
    if language is SkillLanguage.ZH_CN:
        files = [
            (Path("SKILL.md"), packaged_skill_md(SkillLanguage.ZH_CN, name=name))
            if rel == Path("SKILL.md")
            else (rel, source)
            for rel, source in files
        ]
    return files


def _install_to_root(
    root: Path,
    *,
    name: SkillName,
    force: bool = False,
    language: SkillLanguage = SkillLanguage.EN,
) -> SkillInstall:
    dest = root / name.value
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
    for rel, source in _packaged_files(language, name=name):
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(source.read_bytes())
        files += 1

    return SkillInstall(path=dest, files=files, language=language)


def install(
    target: Path | None = None,
    *,
    name: SkillName = _DEFAULT_SKILL,
    force: bool = False,
    language: SkillLanguage = SkillLanguage.EN,
) -> SkillInstall:
    root = default_target() if target is None else target.expanduser()
    return _install_to_root(root, name=name, force=force, language=language)


def install_for_agent(
    agent: SkillAgent,
    *,
    name: SkillName = _DEFAULT_SKILL,
    force: bool = False,
    language: SkillLanguage = SkillLanguage.EN,
) -> list[SkillInstall]:
    roots = targets_for_agent(agent)
    return install_targets(roots, name=name, force=force, language=language)


def install_targets(
    roots: Sequence[Path],
    *,
    name: SkillName = _DEFAULT_SKILL,
    force: bool = False,
    language: SkillLanguage = SkillLanguage.EN,
) -> list[SkillInstall]:
    if not force:
        for root in roots:
            root = root.expanduser()
            dest = root / name.value
            if dest.exists():
                raise OpenBBQError(
                    "skill_exists",
                    path=str(dest),
                    fix="openbbq skill install --force",
                )
    return [
        _install_to_root(
            root.expanduser(), name=name, force=force, language=language
        )
        for root in roots
    ]
