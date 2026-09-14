from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CLIFF_TEST_FIXTURES, require_sibling

from cliff_format import parse, validate
from cliff_format.errors import CliffParseError

VALID_PATHS = require_sibling(CLIFF_TEST_FIXTURES / "valid", "cliff-test/valid")
INVALID_PATHS = require_sibling(CLIFF_TEST_FIXTURES / "invalid", "cliff-test/invalid")


@pytest.mark.skipif(not VALID_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", VALID_PATHS, ids=lambda p: p.name)
def test_valid_fixtures_are_accepted(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parse(text, path=path)
    issues = validate(text, path=path)
    errors = [issue for issue in issues if issue.category not in ("warning", "extension")]
    assert errors == [], [issue.message for issue in errors]


@pytest.mark.skipif(not INVALID_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", INVALID_PATHS, ids=lambda p: p.name)
def test_invalid_fixtures_are_rejected(path: Path) -> None:
    """Each conformance counter-example must produce at least one hard error."""
    text = path.read_text(encoding="utf-8")
    try:
        issues = validate(text, path=path)
    except CliffParseError:
        return
    errors = [issue for issue in issues if issue.category not in ("warning", "extension")]
    assert errors, f"{path.name} was accepted but the fixture is invalid"
    assert all(issue.category for issue in errors)
