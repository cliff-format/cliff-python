from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .identifiers import Correction


@dataclass
class Header:
    """CLIFF header fields.

    The four identity fields (namespace, clan, source-language and
    target-language) are required by the specification.

    "extensions" maps each x- key to the raw CLIFF value text exactly as written
    in the document. Extensions are opaque: the specification requires parsers
    to ignore them without altering their meaning, so cliff_format preserves the
    source text and the serializer re-emits it verbatim.
    """

    namespace: str = ""
    clan: str = ""
    source_language: str = ""
    target_language: str = ""
    version: str | None = None
    variant: str = "standard"
    title: str | None = None
    info: str | None = None
    standard: str | None = None
    dependency: list[str] = field(default_factory=list)
    extensions: dict[str, str] = field(default_factory=dict)


@dataclass
class Entry:
    """A single CLIFF translation entry."""

    id: str
    line: int = 0
    source: str | None = None
    target: str | None = None
    type: str | None = None
    emotion: list[str] = field(default_factory=list)
    status: str | None = None
    context: str | None = None
    max_width: int | None = None
    reference: list[str] = field(default_factory=list)
    reviewer: str | None = None
    extensions: dict[str, str] = field(default_factory=dict)


@dataclass
class Group:
    """A CLIFF group/section.

    ``path`` is the dotted section path, for example ``video.advanced``.
    """

    path: str
    line: int = 0
    context: str | None = None
    type: str | None = None
    emotion: list[str] = field(default_factory=list)
    max_width: int | None = None
    entries: list[Entry] = field(default_factory=list)
    extensions: dict[str, str] = field(default_factory=dict)


@dataclass
class CliffDocument:
    """The parsed representation of one CLIFF file.

    ``spec_version`` is the version the document *declared* on its version
    line (``"1.0"`` or ``"1.1"``), not the version of this library. A
    canonical serializer preserves it, so round-tripping a 1.0 document does
    not silently upgrade the file.

    ``corrections`` collects the repairs a tolerant parse made (specification
    Appendix C). It stays empty for a strict parse: strict mode rejects instead
    of repairing.
    """

    header: Header = field(default_factory=Header)
    groups: list[Group] = field(default_factory=list)
    path: Path | None = None
    spec_version: str = "1.1"
    corrections: list[Correction] = field(default_factory=list)

    def canonical_id(self, group: Group, entry: Entry) -> str:
        """Return the CLIFF canonical ID for an entry."""
        parts = [self.header.namespace, self.header.clan, group.path, entry.id]
        return ".".join(part for part in parts if part)

    def entries(self) -> list[tuple[Group, Entry]]:
        """Yield every ``(group, entry)`` pair in authored order."""
        return [(group, entry) for group in self.groups for entry in group.entries]


@dataclass
class ValidationIssue:
    """A single validation issue.

    Categories follow CLIFF's diagnostic model: ``syntax``, ``semantic``,
    ``vocabulary``, ``icu``, ``id``, ``extension`` and ``warning``, plus the
    two opt-in categories of CLIFF 1.1: ``correction`` (a repair a tolerant
    parse made) and ``style`` (a deviation from ``style/README.md``). Only the
    first six are errors; the last four are reported without failing a file.
    """

    line: int = 0
    category: str = "syntax"
    message: str = ""
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "category": self.category,
            "message": self.message,
            "text": self.text,
        }
