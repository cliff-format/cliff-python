"""Conformance fixtures from the sibling ``cliff-test`` checkout.

The fixture tree is organized by the question each suite answers, so this
module asks each question with the mode that suite is about:

* ``valid/`` — strict parse, zero errors;
* ``invalid/`` — strict parse, at least one hard error;
* ``layout/`` — no error by default (a layout mismatch is a warning in CLIFF
  1.1) but an error under ``check_layout=True``;
* ``tolerant/`` — rejected strictly, accepted tolerantly with a repair report;
* ``style/`` — valid CLIFF, zero errors, and reported by ``style=True``.

Asserting the mode matters: a suite that passes under the wrong mode is not
evidence of anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import CLIFF_TEST_FIXTURES, require_sibling

from cliff_format import parse, parse_tolerant, serialize, validate
from cliff_format.errors import CliffParseError

ADVISORY = ("warning", "extension", "correction", "style")


def _fixtures(name: str) -> list[Path]:
    return require_sibling(CLIFF_TEST_FIXTURES / name, f"cliff-test/{name}")


#: A tolerant fixture whose whole point is that it must be *refused*
#: (specification Appendix C.5): tolerant parsing repairs shape, never content.
UNREPAIRABLE = "unrepairable.zh-CN.cliff"

VALID_PATHS = _fixtures("valid")
INVALID_PATHS = _fixtures("invalid")
LAYOUT_PATHS = _fixtures("layout")
TOLERANT_PATHS = [
    path for path in _fixtures("tolerant") if path.name != UNREPAIRABLE
]
UNREPAIRABLE_PATHS = [
    path for path in _fixtures("tolerant") if path.name == UNREPAIRABLE
]
STYLE_PATHS = _fixtures("style")


def _errors(issues) -> list:
    return [issue for issue in issues if issue.category not in ADVISORY]


def _skip_or_fail(paths: list[Path], name: str) -> None:
    if not paths:
        pytest.skip(f"sibling checkout {name} is not available")


@pytest.mark.skipif(not VALID_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", VALID_PATHS, ids=lambda p: p.name)
def test_valid_fixtures_are_accepted(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parse(text, path=path)
    issues = validate(text, path=path)
    assert _errors(issues) == [], [issue.message for issue in _errors(issues)]


@pytest.mark.skipif(not INVALID_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", INVALID_PATHS, ids=lambda p: p.name)
def test_invalid_fixtures_are_rejected(path: Path) -> None:
    """Each conformance counter-example must produce at least one hard error."""
    text = path.read_text(encoding="utf-8")
    try:
        issues = validate(text, path=path)
    except CliffParseError:
        return
    errors = _errors(issues)
    assert errors, f"{path.name} was accepted but the fixture is invalid"
    assert all(issue.category for issue in errors)


@pytest.mark.skipif(not LAYOUT_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", LAYOUT_PATHS, ids=lambda p: p.name)
def test_layout_fixtures_warn_by_default_and_fail_when_enforced(path: Path) -> None:
    if not LAYOUT_PATHS:
        pytest.skip("cliff-test/layout is not available")
    text = path.read_text(encoding="utf-8")
    assert _errors(validate(text, path=path)) == [], (
        "a layout mismatch is a recommendation in CLIFF 1.1, not an error"
    )
    enforced = _errors(validate(text, path=path, check_layout=True))
    assert enforced, f"{path.name} must fail once layout consistency is enforced"


@pytest.mark.skipif(not TOLERANT_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", TOLERANT_PATHS, ids=lambda p: p.name)
def test_tolerant_fixtures_are_repaired_into_valid_documents(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    with pytest.raises(CliffParseError):
        parse(text, path=path)
    document, corrections = parse_tolerant(text, path=path)
    assert corrections, f"{path.name} declares tolerance but nothing was repaired"
    once = serialize(document)
    assert _errors(validate(once)) == [], [
        issue.message for issue in _errors(validate(once))
    ]
    assert serialize(parse(once)) == once


@pytest.mark.skipif(not UNREPAIRABLE_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", UNREPAIRABLE_PATHS, ids=lambda p: p.name)
def test_unrepairable_tolerant_fixture_is_refused(path: Path) -> None:
    """Appendix C.5: a tolerant parser must not guess missing content."""
    text = path.read_text(encoding="utf-8")
    with pytest.raises(CliffParseError) as excinfo:
        parse(text, path=path, tolerant=True)
    assert excinfo.value.category == "vocabulary", excinfo.value.message
    assert excinfo.value.line > 0


@pytest.mark.skipif(not STYLE_PATHS, reason="cliff-test checkout is not available")
@pytest.mark.parametrize("path", STYLE_PATHS, ids=lambda p: p.name)
def test_style_fixtures_are_valid_but_reported_by_style(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parse(text, path=path)
    assert _errors(validate(text, path=path)) == [], "a style deviation is not an error"
    issues = validate(text, path=path, style=True)
    assert [i for i in issues if i.category == "style"], (
        f"{path.name} is in the style suite but reported no style deviation"
    )
