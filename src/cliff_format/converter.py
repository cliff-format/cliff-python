from __future__ import annotations

import csv
import io
import json
import re
from typing import Any
from xml.etree import ElementTree as ET

from .errors import CliffError
from .model import CliffDocument, Entry, Group, Header
from .validator import effective_context

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PIPE_ESCAPE_RE = re.compile(r"\\(.)")


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _join_pipe(items: list[str]) -> str:
    """Encode a list into one pipe-separated cell, escaping literal pipes."""
    return "|".join(item.replace("\\", "\\\\").replace("|", "\\|") for item in items)


def _split_pipe(value: str | None) -> list[str]:
    """Decode a pipe-separated cell produced by _join_pipe."""
    if not value:
        return []
    items: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in value:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [item.strip() for item in items if item.strip()]


# Flat formats (PO, Fluent, Android, iOS) have no group level and no field for
# CLIFF-specific attributes, so those attributes travel through each format's
# own official metadata channel under a namespaced key.
CLIFF_META_PREFIX = "cliff:"
CLIFF_META_KEYS = (
    "source",
    "type",
    "emotion",
    "status",
    "context",
    "max-width",
    "reference",
    "reviewer",
)


def _entry_metadata(
    group: Group,
    entry: Entry,
    *,
    include_source: bool = False,
) -> dict[str, str]:
    """CLIFF attributes of one entry, resolved for a format without groups.

    Group metadata is folded into the entry because the target format has no
    group level. Only values that really exist are emitted: a derived default
    such as the emotion implied by the type is never written out, so importing
    the result back cannot invent context that the document did not carry.
    """
    meta: dict[str, str] = {}
    if include_source and entry.source is not None:
        meta["source"] = entry.source
    resolved_type = entry.type or group.type
    if resolved_type:
        meta["type"] = resolved_type
    emotion = entry.emotion or group.emotion
    if emotion:
        meta["emotion"] = _join_pipe(emotion)
    if entry.status:
        meta["status"] = entry.status
    context = effective_context(entry, group)
    if context:
        meta["context"] = context
    max_width = entry.max_width if entry.max_width is not None else group.max_width
    if max_width is not None:
        meta["max-width"] = str(max_width)
    if entry.reference:
        meta["reference"] = _join_pipe(entry.reference)
    if entry.reviewer:
        meta["reviewer"] = entry.reviewer
    return meta


def _split_meta_line(text: str) -> tuple[str, str] | None:
    """Split a namespaced metadata line into its CLIFF key and value.

    Returns None for any other text, which callers treat as free-form context
    rather than as structured metadata.
    """
    stripped = text.strip()
    if not stripped.startswith(CLIFF_META_PREFIX):
        return None
    body = stripped[len(CLIFF_META_PREFIX) :]
    for separator in (":", "="):
        key, found, value = body.partition(separator)
        if found and key.strip() in CLIFF_META_KEYS:
            return key.strip(), value.strip()
    return None


def _entry_from_metadata(
    entry_id: str,
    meta: dict[str, str],
    *,
    text: str | None,
    context_lines: list[str],
    fallback_source: str,
) -> Entry:
    """Build an entry from a flat format, using only metadata that was present.

    Everything the source format did not carry falls back to a documented
    default rather than to invented context.
    """
    source = meta.get("source") or fallback_source
    target = text if meta.get("source") else None
    if target is None and text is not None and text != source:
        target = text
    context = meta.get("context") or (" ".join(context_lines) or None)
    width = meta.get("max-width")
    return Entry(
        id=entry_id,
        source=source,
        target=target,
        type=meta.get("type") or "sentence",
        emotion=_split_pipe(meta.get("emotion")),
        status=meta.get("status") or ("translated" if target else "initial"),
        context=context,
        max_width=int(width) if width and width.isdigit() else None,
        reference=_split_pipe(meta.get("reference")),
        reviewer=meta.get("reviewer"),
    )


def _metadata_comment(meta: dict[str, str]) -> str:
    """Render entry metadata as the comment body a flat format carries."""
    lines = []
    context = meta.get("context")
    if context:
        lines.append(context)
    lines.extend(
        f"{CLIFF_META_PREFIX}{key}: {value}"
        for key, value in meta.items()
        if key != "context"
    )
    return "\n".join(lines)


def _read_metadata_comment(body: str) -> tuple[dict[str, str], list[str]]:
    """Split a comment body into CLIFF metadata and free-form context lines."""
    meta: dict[str, str] = {}
    context_lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        pair = _split_meta_line(line)
        if pair is not None:
            meta[pair[0]] = pair[1]
        else:
            context_lines.append(line)
    return meta, context_lines


def _safe_name(text: str, fallback: str = "entry") -> str:
    """Coerce arbitrary external text into a valid CLIFF name.

    Identifiers imported from JSON keys, Android/iOS resource names or CSV
    columns routinely contain uppercase letters, underscores or dots, none of
    which the specification allows. They are folded to lowercase kebab-case so
    every generated document validates.
    """
    candidate = re.sub(r"[^a-z0-9-]+", "-", text.strip().lower()).strip("-")
    candidate = re.sub(r"-{2,}", "-", candidate)
    if not candidate or not NAME_RE.match(candidate):
        candidate = f"{fallback}-{candidate}".strip("-") if candidate else fallback
    return candidate if NAME_RE.match(candidate) else fallback


def _safe_group_path(path: str, fallback: str = "imported") -> str:
    """Coerce a dotted group path so every segment is a valid CLIFF name."""
    segments = [_safe_name(part, fallback) for part in path.split(".") if part.strip()]
    return ".".join(segments) if segments else fallback


def _unique_id(seen: set[str], group_path: str, entry_id: str) -> str:
    """Return an entry id unique within the document.

    Duplicate entry ids are a hard error in CLIFF and must never silently
    overwrite one another, so importers disambiguate with a numeric suffix.
    """
    candidate = entry_id
    counter = 2
    while f"{group_path}.{candidate}" in seen:
        candidate = f"{entry_id}-{counter}"
        counter += 1
    seen.add(f"{group_path}.{candidate}")
    return candidate


