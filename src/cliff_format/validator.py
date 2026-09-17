from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .errors import CliffParseError
from .identifiers import (
    Correction,
    has_style_obligation,
    is_style_identifier,
    strip_line_terminator,
)
from .model import CliffDocument, Entry, Group, ValidationIssue
from .parser import parse
from .vocabulary import (
    EMOTION_TAGS,
    GLOSSARY_TYPES,
    SPEECH_TYPES,
    STATUS_TAGS,
    TYPE_TAGS,
)

# Re-exported for compatibility: these sets were defined here before CLIFF 1.1
# moved them into `vocabulary`, and callers import them from the validator.
__all__ = [
    "EMOTION_TAGS",
    "GLOSSARY_TYPES",
    "SPEECH_TYPES",
    "STATUS_TAGS",
    "TYPE_TAGS",
    "ADVISORY_CATEGORIES",
    "effective_context",
    "effective_emotion",
    "effective_max_width",
    "effective_type",
    "validate",
    "validate_document",
]

# A directory or file-name segment that plausibly is a BCP 47 tag: a 2-3 letter
# primary subtag optionally followed by letter/digit subtags. Word-like names
# such as "valid" or "quality" are deliberately not language tags. The
# two-letter case ("en") matters: a project may use a bare primary subtag
# directory.
LANGUAGE_DIR_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")

#: Categories that are reported without making a document invalid.
ADVISORY_CATEGORIES = frozenset({"warning", "extension", "correction", "style"})

#: The recommended file-name shapes of `style/README.md`, used by `--style`.
STYLE_KEBAB_GROUP_RE = re.compile(r"^[a-z][a-z0-9-]*$")
STYLE_PASCAL_GROUP_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _brace_balance(text: str, line: int) -> list[ValidationIssue]:
    if "{" not in text and "}" not in text:
        return []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return [
                    ValidationIssue(
                        line=line,
                        category="icu",
                        message="unmatched closing brace '}' inside string",
                        text=text,
                    )
                ]
        i += 1
    if depth != 0:
        return [
            ValidationIssue(
                line=line,
                category="icu",
                message=f"unbalanced ICU braces: {depth} unclosed '{{'",
                text=text,
            )
        ]
    return []


ZERO_WIDTH_CATEGORIES = frozenset({"Mn", "Mc", "Me", "Cf", "Zl", "Zp"})
WIDE_EAST_ASIAN_WIDTHS = frozenset({"W", "F"})
ZWJ = "\u200d"
VARIATION_SELECTOR_16 = "\ufe0f"


def _is_emoji_presentation(ch: str, following: str) -> bool:
    """Whether ch renders as a two-cell emoji glyph in this context.

    Characters in the emoji planes carry emoji presentation by default. A
    text-presentation symbol becomes emoji only when variation selector 16
    follows it, which is why a plain letter followed by U+FE0F stays one cell.
    """
    if 0x1F000 <= ord(ch) <= 0x1FAFF:
        return True
    return following.startswith(VARIATION_SELECTOR_16) and unicodedata.category(ch) == "So"


def _display_cells(text: str) -> int:
    """Rendered display width of text in cells, per specification 15.

    East Asian Wide/Fullwidth and emoji count 2 cells, combining marks,
    variation selectors and other zero-width characters count 0, and a ZWJ
    sequence counts as the single 2-cell glyph it renders as.
    """
    total = 0
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if unicodedata.category(ch) in ZERO_WIDTH_CATEGORIES:
            index += 1
            continue
        if _is_emoji_presentation(ch, text[index + 1 :]):
            total += 2
            index += 1
            # A ZWJ sequence renders as one glyph: skip its remaining members.
            while index + 1 < length and text[index] == ZWJ:
                index += 2
            continue
        total += 2 if unicodedata.east_asian_width(ch) in WIDE_EAST_ASIAN_WIDTHS else 1
        index += 1
    return total


def effective_max_width(entry: Entry, group: Group) -> int | None:
    """Effective max-width: the entry value overrides the group value."""
    return entry.max_width if entry.max_width is not None else group.max_width


def effective_type(entry: Entry, group: Group) -> str | None:
    """Effective type: the entry value overrides the group value."""
    return entry.type if entry.type is not None else group.type


