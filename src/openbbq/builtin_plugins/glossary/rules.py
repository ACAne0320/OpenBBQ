from __future__ import annotations

import re
from typing import Any


def normalize_rules(value: Any, *, parameter_name: str, tool_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{tool_name} parameter '{parameter_name}' must be a list.")

    rules: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{tool_name} parameter '{parameter_name}' must be a list.")
        rules.append(_normalize_rule(item, tool_name=tool_name))
    return rules


def apply_text_rules(text: str, rules: list[dict[str, Any]]) -> str:
    next_text = text
    for rule in rules:
        target = str(rule["target"])
        for pattern in _source_patterns(rule):
            if rule.get("is_regex", False):
                flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
                next_text = re.sub(pattern, target, next_text, flags=flags)
                continue
            if rule.get("case_sensitive", False):
                next_text = next_text.replace(pattern, target)
            else:
                next_text = re.sub(re.escape(pattern), target, next_text, flags=re.IGNORECASE)
    return next_text


def source_matches(text: str, rule: dict[str, Any]) -> bool:
    for pattern in _source_patterns(rule):
        if rule.get("is_regex", False):
            flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
            if re.search(pattern, text, flags=flags):
                return True
            continue
        if rule.get("case_sensitive", False):
            if pattern in text:
                return True
            continue
        if pattern.lower() in text.lower():
            return True
    return False


def _normalize_rule(item: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    source = _coalesce_terms(item, primary="source", legacy="find", tool_name=tool_name)
    protected = _optional_bool(item.get("protected"), field_name="protected", tool_name=tool_name)
    target = _coalesce_terms(
        item,
        primary="target",
        legacy="replace",
        tool_name=tool_name,
        required=not protected,
    )
    if target is None:
        target = source
    aliases = _aliases(item.get("aliases"), tool_name=tool_name)
    is_regex = _optional_bool(item.get("is_regex"), field_name="is_regex", tool_name=tool_name)
    case_sensitive = _optional_bool(
        item.get("case_sensitive"),
        field_name="case_sensitive",
        tool_name=tool_name,
    )

    rule: dict[str, Any] = {"source": source, "target": target}
    if aliases:
        rule["aliases"] = aliases
    if protected:
        rule["protected"] = True
    if is_regex:
        rule["is_regex"] = True
    if case_sensitive:
        rule["case_sensitive"] = True
    return rule


def _coalesce_terms(
    item: dict[str, Any],
    *,
    primary: str,
    legacy: str,
    tool_name: str,
    required: bool = True,
) -> str | None:
    primary_value = _optional_string(item.get(primary), field_name=primary, tool_name=tool_name)
    legacy_value = _optional_string(item.get(legacy), field_name=legacy, tool_name=tool_name)
    if primary_value and legacy_value and primary_value != legacy_value:
        raise ValueError(
            f"{tool_name} glossary rule fields '{primary}' and '{legacy}' must match when both are set."
        )
    value = primary_value or legacy_value
    if value is None and required:
        raise ValueError(
            f"{tool_name} glossary rule must include '{primary}' or legacy field '{legacy}'."
        )
    return value


def _optional_string(value: Any, *, field_name: str, tool_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{tool_name} glossary rule '{field_name}' must be a non-empty string.")
    return value.strip()


def _optional_bool(value: Any, *, field_name: str, tool_name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"{tool_name} glossary rule '{field_name}' must be a boolean.")
    return value


def _aliases(value: Any, *, tool_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{tool_name} glossary rule 'aliases' must be a string list.")
    aliases: list[str] = []
    for alias in value:
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(f"{tool_name} glossary rule 'aliases' must be a string list.")
        normalized = alias.strip()
        if normalized not in aliases:
            aliases.append(normalized)
    return aliases


def _source_patterns(rule: dict[str, Any]) -> list[str]:
    patterns = [str(rule["source"])]
    for alias in rule.get("aliases", []):
        normalized = str(alias)
        if normalized not in patterns:
            patterns.append(normalized)
    return patterns