def to_dict(document: CliffDocument) -> dict[str, Any]:
    """Convert a :class:`CliffDocument` to a JSON-shaped dictionary.

    The dictionary uses CLIFF field names (``source-language``,
    ``target-language``, ``max-width``) for easy interchange.
    """
    header = document.header
    header_data: dict[str, Any] = {
        "namespace": header.namespace,
        "clan": header.clan,
        "source-language": header.source_language,
        "target-language": header.target_language,
    }
    if header.version is not None:
        header_data["version"] = header.version
    if header.variant != "standard":
        header_data["variant"] = header.variant
    if header.title is not None:
        header_data["title"] = header.title
    if header.info is not None:
        header_data["info"] = header.info
    if header.standard is not None:
        header_data["standard"] = header.standard
    if header.dependency:
        header_data["dependency"] = list(header.dependency)
    if header.extensions:
        header_data["extensions"] = dict(header.extensions)

    groups: list[dict[str, Any]] = []
    for group in document.groups:
        group_data: dict[str, Any] = {"path": group.path}
        if group.context is not None:
            group_data["context"] = group.context
        if group.type is not None:
            group_data["type"] = group.type
        if group.emotion:
            group_data["emotion"] = list(group.emotion)
        if group.max_width is not None:
            group_data["max-width"] = group.max_width
        if group.extensions:
            group_data["extensions"] = dict(group.extensions)

        entries: list[dict[str, Any]] = []
        for entry in group.entries:
            entry_data: dict[str, Any] = {"id": entry.id}
            if entry.source is not None:
                entry_data["source"] = entry.source
            if entry.target is not None:
                entry_data["target"] = entry.target
            if entry.type is not None:
                entry_data["type"] = entry.type
            if entry.emotion:
                entry_data["emotion"] = list(entry.emotion)
            if entry.status is not None:
                entry_data["status"] = entry.status
            if entry.context is not None:
                entry_data["context"] = entry.context
            if entry.max_width is not None:
                entry_data["max-width"] = entry.max_width
            if entry.reference:
                entry_data["reference"] = list(entry.reference)
            if entry.reviewer is not None:
                entry_data["reviewer"] = entry.reviewer
            if entry.extensions:
                entry_data["extensions"] = dict(entry.extensions)
            entries.append(entry_data)
        group_data["entries"] = entries
        groups.append(group_data)

    return {"header": header_data, "groups": groups}


def is_cliff_mapping(data: Any) -> bool:
    """Whether a decoded mapping is a CLIFF document rather than a flat file.

    A CLIFF-shaped mapping carries a header object and a groups list; anything
    else is a plain key/value localization file.
    """
    return (
        isinstance(data, dict)
        and isinstance(data.get("header"), dict)
        and isinstance(data.get("groups"), list)
    )


def from_dict(data: dict[str, Any]) -> CliffDocument:
    """Create a CliffDocument from a JSON-shaped dictionary.

    Raises CliffError when the mapping omits a required header field, because a
    converter must never emit a document that cannot validate.
    """
    header_data = data.get("header", {})
    missing = [
        key
        for key, aliases in (
            ("namespace", ("namespace",)),
            ("clan", ("clan",)),
            ("source-language", ("source-language", "source_language")),
            ("target-language", ("target-language", "target_language")),
        )
        if not _pick(header_data, *aliases)
    ]
    if missing:
        raise CliffError(
            "CLIFF-shaped input is missing required header fields: "
            + ", ".join(missing)
        )
    header = Header(
        namespace=str(_pick(header_data, "namespace") or ""),
        clan=str(_pick(header_data, "clan") or ""),
        source_language=str(_pick(header_data, "source-language", "source_language") or ""),
        target_language=str(_pick(header_data, "target-language", "target_language") or ""),
        version=(
            str(_pick(header_data, "version"))
            if _pick(header_data, "version") is not None
            else None
        ),
        variant=str(_pick(header_data, "variant") or "standard"),
        title=(
            str(_pick(header_data, "title"))
            if _pick(header_data, "title") is not None
            else None
        ),
        info=(
            str(_pick(header_data, "info"))
            if _pick(header_data, "info") is not None
            else None
        ),
        standard=(
            str(_pick(header_data, "standard"))
            if _pick(header_data, "standard") is not None
            else None
        ),
        dependency=[str(item) for item in _pick(header_data, "dependency") or []],
        extensions={
            str(k): str(v) for k, v in (_pick(header_data, "extensions") or {}).items()
        },
    )

    groups: list[Group] = []
    for group_data in data.get("groups", []):
        group = Group(
            path=str(group_data.get("path", "")),
            context=(
                str(group_data["context"])
                if group_data.get("context") is not None
                else None
            ),
            type=(
                str(group_data["type"])
                if group_data.get("type") is not None
                else None
            ),
            emotion=[str(item) for item in group_data.get("emotion") or []],
            max_width=(
                int(group_data["max-width"])
                if group_data.get("max-width") is not None
                else None
            ),
            extensions={
                str(k): str(v) for k, v in (group_data.get("extensions") or {}).items()
            },
        )
        for entry_data in group_data.get("entries", []):
            entry = Entry(
                id=str(entry_data.get("id", "")),
                source=(
                    str(entry_data["source"])
                    if entry_data.get("source") is not None
                    else None
                ),
                target=(
                    str(entry_data["target"])
                    if entry_data.get("target") is not None
                    else None
                ),
                type=(
                    str(entry_data["type"])
                    if entry_data.get("type") is not None
                    else None
                ),
                emotion=[str(item) for item in entry_data.get("emotion") or []],
                status=(
                    str(entry_data["status"])
                    if entry_data.get("status") is not None
                    else None
                ),
                context=(
                    str(entry_data["context"])
                    if entry_data.get("context") is not None
                    else None
                ),
                max_width=(
                    int(entry_data["max-width"])
                    if entry_data.get("max-width") is not None
                    else None
                ),
                reference=[str(item) for item in entry_data.get("reference") or []],
                reviewer=(
                    str(entry_data["reviewer"])
                    if entry_data.get("reviewer") is not None
                    else None
                ),
                extensions={
                    str(k): str(v) for k, v in (entry_data.get("extensions") or {}).items()
                },
            )
            group.entries.append(entry)
        groups.append(group)

    return CliffDocument(header=header, groups=groups)