def effective_emotion(entry: Entry, group: Group) -> list[str]:
    """Effective emotion list.

    The entry value overrides the group value (lists never merge). When
    neither is present the default is derived from the effective type:
    speech types default to neutral, every other type to objective.
    """
    if entry.emotion:
        return list(entry.emotion)
    if group.emotion:
        return list(group.emotion)
    resolved = effective_type(entry, group)
    return ["neutral"] if resolved in SPEECH_TYPES else ["objective"]


def effective_context(entry: Entry, group: Group) -> str | None:
    """Effective context: the group value followed by the entry value.

    The two are joined with a single space when both exist, per
    specification 9. Returns None when neither carries context.
    """
    parts = [part for part in (group.context, entry.context) if part]
    return " ".join(parts) if parts else None


def _bad_tag(key: str, value: str, allowed: set[str] | frozenset[str]) -> str:
    return f"{key}: invalid tag '{value}'; allowed: {', '.join(sorted(allowed))}"


def _check_extensions(
    extensions: dict[str, str],
    line: int,
    scope: str,
) -> list[ValidationIssue]:
    """Warn about x- extension fields, as strict validators are required to."""
    return [
        ValidationIssue(
            line=line,
            category="extension",
            message=f"unknown {scope} extension field '{key}' is ignored",
            text=f"{key}: {extensions[key]}",
        )
        for key in sorted(extensions)
    ]


def _check_layout(document: CliffDocument) -> list[ValidationIssue]:
    """Check the file layout against the header, per specification 11.3.

    In CLIFF 1.1 the layout is a **recommendation**, so every finding here is a
    warning by default: a file keeps its identity in the header whether or not
    its name agrees. Callers that want the convention enforced pass
    ``check_layout=True`` to :func:`validate`, which promotes these findings to
    errors (the specification permits an explicit opt-in strict mode and
    requires the mode to be visible rather than accidental).

    Folder layout is ``<target-language>/<clan>.cliff`` and flat layout is
    ``<clan>.<target-language>.cliff``. A file matching neither shape is still
    valid and simply skips this check.
    """
    path = document.path
    header = document.header
    if path is None or not header.clan or not header.target_language:
        return []

    issues: list[ValidationIssue] = []
    stem = path.name[: -len(".cliff")] if path.name.endswith(".cliff") else path.stem
    parent = path.parent.name
    target = header.target_language.lower()

    if LANGUAGE_DIR_RE.match(parent):
        if parent.lower() != target:
            issues.append(
                ValidationIssue(
                    line=0,
                    category="layout",
                    message=(
                        f"folder layout mismatch: directory '{parent}' does not match "
                        f"target-language '{header.target_language}'"
                    ),
                    text=str(path),
                )
            )
        if stem != header.clan:
            issues.append(
                ValidationIssue(
                    line=0,
                    category="layout",
                    message=(
                        f"folder layout mismatch: file name '{stem}' does not match "
                        f"clan '{header.clan}'"
                    ),
                    text=str(path),
                )
            )
        return issues

    clan, dot, language = stem.partition(".")
    if dot and LANGUAGE_DIR_RE.match(language):
        if clan != header.clan or language.lower() != target:
            issues.append(
                ValidationIssue(
                    line=0,
                    category="layout",
                    message=(
                        f"flat layout mismatch: '{stem}.cliff' does not match header "
                        f"clan '{header.clan}' and target-language "
                        f"'{header.target_language}'"
                    ),
                    text=str(path),
                )
            )
    return issues


def _check_style(document: CliffDocument) -> list[ValidationIssue]:
    """Report deviations from ``style/README.md`` as warnings.

    Style is informative (specification 10.1), so nothing here is an error. The
    check exists so a project can opt into enforcing its own convention without
    asking the format's grammar to enforce it for everyone.
    """
    issues: list[ValidationIssue] = []

    def note_identifier(line: int, kind: str, value: str, text: str = "") -> None:
        if not value or is_style_identifier(value) or not has_style_obligation(value):
            return
        issues.append(
            ValidationIssue(
                line=line,
                category="style",
                message=(
                    f"{kind} '{value}' is valid CLIFF but does not follow "
                    "style/README.md (recommended: kebab-case or PascalCase, not mixed)"
                ),
                text=text or value,
            )
        )

    note_identifier(0, "namespace", document.header.namespace)
    note_identifier(0, "clan", document.header.clan)
    for group in document.groups:
        for segment in group.path.split("."):
            note_identifier(group.line, "group segment", segment, f"[{group.path}]")
        for entry in group.entries:
            note_identifier(entry.line, "entry id", entry.id, f"<{entry.id}>")
    return issues


