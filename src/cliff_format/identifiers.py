"""Identifier and tag rules for CLIFF 1.1.

This module is the single source of truth for the two kinds of bare word in a
CLIFF document, because the specification distinguishes them and every other
module needs both:

* a **name** — keys, entry ids, group path segments, and the ``namespace`` /
  ``clan`` header values. Characters are ``A-Z a-z 0-9 _ -``; a name is never
  empty and never contains ``.``. Casing is significant and a parser MUST NOT
  rewrite a name (specification 5.5, 10.1).
* a **tag** — the value of a fixed-vocabulary field (``type``, ``emotion``,
  ``status``, ``variant``). Tags were *not* relaxed in 1.1: they stay lowercase
  kebab-case words from a closed set (specification 5.5, 12, 13).

The recommended identifier *shapes* (kebab-case or PascalCase) live in
``style/README.md`` and are informative; they are mirrored here only so the
drift-guard test in ``cliff/tools/check_examples.py`` can compare the two. A
style deviation is never a validity error.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- the normative name rule (specification 5.5) ---------------------------

#: The alternatives of the ABNF ``name-char`` production, as they must be
#: spelled in ``spec/abnf/cliff-1.1.abnf``. ``check_examples.py`` compares the
#: grammar against this tuple.
NAME_CHAR_ALTERNATIVES: tuple[str, ...] = ("ALPHA", "DIGIT", '"_"', '"-"')

#: Human-readable form of the name character set, as documented in
#: ``style/README.md``. Kept as a plain string so the drift guard can compare.
NAME_CHAR_CLASS = "[A-Za-z0-9_-]"

#: The normative name pattern: one or more name characters, nothing else. The
#: dot is excluded on purpose: it separates group path segments and canonical
#: ID components, so allowing it inside a name would make
#: ``namespace.clan.group-path.entry-id`` ambiguous in both directions.
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: The normative tag pattern (specification 5.5). Unchanged from CLIFF 1.0.
TAG_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# --- the recommended shapes (style/README.md, informative) -----------------

#: Recommended kebab-case identifiers: words of lowercase letters and digits,
#: joined by a single ``-``, with no leading or trailing ``-`` —
#: ``inv-sword-iron``, ``panel-2``. The pattern source is a plain string so
#: ``style/README.md`` can print exactly the same text and the drift guard can
#: compare them character for character.
STYLE_KEBAB_PATTERN = "^[a-z0-9]+(-[a-z0-9]+)*$"

#: Recommended PascalCase identifiers: ``InvSwordIron``. Hyphens and
#: underscores are not part of this shape, so ``Bad_ID`` is not PascalCase.
STYLE_PASCAL_PATTERN = "^[A-Z][A-Za-z0-9]*$"

#: The recommended shapes joined as one alternation. The group is
#: load-bearing: without it, ``re.match`` would treat the second alternative as
#: unanchored and silently accept any name at all.
STYLE_NAME_PATTERN = f"(?:{STYLE_KEBAB_PATTERN})|(?:{STYLE_PASCAL_PATTERN})"

STYLE_KEBAB = re.compile(STYLE_KEBAB_PATTERN)

STYLE_PASCAL = re.compile(STYLE_PASCAL_PATTERN)

#: Either recommended shape. A file is expected to use exactly one of them.
STYLE_NAME_RE = re.compile(STYLE_NAME_PATTERN)

#: Patterns that carry no style obligation, because the shape cannot satisfy
#: any recommended form: a leading digit followed by anything that is not a
#: letter, such as ``200``, ``200%``, or ``1``. A generated or positional id of
#: that kind has no better spelling, so reporting it would be noise.
_POSITIONAL_RE = re.compile(r"^[0-9]+[^A-Za-z]*")

# --- key classification (specification 6.1, 6.3, 7, 8) ---------------------

#: Fields whose value is a name rather than text or a tag.
NAME_KEYS = frozenset({"namespace", "clan"})

#: Fields whose value is a language tag.
LANG_KEYS = frozenset({"source-language", "target-language"})

#: Fields whose value is a closed-vocabulary tag.
TAG_KEYS = frozenset({"variant", "type", "status"})

#: Fields whose value is a single-line list.
LIST_KEYS = frozenset({"emotion", "dependency", "reference"})

#: Entry level and header level keys whose value is free text.
STRING_KEYS = frozenset(
    {"version", "title", "info", "standard", "source", "target", "context", "reviewer"}
)

#: The fallback identifier per scope, used when normalization produces nothing.
FALLBACK_NAMES = {
    "entry": "entry",
    "group": "group",
    "namespace": "ns",
    "clan": "clan",
}

_WHITESPACE_RE = re.compile(r"\s+")
_ILLEGAL_RE = re.compile(r"[^A-Za-z0-9_-]")
_HYPHEN_RUN_RE = re.compile(r"-{2,}")


def is_name(text: str) -> bool:
    """Whether ``text`` is a conforming CLIFF 1.1 identifier."""
    return bool(text) and NAME_RE.match(text) is not None


def is_tag(text: str) -> bool:
    """Whether ``text`` is well-formed as a fixed-vocabulary tag."""
    return TAG_NAME_RE.match(text) is not None


def is_style_identifier(text: str) -> bool:
    """Whether ``text`` follows a recommended identifier shape (informative).

    The recommendation in ``style/README.md`` is kebab-case or PascalCase, one
    per file. This predicate is the *style* question, so it is stricter than
    :func:`is_name` in exactly the ways the guide is:

    * no underscores (``bad_id`` is valid CLIFF, not recommended style);
    * no leading or trailing ``-`` (``-save``, ``x-``);
    * no leading digit — except for a purely positional identifier such as
      ``200``, where no recommended spelling exists and a warning would be
      noise.
    """
    return bool(text) and STYLE_NAME_RE.match(text) is not None


def has_style_obligation(text: str) -> bool:
    """Whether ``text`` could have followed the style guide but did not.

    A positional identifier (``200``) cannot satisfy either recommended shape,
    so a style report about it would ask for a change that has no answer.
    """
    return not _POSITIONAL_RE.match(text or "")


@dataclass(frozen=True)
class Correction:
    """One repair a tolerant parse or a style-aware pass made or observed.

    A correction is not an error: the document was accepted. It is also not
    silent: the specification requires every repair to be reported, because an
    unreported repair is indistinguishable from data loss (Appendix C.6).
    """

    line: int = 0
    category: str = ""
    message: str = ""
    before: str = ""
    after: str = ""

    def describe(self) -> str:
        """One diagnostic line, in the shape the CLI prints.

        The message is prefixed with the category because this form is used
        where no other category field is printed. Callers that already render a
        ``[CATEGORY]`` prefix (the validator's issue list, the CLI's
        ``_format_issue``) should use :meth:`detail` instead, so the category
        is not printed twice.
        """
        return f"[{self.category.upper()}] {self.detail()}"

    def detail(self) -> str:
        """The message plus the before/after values, without a category prefix."""
        if self.before or self.after:
            return f"{self.message} (was {self.before!r}, now {self.after!r})"
        return self.message

    def as_dict(self) -> dict[str, object]:
        return {
            "line": self.line,
            "category": self.category,
            "message": self.message,
            "before": self.before,
            "after": self.after,
        }


def normalize_identifier(text: str, *, kind: str = "entry") -> str:
    """Normalize a violating identifier (specification Appendix C.3).

    The algorithm is fixed by the specification so that two independent
    tolerant parsers produce the same identifiers:

    1. NFKC normalization,
    2. strip surrounding whitespace,
    3. each whitespace run becomes a single ``-``,
    4. every other character outside the name set becomes ``-``,
    5. collapse ``-`` runs,
    6. strip leading and trailing ``-``,
    7. fall back to the scope's default name when nothing survives.

    This is applied to a *violating* identifier only. A valid name such as
    ``bad_id`` or ``Resolution`` is returned byte-for-byte: its shape may
    deviate from the style guide, but style is not a repair.
    """
    if is_name(text):
        return text
    normalized = unicodedata.normalize("NFKC", text).strip()
    normalized = _WHITESPACE_RE.sub("-", normalized)
    normalized = _ILLEGAL_RE.sub("-", normalized)
    normalized = _HYPHEN_RUN_RE.sub("-", normalized)
    normalized = normalized.strip("-")
    if normalized:
        return normalized
    return FALLBACK_NAMES.get(kind, "entry")


def unique_identifier(candidate: str, used: set[str], *, sep: str = "-") -> str:
    """Disambiguate ``candidate`` against ``used`` with a numeric suffix.

    Returns the first name not already in ``used`` and records it, so a second
    call for a different collision continues the same counter. Tolerant
    parsing uses this (Appendix C.4); a strict validator never does, because a
    duplicate identifier is an error there (specification 10.2).
    """
    if candidate not in used:
        used.add(candidate)
        return candidate
    counter = 2
    while f"{candidate}{sep}{counter}" in used:
        counter += 1
    resolved = f"{candidate}{sep}{counter}"
    used.add(resolved)
    return resolved


def strip_line_terminator(line: str) -> tuple[str, str, int]:
    """Split the trailing ``,`` / ``;`` terminators off a raw line.

    Returns ``(body, terminators, extra)``: ``body`` is the line without the
    trailing terminators and the whitespace around them, ``terminators`` holds
    the terminator characters found (without any whitespace between them, so
    ``"a, ;"`` yields ``",;"``), and ``extra`` counts how many are beyond the
    single one the grammar permits. The caller reports ``extra > 0`` as the
    syntax error of specification 5.6, so the distinction between "one, legal"
    and "two, illegal" stays visible instead of being flattened here.

    Whitespace *between* two terminators is itself an error, because the only
    legal terminator sits at the end of the line: ``key: v, ;`` still has two
    terminators and is rejected.

    The scan is right-to-left over trailing whitespace and terminators only, so
    a ``,`` or ``;`` inside a quoted string — or the optional trailing comma
    inside a ``[a, b,]`` list, which the bracket already closes — is never
    touched.
    """
    end = len(line)
    index = end
    while index > 0 and line[index - 1] in " \t":
        index -= 1
    if index == 0 or line[index - 1] not in ",;":
        return line[:index], "", 0

    terminators = [line[index - 1]]
    index -= 1
    # A second terminator is illegal whether or not whitespace separates it
    # from the first: the only legal one sits at the very end of the line.
    probe = index
    while probe > 0 and line[probe - 1] in " \t":
        probe -= 1
    if probe > 0 and line[probe - 1] in ",;":
        terminators.append(line[probe - 1])
        index = probe - 1
    terminators.reverse()
    return line[:index], "".join(terminators), max(len(terminators) - 1, 0)