def to_json(
    document: CliffDocument,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
) -> str:
    """Serialize a :class:`CliffDocument` to JSON text."""
    return json.dumps(to_dict(document), ensure_ascii=ensure_ascii, indent=indent)


def from_json(text: str) -> CliffDocument:
    """Parse JSON text into a document.

    CLIFF-shaped JSON produced by to_json round-trips exactly; a flat
    key/value localization file is imported through from_plain_json instead.
    """
    data = json.loads(text)
    if is_cliff_mapping(data):
        return from_dict(data)
    return from_plain_json(text)


def from_plain_json(
    text: str,
    *,
    clan: str = "imported",
    source_language: str = "und",
    target_language: str = "und",
    entry_type: str = "sentence",
    entry_status: str | None = None,
) -> CliffDocument:
    """Import a plain/flat JSON localization file (for example Minecraft-style).

    This accepts a JSON object where keys are translation keys and values are
    target strings. Nested objects are flattened with dots. CLIFF requires
    ``type`` and ``status`` on every entry, so sensible defaults are applied
    unless overridden through ``entry_type`` / ``entry_status``.
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise CliffError("plain JSON root must be an object")

    header = Header(
        namespace="json",
        clan=clan,
        source_language=source_language,
        target_language=target_language,
    )
    document = CliffDocument(header=header)
    group_map: dict[str, Group] = {}
    seen_ids: set[str] = set()

    def add_entry(key: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        parts = key.split(".")
        entry_id = _safe_name(parts[-1])
        raw_path = ".".join(parts[:-1]) if len(parts) > 1 else "imported"
        group_path = _safe_group_path(raw_path)
        if group_path not in group_map:
            group = Group(path=group_path)
            document.groups.append(group)
            group_map[group_path] = group
        else:
            group = group_map[group_path]
        target = value or None
        status = entry_status or ("translated" if target else "initial")
        group.entries.append(
            Entry(
                id=_unique_id(seen_ids, group_path, entry_id),
                source=key,
                target=target,
                type=entry_type,
                status=status,
            )
        )

    def walk(obj: dict[str, Any], prefix: str = "") -> None:
        for key, value in obj.items():
            full = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                walk(value, full)
            else:
                add_entry(full, value)

    walk(data)
    return document


def from_plain_yaml(
    text: str,
    *,
    clan: str = "imported",
    source_language: str = "und",
    target_language: str = "und",
    entry_type: str = "sentence",
    entry_status: str | None = None,
) -> CliffDocument:
    """Import a plain YAML localization mapping with valid CLIFF defaults."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise CliffError("PyYAML is required for YAML conversion") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CliffError("YAML root must be a mapping")
    if is_cliff_mapping(data):
        return from_dict(data)
    return from_plain_json(
        json.dumps(data, ensure_ascii=False),
        clan=clan,
        source_language=source_language,
        target_language=target_language,
        entry_type=entry_type,
        entry_status=entry_status,
    )


def to_yaml(document: CliffDocument) -> str:
    """Serialize a :class:`CliffDocument` to YAML (requires PyYAML)."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise CliffError("PyYAML is required for YAML conversion") from exc
    return yaml.safe_dump(to_dict(document), allow_unicode=True, sort_keys=False)


def from_yaml(text: str) -> CliffDocument:
    """Parse YAML text into a document.

    CLIFF-shaped YAML produced by to_yaml round-trips exactly; a flat
    key/value mapping is imported through from_plain_yaml instead.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise CliffError("PyYAML is required for YAML conversion") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CliffError("YAML root must be a mapping")
    if is_cliff_mapping(data):
        return from_dict(data)
    return from_plain_yaml(text)


def to_fluent(document: CliffDocument) -> str:
    """Serialize a CliffDocument to Fluent (.ftl) text.

    Fluent has exactly one metadata channel: the comment attached to a message.
    Attributes are translatable content, not metadata, so CLIFF attributes are
    written as namespaced comment lines above the message and the message value
    holds the translation.
    """
    lines: list[str] = []
    for group in document.groups:
        for entry in group.entries:
            meta = _entry_metadata(group, entry, include_source=True)
            context = meta.pop("context", None)
            if context:
                lines.append(f"# {context}")
            for key, value in meta.items():
                lines.append(f"# {CLIFF_META_PREFIX}{key} = {value}")
            lines.append(f"{entry.id} = {entry.target or entry.source or ''}")
            lines.append("")
    return "\n".join(lines) + "\n" if lines else "\n"


def from_fluent(text: str, *, clan: str = "imported") -> CliffDocument:
    """Parse Fluent (.ftl) messages into a CLIFF document.

    Message comments are Fluent's metadata channel, so namespaced cliff: lines
    are read back as CLIFF attributes and any other comment line becomes the
    entry context. A file without such comments yields entries with defaults
    only; nothing is invented. Fluent attributes are translatable content that
    CLIFF cannot represent and are skipped.
    """
    header = Header(
        namespace="fluent",
        clan=clan,
        source_language="und",
        target_language="und",
    )
    document = CliffDocument(header=header)
    group = Group(path="fluent")
    document.groups.append(group)
    seen_ids: set[str] = set()

    meta: dict[str, str] = {}
    context_lines: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("###") or line.startswith("##"):
            # Resource and section comments describe the file, not a message.
            continue
        if line.startswith("#"):
            body = line[1:].strip()
            pair = _split_meta_line(body)
            if pair is not None:
                meta[pair[0]] = pair[1]
            elif body:
                context_lines.append(body)
            continue
        if line.startswith("."):
            continue
        message_id, separator, value = line.partition("=")
        if not separator:
            continue
        entry_id = _safe_name(message_id.strip())
        entry = _entry_from_metadata(
            _unique_id(seen_ids, group.path, entry_id),
            meta,
            text=value.strip() or None,
            context_lines=context_lines,
            fallback_source=message_id.strip(),
        )
        group.entries.append(entry)
        meta = {}
        context_lines = []

    return document