def _check_terminator_style(document: CliffDocument, text: str) -> list[ValidationIssue]:
    """Report trailing ``,`` / ``;`` terminators as a style deviation.

    The terminator is legal CLIFF 1.1 syntax (specification 5.6) and means
    nothing, so a document that uses it is valid; the style guide recommends
    not writing it, and this check says so.
    """
    issues: list[ValidationIssue] = []
    for index, raw in enumerate(text.split("\n"), start=1):
        _, terminators, _ = strip_line_terminator(raw)
        if terminators:
            issues.append(
                ValidationIssue(
                    line=index,
                    category="style",
                    message=(
                        f"line ends with a '{terminators[-1]}' terminator; CLIFF 1.1 accepts "
                        "it but style/README.md recommends not writing it"
                    ),
                    text=raw.strip(),
                )
            )
    return issues


def _corrections_as_issues(corrections: list[Correction]) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            line=correction.line,
            category="correction",
            message=correction.detail(),
            text=correction.before or correction.after,
        )
        for correction in corrections
    ]


def validate_document(
    document: CliffDocument,
    *,
    check_width: bool = False,
    check_layout: bool = False,
    style: bool = False,
) -> list[ValidationIssue]:
    """Validate a parsed CliffDocument and return every issue it has.

    ``check_layout`` promotes the layout recommendations of specification 11.3
    from warnings to errors. ``style`` adds ``style``-category warnings for
    identifier and terminator habits; it never turns one into an error.
    """
    issues: list[ValidationIssue] = []
    header = document.header

    for key in ("namespace", "clan", "source_language", "target_language"):
        value = getattr(header, key)
        if not value:
            issues.append(
                ValidationIssue(
                    line=0,
                    category="semantic",
                    message=f"missing required header field '{key.replace('_', '-')}'",
                )
            )

    if header.variant not in ("standard", "glossary"):
        issues.append(
            ValidationIssue(
                line=0,
                category="vocabulary",
                message=_bad_tag("variant", header.variant, {"standard", "glossary"}),
            )
        )

    # Specification 13.1: a standard file must carry at least one entry.
    if header.variant == "standard" and not document.entries():
        issues.append(
            ValidationIssue(
                line=0,
                category="warning",
                message="standard variant file has no entries",
            )
        )

    for issue in _check_layout(document):
        issues.append(
            ValidationIssue(
                line=issue.line,
                category="semantic" if check_layout else "warning",
                message=issue.message
                + ("" if check_layout else " (layout is a recommendation in CLIFF 1.1)"),
                text=issue.text,
            )
        )
    issues.extend(_check_extensions(header.extensions, 0, "header"))
    issues.extend(_corrections_as_issues(document.corrections))

    seen_paths: set[str] = set()
    first_entry: dict[str, tuple[int, str]] = {}
    seen_canonical: set[str] = set()

    for group in document.groups:
        if group.path in seen_paths:
            issues.append(
                ValidationIssue(
                    line=group.line,
                    category="id",
                    message=f"duplicate section path '[{group.path}]'",
                    text=f"[{group.path}]",
                )
            )
        seen_paths.add(group.path)

        if group.type is not None and group.type not in TYPE_TAGS:
            issues.append(
                ValidationIssue(
                    line=group.line,
                    category="vocabulary",
                    message=_bad_tag("type", group.type, TYPE_TAGS),
                    text=group.type,
                )
            )
        for emotion in group.emotion:
            if emotion not in EMOTION_TAGS:
                issues.append(
                    ValidationIssue(
                        line=group.line,
                        category="vocabulary",
                        message=_bad_tag("emotion", emotion, EMOTION_TAGS),
                        text=emotion,
                    )
                )
        if group.context is not None:
            issues.extend(_brace_balance(group.context, group.line))
        issues.extend(_check_extensions(group.extensions, group.line, "group"))

        for entry in group.entries:
            # Specification 10.2: report both conflicting entries and both
            # canonical IDs, and never let one silently win.
            canonical = document.canonical_id(group, entry)
            if entry.id in first_entry:
                first_line, first_canonical = first_entry[entry.id]
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="id",
                        message=(
                            f"duplicate entry id '{entry.id}': also declared on line "
                            f"{first_line}; conflicting canonical IDs "
                            f"'{first_canonical}' and '{canonical}'"
                        ),
                        text=f"<{entry.id}>",
                    )
                )
            else:
                first_entry[entry.id] = (entry.line, canonical)
            if canonical in seen_canonical:
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="id",
                        message=f"duplicate canonical id '{canonical}'",
                        text=f"<{entry.id}>",
                    )
                )
            seen_canonical.add(canonical)

            if entry.source is None:
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="semantic",
                        message=f"entry '{entry.id}' is missing required field 'source'",
                    )
                )
            if entry.status is None:
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="semantic",
                        message=f"entry '{entry.id}' is missing required field 'status'",
                    )
                )
            resolved_type = effective_type(entry, group)
            if resolved_type is None:
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="semantic",
                        message=(
                            f"entry '{entry.id}' is missing required field 'type' "
                            "and the group has no type"
                        ),
                    )
                )
            elif resolved_type not in TYPE_TAGS:
                issues.append(
                    ValidationIssue(
                        line=entry.line,
                        category="vocabulary",
                        message=_bad_tag("type", resolved_type, TYPE_TAGS),
                        text=resolved_type,
                    )
                )

            for emotion in entry.emotion:
                if emotion not in EMOTION_TAGS:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="vocabulary",
                            message=_bad_tag("emotion", emotion, EMOTION_TAGS),
                            text=emotion,
                        )
                    )

            if entry.status is not None:
                if entry.status not in STATUS_TAGS:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="vocabulary",
                            message=_bad_tag("status", entry.status, STATUS_TAGS),
                            text=entry.status,
                        )
                    )
                if entry.status in ("translated", "reviewed", "final") and entry.target is None:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="semantic",
                            message=f"status '{entry.status}' requires a target field",
                        )
                    )
                if entry.status == "initial" and entry.target is not None:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="warning",
                            message="target is present but status is 'initial'",
                        )
                    )

            for key in ("source", "target", "context", "reviewer"):
                value = getattr(entry, key)
                if value is not None:
                    issues.extend(_brace_balance(value, entry.line))
            issues.extend(_check_extensions(entry.extensions, entry.line, "entry"))

            if check_width:
                max_width = effective_max_width(entry, group)
                if max_width is not None and entry.target is not None:
                    cells = _display_cells(entry.target)
                    if cells > max_width:
                        issues.append(
                            ValidationIssue(
                                line=entry.line,
                                category="warning",
                                message=(
                                    f"target display width {cells} cells exceeds "
                                    f"max-width {max_width}: '{entry.target}'"
                                ),
                                text=entry.target,
                            )
                        )

            if header.variant == "glossary":
                if resolved_type is not None and resolved_type not in GLOSSARY_TYPES:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="warning",
                            message=(
                                f"glossary type '{resolved_type}' is not term-level; "
                                f"term-level types are: {', '.join(sorted(GLOSSARY_TYPES))}"
                            ),
                            text=resolved_type,
                        )
                    )
                if entry.target is None:
                    issues.append(
                        ValidationIssue(
                            line=entry.line,
                            category="warning",
                            message="glossary entry is missing target",
                        )
                    )

    if style:
        issues.extend(_check_style(document))

    return issues


def validate(
    text: str,
    *,
    path: str | Path | None = None,
    check_width: bool = False,
    check_layout: bool = False,
    style: bool = False,
    tolerant: bool = False,
) -> list[ValidationIssue]:
    """Parse and validate CLIFF text, returning a list of issues.

    This function never raises for invalid CLIFF; malformed syntax is returned
    as a ``syntax`` issue instead.

    ``tolerant=True`` parses with the documented relaxations of specification
    Appendix C and reports every repair as a ``correction`` issue. ``check_layout``
    promotes layout recommendations to errors, and ``style`` adds style
    warnings. Neither turns a style deviation into an error.
    """
    try:
        document = parse(text, path=path, tolerant=tolerant)
    except CliffParseError as exc:
        return [
            ValidationIssue(
                line=exc.line,
                category=exc.category,
                message=exc.message,
                text=exc.text,
            )
        ]
    issues = validate_document(
        document,
        check_width=check_width,
        check_layout=check_layout,
        style=style,
    )
    if style:
        issues.extend(_check_terminator_style(document, text))
    return issues
