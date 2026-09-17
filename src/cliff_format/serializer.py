from __future__ import annotations

import re

from .identifiers import is_name, normalize_identifier, unique_identifier
from .model import CliffDocument, Entry, Group, Header

_KEBAB_ILLEGAL = re.compile(r"[^a-z0-9]+")
_KEBAB_RUN = re.compile(r"-{2,}")


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


def _style_identifier(value: str, *, kind: str, used: set[str]) -> str:
    """Normalize one identifier to the recommended shape.

    This is the *opt-in* style normalization of ``style/README.md``: it runs
    only when the caller asks for it (``serialize(..., style=True)``), because
    the specification requires a canonical serializer to emit identifiers
    exactly as the data model holds them (specification 17.7). Style
    normalization rewrites ids, which is exactly why it must never be implicit:
    an id is a translation match key.
    """
    if not is_name(value):
        value = normalize_identifier(value, kind=kind)
    lowered = value.lower()
    lowered = _KEBAB_RUN.sub("-", _KEBAB_ILLEGAL.sub("-", lowered)).strip("-")
    if not lowered:
        lowered = kind
    return unique_identifier(lowered, used)


def _serialize_header(header: Header, *, spec_version: str) -> list[str]:
    lines = [f"CLIFF {spec_version}"]
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


def _serialize_entry(entry: Entry, *, entry_id: str) -> list[str]:
    lines = [f"<{entry_id}>"]
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


def _serialize_group(
    group: Group,
    *,
    group_path: str,
    entry_ids: dict[int, str],
) -> list[str]:
    lines = [f"[{group_path}]"]
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
        lines.extend(
            _serialize_entry(entry, entry_id=entry_ids.get(id(entry), entry.id))
        )
    return lines


def serialize(document: CliffDocument, *, style: bool = False) -> str:
    """Serialize a :class:`CliffDocument` to canonical CLIFF text.

    The version line carries the version the document declared, so a document
    that announced ``CLIFF 1.0`` stays a 1.0 document and a new document gets
    the current specification version.

    With ``style=True`` identifiers are additionally normalized to the
    recommended kebab-case shape of ``style/README.md`` and disambiguated when
    two ids collapse into one. That rewrites translation match keys, so it is
    opt-in and never the canonical serializer's default; the caller is expected
    to report the renames.
    """
    header = document.header
    if style:
        namespace_used: set[str] = set()
        clan_used: set[str] = set()
        header = _copy_header(header)
        header.namespace = _style_identifier(
            header.namespace, kind="namespace", used=namespace_used
        )
        header.clan = _style_identifier(header.clan, kind="clan", used=clan_used)
        header.dependency = list(header.dependency)

    lines = _serialize_header(header, spec_version=document.spec_version or "1.1")
    group_ids: dict[str, str] = {}
    entry_ids: dict[int, str] = {}
    if style:
        used_paths: set[str] = set()
        for group in document.groups:
            parts = [
                _style_identifier(part, kind="group", used=used_paths)
                for part in group.path.split(".")
                if part
            ]
            group_ids[group.path] = ".".join(parts) or "group"
        used_entry_ids: set[str] = set()
        for group in document.groups:
            for entry in group.entries:
                entry_ids[id(entry)] = _style_identifier(
                    entry.id, kind="entry", used=used_entry_ids
                )

    for group in document.groups:
        lines.append("")
        lines.extend(
            _serialize_group(
                group,
                group_path=group_ids.get(group.path, group.path),
                entry_ids=entry_ids,
            )
        )
    return "\n".join(lines) + "\n"


def _copy_header(header: Header) -> Header:
    return Header(
        namespace=header.namespace,
        clan=header.clan,
        source_language=header.source_language,
        target_language=header.target_language,
        version=header.version,
        variant=header.variant,
        title=header.title,
        info=header.info,
        standard=header.standard,
        dependency=list(header.dependency),
        extensions=dict(header.extensions),
    )