def to_android_strings(document: CliffDocument) -> str:
    """Serialize a CliffDocument to Android strings.xml.

    Android has no metadata attributes; the documented channel for translator
    context is an XML comment preceding the resource, which is what Android
    Studio and the translation tooling display. CLIFF attributes therefore ride
    in that comment under a namespaced key.
    """
    root = ET.Element("resources")
    for group in document.groups:
        for entry in group.entries:
            meta = _entry_metadata(group, entry, include_source=True)
            comment = _metadata_comment(meta)
            if comment:
                root.append(ET.Comment(comment))
            item = ET.SubElement(root, "string", {"name": entry.id})
            item.text = entry.target or entry.source or ""
    ET.indent(root, space="    ")
    xml = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + xml + "\n"


def from_android_strings(text: str, *, clan: str = "imported") -> CliffDocument:
    """Parse Android strings.xml into a CLIFF document.

    A comment preceding a string is Android's translator-context channel and is
    read back accordingly. Files without comments produce entries carrying only
    defaults.
    """
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    parser.feed(text)
    root = parser.close()
    header = Header(
        namespace="android",
        clan=clan,
        source_language="und",
        target_language="und",
    )
    document = CliffDocument(header=header)
    group = Group(path="android")
    document.groups.append(group)
    seen_ids: set[str] = set()

    meta: dict[str, str] = {}
    context_lines: list[str] = []
    for node in root:
        if not isinstance(node.tag, str):
            # ElementTree models a comment as a callable tag.
            meta, context_lines = _read_metadata_comment(node.text or "")
            continue
        if node.tag != "string":
            continue
        name = node.get("name", "")
        if not name:
            continue
        group.entries.append(
            _entry_from_metadata(
                _unique_id(seen_ids, group.path, _safe_name(name)),
                meta,
                text=node.text or None,
                context_lines=context_lines,
                fallback_source=name,
            )
        )
        meta = {}
        context_lines = []
    return document


def to_ios_strings(document: CliffDocument) -> str:
    """Serialize a CliffDocument to iOS Localizable.strings.

    Apple's genstrings convention puts the translator comment in a block
    comment directly above the key/value pair, so CLIFF attributes travel there.
    """
    lines: list[str] = []
    for group in document.groups:
        for entry in group.entries:
            meta = _entry_metadata(group, entry, include_source=True)
            comment = _metadata_comment(meta)
            if comment:
                lines.append("/* " + comment.replace("*/", "*\\/") + " */")
            value = entry.target or entry.source or ""
            lines.append(f"{_po_quote(entry.id)} = {_po_quote(value)};")
    return "\n".join(lines) + "\n" if lines else "\n"

IOS_PAIR_RE = re.compile(r'^\s*"((?:\\.|[^"])*)"\s*=\s*"((?:\\.|[^"])*)"\s*;\s*$')
IOS_COMMENT_RE = re.compile(r"/\*(.*?)\*/", re.DOTALL)


def from_ios_strings(text: str, *, clan: str = "imported") -> CliffDocument:
    """Parse iOS Localizable.strings into a CLIFF document.

    A block comment preceding a pair is Apple's translator-context channel and
    is read back accordingly; files without comments produce entries carrying
    only defaults.
    """
    header = Header(
        namespace="ios",
        clan=clan,
        source_language="und",
        target_language="und",
    )
    document = CliffDocument(header=header)
    group = Group(path="ios")
    document.groups.append(group)
    seen_ids: set[str] = set()

    meta: dict[str, str] = {}
    context_lines: list[str] = []
    pending_comment: list[str] = []
    in_comment = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if in_comment:
            if "*/" in line:
                pending_comment.append(line.split("*/", 1)[0])
                meta, context_lines = _read_metadata_comment("\n".join(pending_comment))
                pending_comment = []
                in_comment = False
            else:
                pending_comment.append(line)
            continue
        if line.startswith("/*"):
            single = IOS_COMMENT_RE.match(line)
            if single is not None:
                meta, context_lines = _read_metadata_comment(single.group(1))
            else:
                pending_comment = [line[2:]]
                in_comment = True
            continue
        match = IOS_PAIR_RE.match(line)
        if not match:
            continue
        key = _po_unescape(match.group(1))
        value = _po_unescape(match.group(2)) or None
        group.entries.append(
            _entry_from_metadata(
                _unique_id(seen_ids, group.path, _safe_name(key)),
                meta,
                text=value,
                context_lines=context_lines,
                fallback_source=key,
            )
        )
        meta = {}
        context_lines = []
    return document


CSV_COLUMNS = [
    "namespace",
    "clan",
    "source-language",
    "target-language",
    "version",
    "variant",
    "title",
    "info",
    "standard",
    "dependency",
    "group",
    "group-context",
    "group-type",
    "group-emotion",
    "group-max-width",
    "id",
    "source",
    "target",
    "type",
    "emotion",
    "status",
    "context",
    "max-width",
    "reference",
    "reviewer",
]


def _join_list(items: list[str]) -> str:
    return _join_pipe(items)


def _split_list(text: str | None) -> list[str]:
    return _split_pipe(text)


def _entry_to_row(document: CliffDocument, group: Group, entry: Entry) -> dict[str, str]:
    header = document.header
    return {
        "namespace": header.namespace,
        "clan": header.clan,
        "source-language": header.source_language,
        "target-language": header.target_language,
        "version": header.version or "",
        "variant": header.variant,
        "title": header.title or "",
        "info": header.info or "",
        "standard": header.standard or "",
        "dependency": _join_list(header.dependency),
        "group": group.path,
        "group-context": group.context or "",
        "group-type": group.type or "",
        "group-emotion": _join_list(group.emotion),
        "group-max-width": str(group.max_width) if group.max_width is not None else "",
        "id": entry.id,
        "source": entry.source or "",
        "target": entry.target or "",
        "type": entry.type or "",
        "emotion": _join_list(entry.emotion),
        "status": entry.status or "",
        "context": entry.context or "",
        "max-width": str(entry.max_width) if entry.max_width is not None else "",
        "reference": _join_list(entry.reference),
        "reviewer": entry.reviewer or "",
    }


