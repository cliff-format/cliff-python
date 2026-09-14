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
