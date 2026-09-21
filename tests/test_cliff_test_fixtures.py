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

#: The categories a refusal under Appendix C.5 can carry. See
#: `test_unrepairable_tolerant_fixture_is_refused` for why this is a set.
C5_REFUSAL_CATEGORIES = frozenset({"vocabulary", "semantic", "id", "syntax"})


def _fixtures(name: str) -> list[Path]:
    return require_sibling(CLIFF_TEST_FIXTURES / name, f"cliff-test/{name}")


#: Tolerant fixtures whose whole point is that they must be *refused*
#: (specification Appendix C.5): tolerant parsing repairs shape, never content.
#: The list is duplicated in ``cliff-test/tests/run_all.py``, which splits the
#: same directory into "repairable" and "refused" for the validator suite, and
#: ``test_unrepairable_list_matches_the_conformance_suite`` below fails if the two
#: ever disagree - a fixture that one repository classifies as refusable and the
#: other as repairable is tested by neither.
UNREPAIRABLE = frozenset(
    {
        "unrepairable.zh-CN.cliff",
        "quoted-unknown-key.zh-CN.cliff",
        "closing-tag.zh-CN.cliff",
    }
)

VALID_PATHS = _fixtures("valid")
INVALID_PATHS = _fixtures("invalid")
LAYOUT_PATHS = _fixtures("layout")
TOLERANT_PATHS = [
    path for path in _fixtures("tolerant") if path.name not in UNREPAIRABLE
]
UNREPAIRABLE_PATHS = [
    path for path in _fixtures("tolerant") if path.name in UNREPAIRABLE
]
STYLE_PATHS = _fixtures("style")


def test_unrepairable_list_matches_the_conformance_suite() -> None:
    """The two repositories must classify the tolerant fixtures the same way."""
    import re

    from conftest import WORKSPACE_ROOT

    run_all = WORKSPACE_ROOT / "cliff-test" / "tests" / "run_all.py"
    if not run_all.is_file():
        pytest.skip("cliff-test checkout is not available")
    match = re.search(
        r"^UNREPAIRABLE\s*=\s*\{(?P<body>[^}]*)\}", run_all.read_text(encoding="utf-8"), re.M
    )
    assert match is not None, "cliff-test/tests/run_all.py no longer defines UNREPAIRABLE"
    theirs = set(re.findall(r'"([^"]+)"', match.group("body")))
    assert theirs == set(UNREPAIRABLE), (
        f"cliff-test refuses {sorted(theirs)} but this suite refuses "
        f"{sorted(UNREPAIRABLE)}; a fixture in neither list is tested as repairable "
        "by whichever repository forgot it"
    )


def _errors(issues) -> list:
    return [issue for issue in issues if issue.category not in ADVISORY]


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
    """Appendix C.5: a tolerant parser must not guess missing content.

    The refusal's *category* is not asserted to be one particular value, because
    C.5 lists several distinct refusals and the parser reports each under the
    category naming the rule it broke: `vocabulary` for a value outside a closed
    set, `semantic` for an unknown key or a missing field, `id` for a malformed
    section path. What the test does assert is that tolerant mode *refuses* rather
    than returning a document, and that it refuses under one of those categories
    with a line number - an unrepairable fixture that starts parsing is the
    failure this exists to catch.
    """
    text = path.read_text(encoding="utf-8")
    with pytest.raises(CliffParseError) as excinfo:
        parse(text, path=path, tolerant=True)
    assert excinfo.value.category in C5_REFUSAL_CATEGORIES, excinfo.value.message
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