def _simple_rows_to_document(
    rows: list[dict[str, Any]], *, clan: str = "imported"
) -> CliffDocument:
    document = CliffDocument(
        header=Header(
            namespace="csv",
            clan=clan,
            source_language="und",
            target_language="und",
        )
    )
    group_map: dict[str, Group] = {}
    seen_ids: set[str] = set()
    for row in rows:
        key = str(row.get("key") or row.get("id") or "")
        if not key:
            continue
        parts = key.split(".")
        entry_id = _safe_name(parts[-1])
        raw_path = ".".join(parts[:-1]) if len(parts) > 1 else "imported"
        group_path = _safe_group_path(raw_path)
        if group_path not in group_map:
            group = Group(path=group_path)
            document.groups.append(group)
            group_map[group_path] = group
        else:
            group = group_map[group_path]
        target = str(row.get("target") or "") or None
        group.entries.append(
            Entry(
                id=_unique_id(seen_ids, group_path, entry_id),
                source=str(row.get("source") or key) or None,
                target=target,
                type="sentence",
                status="translated" if target else "initial",
            )
        )
    return document


def _csv_width(value: str, column: str, line: int) -> int | None:
    """Read an integer width column, failing with a CLIFF error, not a ValueError.

    A CSV row whose fields have shifted (a stray comma, a dropped header) puts
    text where a number belongs. That is a malformed document, so it must
    surface as a CliffError naming the column and the line, not as a bare
    ValueError from int().
    """
    if not value:
        return None
    text_value = value.strip()
    if not text_value:
        return None
    if not text_value.isdigit():
        raise CliffError(
            f"CSV line {line}: column '{column}' expects an integer, found "
            f"{text_value[:40]!r}; the row's fields are probably shifted "
            "(a stray comma or a missing header)"
        )
    return int(text_value)


def _rows_to_document(rows: list[dict[str, Any]], *, clan: str = "imported") -> CliffDocument:
    if not rows:
        return CliffDocument()
    if "namespace" not in rows[0]:
        return _simple_rows_to_document(rows, clan=clan)
    first = rows[0]

    def text(row: dict[str, Any], key: str) -> str:
        value = row.get(key)
        return "" if value is None else str(value)

    header = Header(
        namespace=text(first, "namespace"),
        clan=text(first, "clan"),
        source_language=text(first, "source-language"),
        target_language=text(first, "target-language"),
        version=text(first, "version") or None,
        variant=text(first, "variant") or "standard",
        title=text(first, "title") or None,
        info=text(first, "info") or None,
        standard=text(first, "standard") or None,
        dependency=_split_list(text(first, "dependency")),
    )
    document = CliffDocument(header=header)
    group_map: dict[str, Group] = {}
    seen_ids: set[str] = set()

    for number, row in enumerate(rows, start=2):
        path = _safe_group_path(text(row, "group"))
        group_width = text(row, "group-max-width")
        if path not in group_map:
            group = Group(
                path=path,
                context=text(row, "group-context") or None,
                type=text(row, "group-type") or None,
                emotion=_split_list(text(row, "group-emotion")),
                max_width=_csv_width(group_width, "group-max-width", number),
            )
            document.groups.append(group)
            group_map[path] = group
        else:
            group = group_map[path]

        entry = Entry(
            id=_unique_id(seen_ids, path, _safe_name(text(row, "id"))),
            source=text(row, "source") or None,
            target=text(row, "target") or None,
            type=text(row, "type") or None,
            emotion=_split_list(text(row, "emotion")),
            status=text(row, "status") or None,
            context=text(row, "context") or None,
            max_width=_csv_width(text(row, "max-width"), "max-width", number),
            reference=_split_list(text(row, "reference")),
            reviewer=text(row, "reviewer") or None,
        )
        group.entries.append(entry)

    return document


