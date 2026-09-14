from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SPEC_EXAMPLES, require_sibling

from cliff_format import parse, serialize, validate

EXAMPLE_PATHS = require_sibling(SPEC_EXAMPLES, "cliff")


@pytest.mark.skipif(not EXAMPLE_PATHS, reason="cliff specification checkout is not available")
@pytest.mark.parametrize("path", EXAMPLE_PATHS, ids=lambda p: p.name)
def test_spec_examples_parse_and_validate(path: Path) -> None:
    """Every normative example must parse and validate without errors."""
    text = path.read_text(encoding="utf-8")
    parse(text, path=path)
    issues = validate(text, path=path)
    errors = [issue for issue in issues if issue.category not in ("warning", "extension")]
    assert errors == [], [issue.message for issue in errors]


@pytest.mark.skipif(not EXAMPLE_PATHS, reason="cliff specification checkout is not available")
@pytest.mark.parametrize("path", EXAMPLE_PATHS, ids=lambda p: p.name)
def test_spec_examples_serialize_to_a_stable_document(path: Path) -> None:
    """Serialization is idempotent: re-parsing canonical output is a fixed point."""
    document = parse(path.read_text(encoding="utf-8"), path=path)
    once = serialize(document)
    assert serialize(parse(once, path=path)) == once
