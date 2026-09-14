from __future__ import annotations

from .model import CliffDocument, Entry, Group, Header


def _quote_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _format_quoted_list(items: list[str]) -> str:
    return "[" + ", ".join(_quote_string(item) for item in items) + "]"


def _format_bare_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _serialize_header(header: Header) -> list[str]:
    lines = ["CLIFF 1.0"]
    lines.append(f"namespace: {header.namespace}")
    lines.append(f"clan: {header.clan}")
    lines.append(f"source-language: {header.source_language}")
    lines.append(f"target-language: {header.target_language}")
    if header.version is not None:
        lines.append(f"version: {_quote_string(header.version)}")
    if header.variant not in (None, "standard"):
        lines.append(f"variant: {header.variant}")
    if header.title is not None:
        lines.append(f"title: {_quote_string(header.title)}")
    if header.info is not None:
        lines.append(f"info: {_quote_string(header.info)}")
    if header.standard is not None:
        lines.append(f"standard: {_quote_string(header.standard)}")
    if header.dependency:
        lines.append(f"dependency: {_format_quoted_list(header.dependency)}")
    for key in sorted(header.extensions):
        lines.append(f"{key}: {header.extensions[key]}")
    return lines


def _serialize_entry(entry: Entry) -> list[str]:
    lines = [f"<{entry.id}>"]
    if entry.source is not None:
        lines.append(f"source: {_quote_string(entry.source)}")
    if entry.target is not None:
        lines.append(f"target: {_quote_string(entry.target)}")
    if entry.type is not None:
        lines.append(f"type: {entry.type}")
    if entry.emotion:
        lines.append(f"emotion: {_format_bare_list(entry.emotion)}")
    if entry.status is not None:
        lines.append(f"status: {entry.status}")
    if entry.context is not None:
        lines.append(f"context: {_quote_string(entry.context)}")
    if entry.max_width is not None:
        lines.append(f"max-width: {entry.max_width}")
    if entry.reference:
        lines.append(f"reference: {_format_quoted_list(entry.reference)}")
    if entry.reviewer is not None:
        lines.append(f"reviewer: {_quote_string(entry.reviewer)}")
    for key in sorted(entry.extensions):
        lines.append(f"{key}: {entry.extensions[key]}")
    return lines


def _serialize_group(group: Group) -> list[str]:
    lines = [f"[{group.path}]"]
    if group.context is not None:
        lines.append(f"context: {_quote_string(group.context)}")
    if group.type is not None:
        lines.append(f"type: {group.type}")
    if group.emotion:
        lines.append(f"emotion: {_format_bare_list(group.emotion)}")
    if group.max_width is not None:
        lines.append(f"max-width: {group.max_width}")
    for key in sorted(group.extensions):
        lines.append(f"{key}: {group.extensions[key]}")
    for entry in group.entries:
        lines.append("")
        lines.extend(_serialize_entry(entry))
    return lines


def serialize(document: CliffDocument) -> str:
    """Serialize a :class:`CliffDocument` to canonical CLIFF text."""
    lines = _serialize_header(document.header)
    for group in document.groups:
        lines.append("")
        lines.extend(_serialize_group(group))
    return "\n".join(lines) + "\n"