def to_csv(document: CliffDocument) -> str:
    """Serialize a :class:`CliffDocument` to CSV text."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for group in document.groups:
        for entry in group.entries:
            writer.writerow(_entry_to_row(document, group, entry))
    return buffer.getvalue()


def from_csv(text: str, *, clan: str = "imported") -> CliffDocument:
    """Parse CSV text created by :func:`to_csv` into a document."""
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    return _rows_to_document(rows, clan=clan)


def _po_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _po_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _po_parse_value_token(token: str) -> str:
    token = token.strip()
    if not token.startswith('"'):
        raise CliffError(f"expected quoted PO string, got {token!r}")
    return _po_unescape(token[1:-1])


def _po_read_entry_lines(lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "msgctxt": None,
        "msgid": "",
        "msgid_plural": "",
        "msgstr": "",
        "msgstrs": [],
        "references": [],
        "translator_comments": [],
        "flags": [],
    }
    current: str | None = None
    for raw in lines:
        line = raw.strip()
        if line.startswith("#:"):
            result["references"].extend(part for part in line[2:].split() if part)
            continue
        if line.startswith("#."):
            result["translator_comments"].append(line[2:].strip())
            continue
        if line.startswith("#,"):
            result["flags"].extend(part.strip() for part in line[2:].split(",") if part.strip())
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgctxt "):
            current = "msgctxt"
            result["msgctxt"] = _po_parse_value_token(line[len("msgctxt ") :])
            continue
        if line.startswith("msgid "):
            current = "msgid"
            result["msgid"] = _po_parse_value_token(line[len("msgid ") :])
            continue
        if line.startswith("msgid_plural "):
            current = "msgid_plural"
            result["msgid_plural"] = _po_parse_value_token(line[len("msgid_plural ") :])
            continue
        if line.startswith("msgstr "):
            current = "msgstr"
            result["msgstr"] = _po_parse_value_token(line[len("msgstr ") :])
            continue
        if line.startswith("msgstr["):
            idx_text, _, rest = line[len("msgstr[") :].partition("]")
            try:
                idx = int(idx_text)
            except ValueError:
                continue
            value = _po_parse_value_token(rest.strip())
            while len(result["msgstrs"]) <= idx:
                result["msgstrs"].append("")
            result["msgstrs"][idx] = value
            current = None
            continue
        if line.startswith('"') and current is not None:
            result[current] += _po_parse_value_token(line)
    return result


def to_po(document: CliffDocument) -> str:
    """Serialize a CliffDocument to standard GNU gettext PO text.

    PO defines three metadata channels and CLIFF uses each for what it is meant
    for: msgctxt carries the disambiguating context key (the CLIFF group path
    and entry id), #: carries source references, and #. carries the extracted
    comments a translator reads. Attributes PO has no field for travel inside
    those extracted comments under a namespaced key, so they cannot be
    confused with a human comment.
    """
    header = document.header
    lines = [
        'msgid ""',
        'msgstr ""',
        f'"Language: {header.target_language}\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        "",
    ]
    for group in document.groups:
        for entry in group.entries:
            meta = _entry_metadata(group, entry)
            for reference in entry.reference:
                lines.append("#: " + reference)
            meta.pop("reference", None)
            context = meta.pop("context", None)
            if context:
                lines.append("#. " + context)
            for key, value in meta.items():
                lines.append(f"#. {CLIFF_META_PREFIX}{key}: {value}")
            msgctxt = group.path + "." + entry.id if group.path else entry.id
            lines.append("msgctxt " + _po_quote(msgctxt))
            lines.append("msgid " + _po_quote(entry.source or ""))
            lines.append("msgstr " + _po_quote(entry.target or ""))
            lines.append("")
    return "\n".join(lines) + "\n"


def _po_header_value(header_text: str, key: str) -> str | None:
    for line in header_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(key + ":"):
            return stripped[len(key) + 1 :].strip()
    return None


def _po_split_msgctxt(
    msgctxt: str,
    namespace: str,
    clan: str,
    fallback_index: int,
) -> tuple[str, str]:
    if not msgctxt:
        return "imported", f"entry-{fallback_index}"
    if msgctxt.startswith(f"{namespace}.{clan}."):
        rest = msgctxt[len(f"{namespace}.{clan}.") :]
    else:
        rest = msgctxt
    if "." in rest:
        parts = rest.split(".")
        return _safe_group_path(".".join(parts[:-1])), _safe_name(parts[-1])
    return "imported", _safe_name(rest)



def _icu_literal(text: str) -> str:
    """Quote ICU-significant braces so a generated message stays balanced."""
    return text.replace("{", "'{'").replace("}", "'}'")


def _po_plural_to_icu(singular: str, plural: str, forms: list[str]) -> tuple[str, str]:
    """Build a simple ICU plural source/target pair from PO plural forms."""
    if not forms:
        return singular or plural, ""
    if plural and len(forms) >= 2:
        source = (
            "{count, plural, one {"
            + _icu_literal(singular)
            + "} other {"
            + _icu_literal(plural)
            + "}}"
        )
    else:
        source = singular or plural
    if len(forms) >= 2:
        one, other = _icu_literal(forms[0]), _icu_literal(forms[1])
        target = "{count, plural, =0 {" + one + "} one {" + one + "} other {" + other + "}}"
    else:
        target = forms[0]
    return source, target


def from_po(text: str, *, clan: str = "imported") -> CliffDocument:
    """Parse standard GNU gettext PO text into a CLIFF document.

    CLIFF requires ``type`` and ``status``, so when the PO has no CLIFF metadata
    the importer uses sensible defaults (``type: sentence``; ``status`` based
    on whether a translation exists). ``type``/``status`` comments from CLIFF
    exports are still honored when present.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)

    header = Header(
        namespace="po",
        clan=clan,
        source_language="und",
        target_language="und",
    )
    document = CliffDocument(header=header)
    group_map: dict[str, Group] = {}
    seen_ids: set[str] = set()
    entry_index = 0

    for block_lines in blocks:
        data = _po_read_entry_lines(block_lines)
        # Only the PO header block has an empty msgid with no msgctxt. An entry
        # with an empty source but a real translation must not be swallowed.
        is_header = (
            not data["msgid"]
            and not data["msgctxt"]
            and (
                not data["msgstr"]
                or "Content-Type:" in data["msgstr"]
                or "Language:" in data["msgstr"]
                or "MIME-Version:" in data["msgstr"]
            )
        )
        if is_header:
            lang = _po_header_value(data["msgstr"], "Language")
            if lang:
                header.target_language = lang
            continue

        entry_index += 1
        msgctxt = data["msgctxt"] or ""
        group_path, entry_id = _po_split_msgctxt(
            msgctxt, header.namespace, header.clan, entry_index
        )
        if group_path not in group_map:
            group = Group(path=group_path)
            document.groups.append(group)
            group_map[group_path] = group
        else:
            group = group_map[group_path]

        # Extracted comments are PO's translator-context channel. A namespaced
        # line is a CLIFF attribute; anything else is a human comment and
        # therefore context. Nothing beyond what the file carries is added.
        meta, context_lines = _read_metadata_comment(
            "\n".join(data["translator_comments"])
        )

        source_value: str | None
        target_value: str | None
        if data["msgid_plural"] or data["msgstrs"]:
            source_value, target_value = _po_plural_to_icu(
                data["msgid"] or "",
                data["msgid_plural"] or "",
                data["msgstrs"],
            )
        else:
            source_value = data["msgid"] or None
            target_value = data["msgstr"] or None

        width = meta.get("max-width")
        entry = Entry(
            id=_unique_id(seen_ids, group.path, entry_id),
            source=source_value,
            target=target_value,
            type=meta.get("type") or "sentence",
            status=meta.get("status") or ("translated" if target_value else "initial"),
            emotion=_split_pipe(meta.get("emotion")),
            context=meta.get("context") or (" ".join(context_lines) or None),
            max_width=int(width) if width and width.isdigit() else None,
            reference=list(data["references"]),
            reviewer=meta.get("reviewer"),
        )
        group.entries.append(entry)

    return document


# XLIFF 2.0, 2.1 and 2.2 share one core namespace and are told apart by the
# version attribute. The glossary module arrived with 2.2 Part 2.
XLIFF_2_NS = "urn:oasis:names:tc:xliff:document:2.0"
XLIFF_METADATA_NS = "urn:oasis:names:tc:xliff:metadata:2.0"
XLIFF_GLOSSARY_NS = "urn:oasis:names:tc:xliff:glossary:2.0"
XLIFF_META_CATEGORY = "cliff"
XLIFF_NOTE_PREFIX = CLIFF_META_PREFIX
XLIFF_VERSIONS = ("2.0", "2.1", "2.2")
XLIFF_GLOSSARY_VERSION = "2.2"


def _x2(tag: str) -> str:
    """Qualify a tag name with the XLIFF 2 core namespace."""
    return f"{{{XLIFF_2_NS}}}{tag}"


