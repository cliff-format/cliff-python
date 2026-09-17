from __future__ import annotations


class CliffError(Exception):
    """Base class for all library-specific errors."""


class CliffParseError(CliffError):
    """Raised when CLIFF text cannot be parsed into a document.

    ``category`` uses the same diagnostic categories as
    :class:`~cliff_format.model.ValidationIssue`.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int = 0,
        category: str = "syntax",
        text: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.category = category
        self.text = text


class UnsupportedSpecVersion(CliffParseError):
    """Raised when a document declares a CLIFF version this build does not implement.

    Subclasses :class:`CliffParseError`, so callers that only catch the base
    class keep working while callers that want to distinguish "valid CLIFF, but
    from another version" from "not CLIFF at all" can catch this instead.

    ``declared`` is the version as written, and ``supported`` lists the versions
    this implementation implements.
    """

    def __init__(
        self,
        message: str,
        *,
        declared: str = "",
        supported: tuple[str, ...] = (),
        line: int = 0,
        text: str = "",
    ) -> None:
        super().__init__(message, line=line, category="semantic", text=text)
        self.declared = declared
        self.supported = supported
