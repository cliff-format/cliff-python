from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from .errors import CliffParseError, UnsupportedSpecVersion
from .identifiers import (
    Correction,
    is_name,
    is_tag,
    normalize_identifier,
    strip_line_terminator,
    unique_identifier,
)
from .model import CliffDocument, Entry, Group, Header
from .vocabulary import (
    STATUS_TAGS,
    TYPE_TAGS,
    VARIANT_TAGS,
    canonical_case,
)

VERSION_RE = re.compile(r"^\s*CLIFF\s+(1\.0|1\.1)\s*$")
#: A line that announces CLIFF with a number, but one this implementation does
#: not implement. Kept separate so the diagnostic can name the supported set.
UNSUPPORTED_VERSION_RE = re.compile(r"^\s*CLIFF\s+(\S+)\s*$", re.IGNORECASE)
#: The tolerant reading of the version line: spelling differences only.
TOLERANT_VERSION_RE = re.compile(r"^\s*cliff\s+(1\.(?:0|1)(?:\.\d+)*)\s*$", re.IGNORECASE)
SECTION_RE = re.compile(r"^\s*\[([^\[\]]*)\]\s*$")
ENTRY_RE = re.compile(r"^\s*<([^<>]*)>\s*$")
LANG_RE = re.compile(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$")

#: Versions this implementation implements, in canonical spelling order.
SUPPORTED_VERSIONS = ("1.0", "1.1")

#: The canonical version line a serializer writes for a new document.
CANONICAL_VERSION = "1.1"

#: The default version assumed by tolerant parsing when no version line exists.
TOLERANT_ASSUMED_VERSION = "1.1"

HEADER_KEYS = {
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
}
GROUP_KEYS = {"context", "type", "emotion", "max-width"}
ENTRY_KEYS = {
    "source",
    "target",
    "type",
    "emotion",
    "status",
    "context",
    "max-width",
    "reference",
    "reviewer",
}
STRING_KEYS = {"version", "title", "info", "standard", "source", "target", "context", "reviewer"}
LIST_KEYS = {"emotion", "dependency", "reference"}
NAME_KEYS = {"namespace", "clan"}
LANG_KEYS = {"source-language", "target-language"}
INT_KEYS = {"max-width"}
TAG_KEYS = {"variant", "type", "status"}

#: Which closed vocabulary each tag-typed key validates against. The tolerant
#: tag reader uses this to decide whether a differently cased spelling is a
#: fold or an error (specification Appendix C.2.3).
TAG_VOCABULARIES: dict[str, frozenset[str]] = {
    "variant": VARIANT_TAGS,
    "type": TYPE_TAGS,
    "status": STATUS_TAGS,
}

ESCAPES = {'"': '"', "'": "'", "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}

_LIST_HINTS = {
    "emotion": "emotion: [neutral]",
    "dependency": 'dependency: ["../terms/terms.zh-CN.cliff"]',
    "reference": 'reference: ["src/ui.cpp:12"]',
}

#: Resource limits (specification 19). They apply in strict and tolerant mode
#: alike and are configurable, so a hostile document cannot exhaust memory.
DEFAULT_MAX_LINES = 1_000_000
DEFAULT_MAX_LINE_LENGTH = 1 << 20  # 1 MiB
DEFAULT_MAX_STRING_LENGTH = 1 << 20  # 1 MiB

#: The resource limits accepted by :func:`parse` and :func:`load`.
class Limits(TypedDict, total=False):
    max_lines: int
    max_line_length: int
    max_string_length: int


def _normalize_lines(text: str) -> list[str]:
    if text.startswith("\ufeff"):
        text = text[1:]
    if "\r" in text:
        text = text.replace("\r\n", "\n")
        if "\r" in text:
            raise CliffParseError("bare CR is not a valid line ending")
    return text.split("\n")


def _is_ignorable(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def _starts_quote(text: str) -> bool:
    return text.startswith('"') or text.startswith("'")


def _unescape(text: str, quote: str) -> str:
    allowed = {'"', "\\", "n", "r", "t"} if quote == '"' else {"'", "\\", "n", "r", "t"}
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            if i + 1 >= len(text):
                raise CliffParseError("trailing backslash")
            nxt = text[i + 1]
            if nxt not in allowed:
                raise CliffParseError(f"unknown escape sequence \\{nxt}")
            out.append(ESCAPES[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_string_at(text: str) -> tuple[str, str]:
    if text.startswith('"'):
        quote = '"'
    elif text.startswith("'"):
        quote = "'"
    else:
        raise CliffParseError("expected a quoted string")

    i = 1
    out: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == quote:
            value = _unescape("".join(out), quote)
            return value, text[i + 1 :]
        if ch == "\\":
            if i + 1 >= len(text):
                raise CliffParseError("trailing backslash")
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch in "\n\r\t" or ord(ch) < 0x20:
            raise CliffParseError("raw control character inside string")
        out.append(ch)
        i += 1
    raise CliffParseError("unterminated string")


def _parse_adjacent_strings(text: str) -> str:
    text = text.strip()
    if not text:
        raise CliffParseError("empty value")
    parts: list[str] = []
    rest = text
    while rest:
        if not _starts_quote(rest):
            raise CliffParseError("expected a quoted string")
        value, after = _parse_string_at(rest)
        parts.append(value)
        rest = after.lstrip()
    return "".join(parts)


def _unquote_exactly(text: str) -> str:
    """Return the contents of a value that is exactly one quoted string."""
    text = text.strip()
    if not _starts_quote(text):
        raise CliffParseError("expected a quoted string")
    value, rest = _parse_string_at(text)
    if rest.strip():
        raise CliffParseError("unexpected content after the closing quote")
    return value


def _find_separator(text: str) -> int | None:
    """Index of the first "=" or ":" that sits outside a quoted string."""
    quote: str | None = None
    escaped = False
    for i, ch in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "=:":
            return i
    return None


def _parse_field_line(line: str) -> tuple[str, str]:
    idx = _find_separator(line)
    if idx is None:
        raise CliffParseError("expected 'key: value' or 'key = value' field")
    key = line[:idx].strip()
    value = line[idx + 1 :].strip()
    if not is_name(key):
        raise CliffParseError(
            f"invalid field name '{key}' (a name is one or more of A-Z a-z 0-9 _ -)"
        )
    return key, value


def _split_list_items(body: str) -> list[str]:
    """Split a list body on commas that sit outside quoted strings."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in body:
        if quote is not None:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if quote is not None:
        raise CliffParseError("unterminated string inside list")
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_tag(text: str, key: str) -> str:
    """Parse a fixed-vocabulary tag, which the grammar defines as a bare word.

    Tags are the one thing CLIFF 1.1 did not relax: the value must be a
    lowercase kebab-case word (specification 5.5). This function enforces the
    *shape* only, plus the two spellings the closed vocabulary itself defines,
    so that a word outside the vocabulary is reported by the validator as the
    ``vocabulary`` error the specification asks for, listing the allowed values
    (§12) rather than as a generic syntax error.
    """
    text = text.strip()
    if not text:
        raise CliffParseError("empty tag")
    if _starts_quote(text):
        raise CliffParseError(
            f"tag values are unquoted lowercase words; write {text.strip(chr(34) + chr(39))}"
            " without quotes"
        )
    if (
        not is_tag(text)
        and not LANG_RE.match(text)
        and text.lower() not in TAG_VOCABULARIES.get(key, frozenset())
    ):
        raise CliffParseError(
            f"{text!r} is not a valid tag (lowercase kebab-case required)", category="vocabulary"
        )
    return text


def _parse_list(text: str, key: str) -> list[str]:
    text = text.strip()
    if not text.startswith("["):
        raise CliffParseError(f"{key} must be a single-line list")
    if not text.endswith("]"):
        raise CliffParseError("unclosed list (closing bracket must be on the same line)")
    body = text[1:-1].strip()
    if not body:
        return []
    items: list[str] = []
    for part in _split_list_items(body):
        part = part.strip()
        if not part:
            raise CliffParseError("empty list item")
        if part.startswith("["):
            raise CliffParseError("nested lists are not allowed")
        if key in ("dependency", "reference"):
            if not _starts_quote(part):
                raise CliffParseError(f"{key} list items must be quoted strings")
            items.append(_unquote_exactly(part))
        elif key == "emotion":
            items.append(_parse_tag(part, "emotion"))
        elif _starts_quote(part):
            items.append(_unquote_exactly(part))
        else:
            items.append(_parse_tag(part, key))
    return items


def _check_extension_value(text: str) -> str:
    """Validate an x- extension value and return its raw text unchanged.

    Extension values are opaque to cliff_format: the spec requires parsers to ignore
    them without changing their meaning, so the raw source text is preserved
    and re-emitted verbatim by the serializer. Only well-formedness is checked.
    """
    text = text.strip()
    if not text:
        raise CliffParseError("empty value")
    if text.startswith("["):
        _parse_list(text, "extension")
    elif _starts_quote(text):
        _parse_adjacent_strings(text)
    elif not text.isdigit() and not is_name(text) and not LANG_RE.match(text):
        raise CliffParseError(f"{text!r} is not a valid string, list, integer, or name")
    return text


def _parse_scalar(text: str, key: str) -> Any:
    text = text.strip()
    if not text:
        raise CliffParseError("empty value")
    if _starts_quote(text):
        return _unquote_exactly(text)
    if key in LANG_KEYS:
        if not LANG_RE.match(text):
            raise CliffParseError(f"'{text}' is not a plausible BCP 47 language tag")
        return text
    if key in NAME_KEYS:
        if not is_name(text):
            raise CliffParseError(
                f"'{text}' is not a valid name (one or more of A-Z a-z 0-9 _ -)"
            )
        return text
    if key in INT_KEYS:
        if not text.isdigit() or int(text) <= 0:
            raise CliffParseError(f"'{text}' is not a positive integer")
        return int(text)
    if is_name(text):
        return text
    raise CliffParseError(f"'{text}' is not a valid name, string, or integer")


def _parse_value(text: str, key: str) -> Any:
    text = text.strip()
    if key in STRING_KEYS:
        return _parse_adjacent_strings(text)
    if key in LIST_KEYS:
        if not text.startswith("["):
            raise CliffParseError(
                f"{key} is a list-typed field and must be written as a list, "
                f"even for a single item (for example: {_LIST_HINTS[key]})"
            )
        return _parse_list(text, key)
    if key in TAG_KEYS:
        return _parse_tag(text, key)
    return _parse_scalar(text, key)


# ---------------------------------------------------------------------------
# tolerant parsing (specification Appendix C)
# ---------------------------------------------------------------------------


def _tolerant_correction(
    corrections: list[Correction],
    line: int,
    category: str,
    message: str,
    before: str = "",
    after: str = "",
) -> None:
    corrections.append(
        Correction(
            line=line,
            category=category,
            message=message,
            before=before,
            after=after,
        )
    )


def _tolerant_tag(text: str, key: str, line: int, corrections: list[Correction]) -> str:
    """Read a tag value in tolerant mode (Appendix C.2.3).

    Quotes are removed, and a spelling whose lowercase form is in the closed
    vocabulary is folded. Any other deviation stays an error: the tolerant
    parser never guesses a word (Appendix C.5), and a word that is not in the
    vocabulary is reported as the vocabulary error the specification asks for.
    """
    text = text.strip()
    if _starts_quote(text):
        unquoted = _unquote_exactly(text)
        _tolerant_correction(
            corrections,
            line,
            "tag-quote",
            f"{key}: removed the quotes around a tag value",
            before=text,
            after=unquoted,
        )
        text = unquoted
    allowed = TAG_VOCABULARIES.get(key)
    if is_tag(text) or (allowed is not None and text.lower() in allowed):
        folded = canonical_case(text, allowed) if allowed is not None else None
        if folded is not None and folded != text:
            _tolerant_correction(
                corrections,
                line,
                "casing",
                f"{key}: folded a tag to its lowercase spelling",
                before=text,
                after=folded,
            )
            return folded
        return text
    if allowed is not None and text.lower() not in allowed:
        raise CliffParseError(
            f"{key}: invalid tag '{text}'; allowed: {', '.join(sorted(allowed))}",
            category="vocabulary",
        )
    raise CliffParseError(f"{text!r} is not a valid tag (lowercase kebab-case required)")


def _tolerant_list_item(part: str, key: str, line: int, corrections: list[Correction]) -> str:
    """Read one list item in tolerant mode, unwrapping a quoted tag."""
    if key in ("dependency", "reference"):
        if not _starts_quote(part):
            raise CliffParseError(f"{key} list items must be quoted strings")
        return _unquote_exactly(part)
    if key == "emotion" or not _starts_quote(part):
        return _tolerant_tag(part, "emotion" if key == "emotion" else key, line, corrections)
    return _unquote_exactly(part)


def _tolerant_list(text: str, key: str, line: int, corrections: list[Correction]) -> list[str]:
    """Read a single-line list in tolerant mode.

    Nested brackets are flattened and their items taken; otherwise this is the
    strict reader with tolerant tag handling.
    """
    text = text.strip()
    if not text.startswith("["):
        raise CliffParseError(f"{key} must be a single-line list")
    if not text.endswith("]"):
        raise CliffParseError("unclosed list (closing bracket must be on the same line)")
    body = text[1:-1].strip()
    if not body:
        return []
    items: list[str] = []
    for part in _split_list_items(body):
        part = part.strip()
        if not part:
            raise CliffParseError("empty list item")
        if part.startswith("["):
            _tolerant_correction(
                corrections,
                line,
                "list-shape",
                f"{key}: flattened a nested list",
                before=part,
                after=part.strip("[]"),
            )
            items.extend(_tolerant_list(part, key, line, corrections))
            continue
        items.append(_tolerant_list_item(part, key, line, corrections))
    return items


def _tolerant_value(text: str, key: str, line: int, corrections: list[Correction]) -> Any:
    """Read any field value in tolerant mode (Appendix C.2.1, C.2.3)."""
    text = text.strip()
    if key in STRING_KEYS:
        return _parse_adjacent_strings(text)
    if key in LIST_KEYS:
        if text.startswith("["):
            return _tolerant_list(text, key, line, corrections)
        # Appendices C.2.1: a bare scalar in a list-typed field is a one-item
        # list; a comma-separated series is that many items.
        items = [
            _tolerant_list_item(part, key, line, corrections)
            for part in _split_list_items(text)
            if part.strip()
        ]
        if not items:
            raise CliffParseError(f"{key} list is empty")
        _tolerant_correction(
            corrections,
            line,
            "list-shape",
            f"{key}: accepted a bare value as a one-item list "
            f"(write it as {_LIST_HINTS[key]})",
            before=text,
            after="[" + ", ".join(items) + "]",
        )
        return items
    if key in TAG_KEYS:
        return _tolerant_tag(text, key, line, corrections)
    return _parse_scalar(text, key)


def _tolerant_merge(
    container: Any,
    key: str,
    parsed: Any,
    line: int,
    corrections: list[Correction],
) -> None:
    """Merge a repeated field instead of rejecting it (Appendix C.2.2)."""
    current = _current_value(container, key)
    if isinstance(parsed, list) and isinstance(current, list):
        _tolerant_correction(
            corrections,
            line,
            "field-repeat",
            f"{key}: appended a repeated field instead of rejecting it",
            before=str(current),
            after=str(current + parsed),
        )
        _append_list(container, key, parsed)
        return
    if isinstance(parsed, str) and isinstance(current, str) and current:
        _tolerant_correction(
            corrections,
            line,
            "field-repeat",
            f"{key}: concatenated a repeated string field (C-style, no inserted character)",
            before=current,
            after=current + parsed,
        )
        _set_multiline_string(container, key, parsed)
        return
    # Nothing to merge (an empty or absent previous value): keep the new one.
    _assign(container, key, parsed)


def _current_value(container: Any, key: str) -> Any:
    if isinstance(container, Header):
        if key == "dependency":
            return list(container.dependency)
        return getattr(container, key.replace("-", "_"), None)
    if isinstance(container, Group):
        if key == "emotion":
            return list(container.emotion)
        return getattr(container, key.replace("-", "_"), None)
    if isinstance(container, Entry):
        if key == "emotion":
            return list(container.emotion)
        if key == "reference":
            return list(container.reference)
        return getattr(container, key.replace("-", "_"), None)
    return None


@contextmanager
def _located(line: int, text: str) -> Iterator[None]:
    """Attach the current line number and source text to a parse error.

    Value-level helpers do not know where they are being called from, so the
    main loop enriches whatever they raise. Every CLIFF diagnostic has to carry
    a line number and the offending line.
    """
    try:
        yield
    except CliffParseError as exc:
        if not exc.line:
            exc.line = line
            exc.text = text
        raise


def _valid_group_path(path: str) -> bool:
    return bool(path) and all(is_name(segment) for segment in path.split("."))


def _set_multiline_string(container: Any, key: str, fragment: str) -> None:
    if isinstance(container, Header):
        if key in {"version", "title", "info", "standard"}:
            current = getattr(container, key)
            setattr(container, key, (current or "") + fragment)
    elif isinstance(container, Group):
        if key == "context":
            container.context = (container.context or "") + fragment
    elif isinstance(container, Entry):
        if key in {"source", "target", "context", "reviewer"}:
            current = getattr(container, key)
            setattr(container, key, (current or "") + fragment)


def _append_list(container: Any, key: str, items: list[str]) -> None:
    if isinstance(container, Header):
        if key == "dependency":
            container.dependency.extend(items)
    elif isinstance(container, Group):
        if key == "emotion":
            container.emotion.extend(items)
    elif isinstance(container, Entry):
        if key == "emotion":
            entry_items = container.emotion
            entry_items.extend(items)
        elif key == "reference":
            container.reference.extend(items)


def _assign_header(header: Header, key: str, value: str) -> None:
    if key.startswith("x-"):
        header.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    _set_header_value(header, key, parsed)


def _set_header_value(header: Header, key: str, parsed: Any) -> None:
    if key == "namespace":
        header.namespace = parsed
    elif key == "clan":
        header.clan = parsed
    elif key == "source-language":
        header.source_language = parsed
    elif key == "target-language":
        header.target_language = parsed
    elif key == "version":
        header.version = parsed
    elif key == "variant":
        header.variant = parsed
    elif key == "title":
        header.title = parsed
    elif key == "info":
        header.info = parsed
    elif key == "standard":
        header.standard = parsed
    elif key == "dependency":
        header.dependency = parsed
    else:  # pragma: no cover - guarded by HEADER_KEYS
        raise CliffParseError(f"unknown header key '{key}'", category="semantic")


def _assign_group(group: Group, key: str, value: str) -> None:
    if key.startswith("x-"):
        group.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    if key == "context":
        group.context = parsed
    elif key == "type":
        group.type = parsed
    elif key == "emotion":
        group.emotion = parsed
    elif key == "max-width":
        group.max_width = parsed
    else:  # pragma: no cover - guarded by GROUP_KEYS
        raise CliffParseError(f"key '{key}' is not allowed in group metadata", category="semantic")


def _assign_entry(entry: Entry, key: str, value: str) -> None:
    if key.startswith("x-"):
        entry.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    if key == "source":
        entry.source = parsed
    elif key == "target":
        entry.target = parsed
    elif key == "type":
        entry.type = parsed
    elif key == "emotion":
        entry.emotion = parsed
    elif key == "status":
        entry.status = parsed
    elif key == "context":
        entry.context = parsed
    elif key == "max-width":
        entry.max_width = parsed
    elif key == "reference":
        entry.reference = parsed
    elif key == "reviewer":
        entry.reviewer = parsed
    else:  # pragma: no cover - guarded by ENTRY_KEYS
        raise CliffParseError(f"unknown entry key '{key}'", category="semantic")


def _assign(container: Any, key: str, parsed: Any) -> None:
    """Install an already-parsed value into its container."""
    if isinstance(container, Header):
        _set_header_value(container, key, parsed)
    elif isinstance(container, Group):
        if key == "context":
            container.context = parsed
        elif key == "type":
            container.type = parsed
        elif key == "emotion":
            container.emotion = parsed
        elif key == "max-width":
            container.max_width = parsed
    elif isinstance(container, Entry):
        if key == "source":
            container.source = parsed
        elif key == "target":
            container.target = parsed
        elif key == "type":
            container.type = parsed
        elif key == "emotion":
            container.emotion = parsed
        elif key == "status":
            container.status = parsed
        elif key == "context":
            container.context = parsed
        elif key == "max-width":
            container.max_width = parsed
        elif key == "reference":
            container.reference = parsed
        elif key == "reviewer":
            container.reviewer = parsed


def _check_limits(
    lines: list[str],
    *,
    max_lines: int,
    max_line_length: int,
) -> None:
    """Enforce the document-level resource limits of specification 19."""
    if len(lines) > max_lines:
        raise CliffParseError(
            f"document has {len(lines)} lines, which exceeds the limit of {max_lines}",
            category="semantic",
        )
    for idx, line in enumerate(lines, start=1):
        if len(line) > max_line_length:
            raise CliffParseError(
                f"line is {len(line)} characters long, which exceeds the limit "
                f"of {max_line_length}",
                line=idx,
                text=line[:120],
                category="semantic",
            )


def _split_version_line(idx: int, raw: str, body: str) -> str:
    """Return the declared version of a version line, or raise."""
    match = VERSION_RE.match(body)
    if match:
        return match.group(1)
    unsupported = UNSUPPORTED_VERSION_RE.match(body)
    if unsupported:
        declared = unsupported.group(1)
        raise UnsupportedSpecVersion(
            f"unsupported CLIFF version '{declared}'; this implementation "
            f"implements {', '.join(SUPPORTED_VERSIONS)}",
            declared=declared,
            supported=SUPPORTED_VERSIONS,
            line=idx,
            text=raw,
        )
    raise CliffParseError(
        "version line 'CLIFF 1.1' must be the first non-blank, non-comment line",
        line=idx,
        text=raw,
    )


def _tolerant_version_line(idx: int, raw: str, corrections: list[Correction]) -> str:
    """Read the version line in tolerant mode (Appendix C.2.6).

    Only the *spelling* of the line is tolerated. The version number itself is
    never inferred from the document's content, and an unimplemented version is
    still rejected: the caller has already established that the line announces
    a version this implementation might implement.
    """
    match = TOLERANT_VERSION_RE.match(raw)
    if match is None:
        return _split_version_line(idx, raw, raw.strip())
    declared = match.group(1)
    minor = ".".join(declared.split(".")[:2])
    if raw.strip() != f"CLIFF {minor}":
        _tolerant_correction(
            corrections,
            idx,
            "version",
            "accepted a differently-spelled version line",
            before=raw.strip(),
            after=f"CLIFF {minor}",
        )
    return minor


def _check_string_length(value: str, line: int, limit: int) -> None:
    if len(value) > limit:
        raise CliffParseError(
            f"string is {len(value)} characters long, which exceeds the limit of {limit}",
            line=line,
            category="semantic",
        )


def parse(
    text: str,
    *,
    path: str | Path | None = None,
    tolerant: bool = False,
    corrections: list[Correction] | None = None,
    max_lines: int = DEFAULT_MAX_LINES,
    max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
) -> CliffDocument:
    """Parse CLIFF text into a :class:`CliffDocument`.

    With ``tolerant=False`` (the default) the strict grammar applies: anything
    the specification rejects is a :class:`CliffParseError`. With
    ``tolerant=True`` the documented relaxations of specification Appendix C are
    applied instead, and every repair is recorded — pass a list as
    ``corrections`` to collect them, or read ``document.corrections``. The
    tolerant path never guesses missing data, vocabulary, or structure: the
    situations listed in Appendix C.5 still raise.

    Semantic validation is intentionally separate; use
    :func:`cliff_format.validate` for the full validator.
    """
    doc = CliffDocument(path=Path(path) if path is not None else None)
    collected: list[Correction] = corrections if corrections is not None else []
    doc.corrections = collected
    lines = _normalize_lines(text)
    _check_limits(lines, max_lines=max_lines, max_line_length=max_line_length)

    seen_version = False
    current_group: Group | None = None
    current_entry: Entry | None = None
    last_container: Any = None
    last_key: str | None = None
    seen_header: set[str] = set()
    seen_group: set[str] = set()
    seen_entry: set[str] = set()
    seen_paths: set[str] = set()
    seen_entry_ids: set[str] = set()
    seen_canonical: set[str] = set()

    for idx, raw in enumerate(lines, start=1):
        line, _terminator, extra = strip_line_terminator(raw)
        if extra:
            raise CliffParseError(
                "at most one trailing ',' or ';' is allowed on a line",
                line=idx,
                text=raw,
            )
        if _is_ignorable(line):
            last_container = None
            last_key = None
            continue

        if not seen_version:
            if tolerant:
                if TOLERANT_VERSION_RE.match(line) or UNSUPPORTED_VERSION_RE.match(line):
                    doc.spec_version = _tolerant_version_line(idx, raw, collected)
                    seen_version = True
                    continue
                # Not a version line at all: leave it for the field handling
                # below and register the missing version at the end.
            else:
                doc.spec_version = _split_version_line(idx, raw, line)
                seen_version = True
                continue

        section = SECTION_RE.match(line)
        if section:
            group_path = section.group(1).strip()
            if tolerant:
                original = group_path
                group_path = _tolerant_identifier_path(
                    group_path, collected, seen_paths
                )
                if group_path != original:
                    _tolerant_correction(
                        collected,
                        idx,
                        "name-normalized",
                        "normalized a group path",
                        before=original,
                        after=group_path,
                    )
            elif not _valid_group_path(group_path):
                # A bare list continuation looks exactly like a section line, so
                # the bracket content decides: only a valid group path is a
                # section, and anything else continues an open list field.
                if not (last_container is not None and last_key in LIST_KEYS):
                    raise CliffParseError(
                        f"invalid group path '[{group_path}]'; segments must be names "
                        "(one or more of A-Z a-z 0-9 _ -)",
                        line=idx,
                        category="id",
                        text=raw,
                    )
            if _valid_group_path(group_path):
                if group_path in seen_paths:
                    if tolerant:
                        base = group_path
                        group_path = unique_identifier(group_path, seen_paths)
                        _tolerant_correction(
                            collected,
                            idx,
                            "id-collision",
                            "disambiguated a duplicate section path "
                            f"(was already declared as '[{base}]')",
                            before=base,
                            after=group_path,
                        )
                    else:
                        # The duplicate is reported by the validator, which has
                        # the line and the canonical IDs; parsing continues so
                        # the whole document can be checked at once.
                        pass
                else:
                    seen_paths.add(group_path)
                current_group = Group(path=group_path, line=idx)
                doc.groups.append(current_group)
                current_entry = None
                seen_group = set()
                last_container = None
                last_key = None
                continue
            if tolerant:
                raise CliffParseError(
                    f"invalid group path '[{group_path}]'; segments must be names "
                    "(one or more of A-Z a-z 0-9 _ -)",
                    line=idx,
                    category="id",
                    text=raw,
                )

        entry = ENTRY_RE.match(line)
        if entry:
            if current_group is None:
                raise CliffParseError(
                    "entry declared before any [group] section",
                    line=idx,
                    text=raw,
                )
            entry_id = entry.group(1)
            if tolerant:
                original = entry_id.strip()
                if _starts_quote(original):
                    entry_id = _unquote_exactly(original)
                    _tolerant_correction(
                        collected,
                        idx,
                        "name-quote",
                        "removed the quotes around an entry id",
                        before=original,
                        after=entry_id,
                    )
                # Compare against the value *after* unquoting, so one line
                # produces one repair rather than two.
                unquoted = entry_id
                entry_id = normalize_identifier(entry_id, kind="entry")
                if entry_id != unquoted:
                    _tolerant_correction(
                        collected,
                        idx,
                        "name-normalized",
                        "normalized an entry id",
                        before=unquoted,
                        after=entry_id,
                    )
            elif not is_name(entry_id):
                raise CliffParseError(
                    f"invalid entry id '{entry_id}'; a name is one or more of "
                    "A-Z a-z 0-9 _ -",
                    line=idx,
                    category="id",
                    text=raw,
                )
            if entry_id in seen_entry_ids:
                if tolerant:
                    base = entry_id
                    entry_id = unique_identifier(entry_id, seen_entry_ids)
                    _tolerant_correction(
                        collected,
                        idx,
                        "id-collision",
                        f"disambiguated a duplicate entry id '<{base}>'",
                        before=base,
                        after=entry_id,
                    )
                else:
                    # Duplicate ids are a hard error, but it is the validator
                    # that reports both occurrences and both canonical IDs, so
                    # keep the id as written and let it decide.
                    pass
            else:
                seen_entry_ids.add(entry_id)
            current_entry = Entry(id=entry_id, line=idx)
            assert current_group is not None
            current_group.entries.append(current_entry)
            canonical = doc.canonical_id(current_group, current_entry)
            if canonical in seen_canonical and tolerant:
                base_id = current_entry.id
                current_entry.id = unique_identifier(base_id, seen_entry_ids)
                _tolerant_correction(
                    collected,
                    idx,
                    "id-collision",
                    f"disambiguated a duplicate canonical id '{canonical}'",
                    before=base_id,
                    after=current_entry.id,
                )
            seen_canonical.add(doc.canonical_id(current_group, current_entry))
            seen_entry = set()
            last_container = None
            last_key = None
            continue
        if last_container is not None and last_key is not None:
            stripped = line.strip()
            if last_key in STRING_KEYS and _starts_quote(stripped):
                with _located(idx, raw):
                    fragment = _parse_adjacent_strings(stripped)
                _check_string_length(fragment, idx, max_string_length)
                _set_multiline_string(last_container, last_key, fragment)
                continue
            if last_key in LIST_KEYS and stripped.startswith("["):
                with _located(idx, raw):
                    items = (
                        _tolerant_list(stripped, last_key, idx, collected)
                        if tolerant
                        else _parse_list(stripped, last_key)
                    )
                _append_list(last_container, last_key, items)
                continue
            if _starts_quote(stripped) or stripped.startswith("["):
                raise CliffParseError(
                    f"continuation line does not match the preceding '{last_key}' field",
                    line=idx,
                    text=raw,
                )

        with _located(idx, raw):
            key, value_text = _parse_field_line(line)

        container: Any
        scope: str
        if current_group is None:
            container = doc.header
            scope = "header"
        elif current_entry is not None:
            container = current_entry
            scope = "entry"
        else:
            container = current_group
            scope = "group"

        seen = (
            seen_header
            if scope == "header"
            else (seen_entry if scope == "entry" else seen_group)
        )
        allowed = (
            HEADER_KEYS
            if scope == "header"
            else (ENTRY_KEYS if scope == "entry" else GROUP_KEYS)
        )

        if not tolerant:
            if key in seen:
                raise CliffParseError(
                    f"{scope} field '{key}' may appear at most once "
                    "(CLIFF has no repeatable fields)",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            if key not in allowed and not key.startswith("x-"):
                raise CliffParseError(
                    f"unknown {scope} key '{key}'; known keys: {', '.join(sorted(allowed))}",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            seen.add(key)
            with _located(idx, raw):
                if scope == "header":
                    _assign_header(doc.header, key, value_text)
                elif scope == "entry":
                    assert current_entry is not None
                    _assign_entry(current_entry, key, value_text)
                else:
                    assert current_group is not None
                    _assign_group(current_group, key, value_text)
            last_container = container
            last_key = key
            continue

        # Tolerant path: repeatable fields merge, and every repair is recorded.
        if key not in allowed and not key.startswith("x-"):
            raise CliffParseError(
                f"unknown {scope} key '{key}'; known keys: {', '.join(sorted(allowed))}",
                line=idx,
                category="semantic",
                text=raw,
            )
        with _located(idx, raw):
            parsed = (
                _check_extension_value(value_text)
                if key.startswith("x-")
                else _tolerant_value(value_text, key, idx, collected)
            )
        if isinstance(parsed, str):
            _check_string_length(parsed, idx, max_string_length)
        if key in seen:
            with _located(idx, raw):
                _tolerant_merge(container, key, parsed, idx, collected)
        else:
            seen.add(key)
            with _located(idx, raw):
                _assign(container, key, parsed)
        last_container = container
        last_key = key

    if not seen_version:
        if not tolerant:
            raise CliffParseError("empty file")
        _tolerant_correction(
            collected,
            0,
            "version",
            "no version line found; assumed the current specification version",
            before="",
            after=f"CLIFF {TOLERANT_ASSUMED_VERSION}",
        )
        doc.spec_version = TOLERANT_ASSUMED_VERSION

    return doc


def _tolerant_identifier_path(
    path: str,
    corrections: list[Correction],
    seen_paths: set[str],
) -> str:
    """Normalize a dotted group path in tolerant mode (Appendix C.2.5)."""
    segments = [normalize_identifier(part, kind="group") for part in path.split(".")]
    segments = [seg for seg in segments if seg]
    if not segments:
        segments = ["group"]
    return ".".join(segments)


def parse_tolerant(
    text: str,
    *,
    path: str | Path | None = None,
    **limits: Any,
) -> tuple[CliffDocument, list[Correction]]:
    """Parse in tolerant mode and return ``(document, corrections)``.

    Convenience wrapper around :func:`parse` for the common case where the
    caller wants the repair report next to the document.
    """
    corrections: list[Correction] = []
    document = parse(text, path=path, tolerant=True, corrections=corrections, **limits)
    return document, corrections


def load(
    path: str | Path,
    *,
    tolerant: bool = False,
    corrections: list[Correction] | None = None,
    **limits: Any,
) -> CliffDocument:
    """Read and parse a ``.cliff`` file from disk."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CliffParseError(f"file is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise CliffParseError(f"cannot read file: {exc}") from exc
    return parse(text, path=p, tolerant=tolerant, corrections=corrections, **limits)