def _mda(tag: str) -> str:
    """Qualify a tag name with the XLIFF metadata module namespace."""
    return f"{{{XLIFF_METADATA_NS}}}{tag}"


def _gls(tag: str) -> str:
    """Qualify a tag name with the XLIFF 2.2 glossary module namespace."""
    return f"{{{XLIFF_GLOSSARY_NS}}}{tag}"


def _add_xliff_metadata(parent: ET.Element, values: dict[str, str | None]) -> None:
    """Attach CLIFF fields through the XLIFF metadata module.

    XLIFF 2.x models tool-specific data with mda:metadata / mda:metaGroup /
    mda:meta, which is the channel the CLIFF specification names for type and
    context. The human-readable context is additionally written as a plain
    note, because that is what a translation editor shows to a translator.
    """
    present = {key: value for key, value in values.items() if value}
    if not present:
        return
    metadata = ET.SubElement(parent, _mda("metadata"))
    group = ET.SubElement(metadata, _mda("metaGroup"), {"category": XLIFF_META_CATEGORY})
    for key, value in present.items():
        meta = ET.SubElement(group, _mda("meta"), {"type": key})
        meta.text = value
    context = present.get("context")
    if context:
        notes = ET.SubElement(parent, _x2("notes"))
        note = ET.SubElement(notes, _x2("note"))
        note.text = context


def _read_xliff_metadata(parent: ET.Element | None) -> dict[str, str]:
    """Read CLIFF fields from an XLIFF element.

    The metadata module is authoritative. When it is absent the reader falls
    back to notes: a cliff:-categorised note from an older export, and finally
    a plain note, which in XLIFF is translator context and nothing else.
    """
    if parent is None:
        return {}
    values: dict[str, str] = {}
    for metadata in parent.findall(_mda("metadata")):
        for group in metadata.findall(_mda("metaGroup")):
            if (group.get("category") or XLIFF_META_CATEGORY) != XLIFF_META_CATEGORY:
                continue
            for meta in group.findall(_mda("meta")):
                key = meta.get("type") or ""
                if key:
                    values[key] = (meta.text or "").strip()

    containers = parent.findall(_x2("notes")) or [parent]
    for container in containers:
        for note in list(container.findall(_x2("note"))) + list(container.findall("note")):
            category = note.get("category") or ""
            text = (note.text or "").strip()
            if category.startswith(XLIFF_NOTE_PREFIX):
                values.setdefault(category[len(XLIFF_NOTE_PREFIX) :], text)
            elif text:
                values.setdefault("context", text)
    return values


def _add_glossary_module(file_el: ET.Element, document: CliffDocument) -> None:
    """Mirror a CLIFF glossary into the XLIFF 2.2 glossary module.

    A variant: glossary file is a terminology file, which XLIFF 2.2 Part 2
    models with gls:glossEntry / gls:term / gls:translation. The units stay in
    place so the round-trip keeps every CLIFF field.
    """
    entries = [(group, entry) for group, entry in document.entries() if entry.source]
    if not entries:
        return
    # Module elements precede notes and units in the XLIFF 2.x content model.
    glossary = ET.Element(_gls("glossary"))
    position = next(
        (index for index, child in enumerate(file_el) if child.tag == _x2("group")),
        len(file_el),
    )
    file_el.insert(position, glossary)
    for group, entry in entries:
        gloss_entry = ET.SubElement(
            glossary,
            _gls("glossEntry"),
            {"ref": f"#{document.canonical_id(group, entry)}"},
        )
        term = ET.SubElement(gloss_entry, _gls("term"), {"source": "cliff"})
        term.text = entry.source
        if entry.target is not None:
            translation = ET.SubElement(
                gloss_entry,
                _gls("translation"),
                {"id": entry.id, "source": "cliff"},
            )
            translation.text = entry.target
        context = effective_context(entry, group)
        if context:
            definition = ET.SubElement(gloss_entry, _gls("definition"), {"source": "cliff"})
            definition.text = context


def to_xliff(document: CliffDocument, *, version: str = "2.1") -> str:
    """Serialize a CliffDocument to XLIFF 2.x XML text.

    The specification maps CLIFF onto XLIFF 2.1/2.2: the dotted section path
    becomes the group id, each entry becomes a unit with one segment, and the
    CLIFF status maps directly onto the XLIFF segment state (both use
    initial/translated/reviewed/final). Fields XLIFF has no native slot for
    (type, emotion, context, max-width, reviewer, reference and the CLIFF
    header prose) travel as notes categorised with a cliff: prefix, so a
    round-trip through this converter is lossless.

    With version 2.2 a variant: glossary document additionally carries the
    XLIFF 2.2 glossary module, which is the standard representation of a
    terminology file.
    """
    if version not in XLIFF_VERSIONS:
        raise CliffError(
            f"unsupported XLIFF version {version!r}; expected one of "
            + ", ".join(XLIFF_VERSIONS)
        )
    ET.register_namespace("", XLIFF_2_NS)
    ET.register_namespace("mda", XLIFF_METADATA_NS)
    ET.register_namespace("gls", XLIFF_GLOSSARY_NS)
    header = document.header
    root = ET.Element(
        _x2("xliff"),
        {
            "version": version,
            "srcLang": header.source_language,
            "trgLang": header.target_language,
        },
    )
    original = f"{header.namespace}.{header.clan}"
    file_el = ET.SubElement(root, _x2("file"), {"id": original, "original": original})
    _add_xliff_metadata(
        file_el,
        {
            "version": header.version,
            "variant": header.variant if header.variant != "standard" else None,
            "title": header.title,
            "info": header.info,
            "standard": header.standard,
            "dependency": _join_pipe(header.dependency) if header.dependency else None,
        },
    )

    for group in document.groups:
        group_el = ET.SubElement(file_el, _x2("group"), {"id": group.path})
        _add_xliff_metadata(
            group_el,
            {
                "context": group.context,
                "type": group.type,
                "emotion": _join_pipe(group.emotion) if group.emotion else None,
                "max-width": str(group.max_width) if group.max_width is not None else None,
            },
        )
        for entry in group.entries:
            unit = ET.SubElement(group_el, _x2("unit"), {"id": entry.id})
            _add_xliff_metadata(
                unit,
                {
                    "type": entry.type,
                    "emotion": _join_pipe(entry.emotion) if entry.emotion else None,
                    "context": entry.context,
                    "max-width": str(entry.max_width) if entry.max_width is not None else None,
                    "reference": _join_pipe(entry.reference) if entry.reference else None,
                    "reviewer": entry.reviewer,
                },
            )
            segment = ET.SubElement(unit, _x2("segment"))
            if entry.status:
                segment.set("state", entry.status)
            source = ET.SubElement(segment, _x2("source"))
            source.text = entry.source or ""
            if entry.target is not None:
                target = ET.SubElement(segment, _x2("target"))
                target.text = entry.target

    if version == XLIFF_GLOSSARY_VERSION and header.variant == "glossary":
        _add_glossary_module(file_el, document)
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + xml + "\n"


def _find_element(parent: ET.Element, *tags: str) -> ET.Element | None:
    """First matching child. An element with no children is falsy, so the
    lookup must compare against None explicitly rather than use or-chaining.
    """
    for tag in tags:
        found = parent.find(tag)
        if found is not None:
            return found
    return None


def _xliff_units(group_el: ET.Element) -> list[tuple[ET.Element, ET.Element | None]]:
    """Yield (unit, segment) pairs for XLIFF 2 units and legacy 1.2 trans-units."""
    pairs: list[tuple[ET.Element, ET.Element | None]] = []
    for unit in group_el.findall(_x2("unit")):
        pairs.append((unit, unit.find(_x2("segment"))))
    for unit in group_el.findall("trans-unit"):
        pairs.append((unit, None))
    return pairs


def from_xliff(text: str, *, clan: str | None = None) -> CliffDocument:
    """Parse XLIFF into a CLIFF document.

    XLIFF 2.x produced by to_xliff round-trips losslessly. XLIFF 1.2 documents
    are still accepted so older exports keep working.
    """
    root = ET.fromstring(text)
    file_el = _find_element(root, _x2("file"), "file")
    if file_el is None:
        raise CliffError("missing <file> element in XLIFF")
    original = file_el.get("original") or file_el.get("id") or "imported"
    if "." in original:
        namespace, _, original_clan = original.partition(".")
    else:
        namespace, original_clan = "xliff", original

    legacy_header = _find_element(file_el, "header")
    header_notes = _read_xliff_metadata(file_el)
    header_notes.update(_read_xliff_metadata(legacy_header))
    header = Header(
        namespace=_safe_name(namespace, "xliff"),
        clan=_safe_name(clan if clan is not None else original_clan, "imported"),
        source_language=(
            root.get("srcLang") or file_el.get("source-language") or "und"
        ),
        target_language=(
            root.get("trgLang") or file_el.get("target-language") or "und"
        ),
        version=header_notes.get("version") or None,
        variant=header_notes.get("variant") or "standard",
        title=header_notes.get("title") or None,
        info=header_notes.get("info") or None,
        standard=header_notes.get("standard") or None,
        dependency=_split_pipe(header_notes.get("dependency")),
    )
    document = CliffDocument(header=header)
    body_el = _find_element(file_el, "body", _x2("body"))
    container = body_el if body_el is not None else file_el
    seen_ids: set[str] = set()

    # An XLIFF 2.2 glossary module marks the file as a terminology file even
    # when the CLIFF variant note is absent.
    glossary_el = _find_element(file_el, _gls("glossary"))
    if glossary_el is not None and header.variant == "standard":
        header.variant = "glossary"

    for group_el in list(container.findall(_x2("group"))) + list(container.findall("group")):
        group_notes = _read_xliff_metadata(group_el)
        group_width = group_notes.get("max-width")
        group = Group(
            path=_safe_group_path(group_el.get("id", "imported")),
            context=group_notes.get("context"),
            type=group_notes.get("type"),
            emotion=_split_pipe(group_notes.get("emotion")),
            max_width=int(group_width) if group_width else None,
        )
        document.groups.append(group)
        for unit, segment in _xliff_units(group_el):
            holder = segment if segment is not None else unit
            source_el = _find_element(holder, _x2("source"), "source")
            target_el = _find_element(holder, _x2("target"), "target")
            notes = _read_xliff_metadata(unit)
            target_text = target_el.text if target_el is not None else None
            state = (segment.get("state") if segment is not None else None) or unit.get("state")
            width = notes.get("max-width")
            entry = Entry(
                id=_unique_id(seen_ids, group.path, _safe_name(unit.get("id", ""))),
                source=source_el.text if source_el is not None else None,
                target=target_text,
                type=notes.get("type"),
                status=state or notes.get("status") or ("translated" if target_text else "initial"),
                context=notes.get("context"),
                emotion=_split_pipe(notes.get("emotion")),
                max_width=int(width) if width else None,
                reference=_split_pipe(notes.get("reference")),
                reviewer=notes.get("reviewer"),
            )
            if entry.type is None and group.type is None:
                entry.type = "sentence"
            group.entries.append(entry)

    if not document.entries() and glossary_el is not None:
        document.groups.append(_glossary_group(glossary_el, seen_ids))
    return document


def _glossary_group(glossary_el: ET.Element, seen_ids: set[str]) -> Group:
    """Build a CLIFF group from a standalone XLIFF 2.2 glossary module."""
    group = Group(path="glossary", type="noun-phrase")
    for index, gloss_entry in enumerate(glossary_el.findall(_gls("glossEntry")), start=1):
        term = _find_element(gloss_entry, _gls("term"))
        translation = _find_element(gloss_entry, _gls("translation"))
        definition = _find_element(gloss_entry, _gls("definition"))
        ref = (gloss_entry.get("ref") or "").lstrip("#")
        raw_id = translation.get("id") if translation is not None else None
        candidate = raw_id or (ref.rsplit(".", 1)[-1] if ref else f"term-{index}")
        target = translation.text if translation is not None else None
        group.entries.append(
            Entry(
                id=_unique_id(seen_ids, group.path, _safe_name(candidate, "term")),
                source=term.text if term is not None else None,
                target=target,
                status="translated" if target else "initial",
                context=definition.text if definition is not None else None,
            )
        )
    return group