"""Drift guards: the implementation must agree with the specification.

Two independent artifacts state the same rules — the normative ABNF grammar and
the informative style guide — and a third states them in code
(``cliff_format.identifiers``). Nothing keeps them in sync except a test, and a
validator that accepts fewer identifiers than the grammar (or more) is exactly
the silent divergence this project cannot afford: the grammar is what users
read, the code is what runs.

The checks skip when the sibling ``cliff`` checkout is absent, following the
convention in ``conftest.require_sibling``.
"""

from __future__ import annotations

import re

import pytest
from conftest import WORKSPACE_ROOT

from cliff_format import identifiers
from cliff_format.vocabulary import EMOTION_TAGS, STATUS_TAGS, TYPE_TAGS

CLIFF_REPO = WORKSPACE_ROOT / "cliff"
ABNF = CLIFF_REPO / "spec" / "abnf" / "cliff-1.1.abnf"
STYLE = CLIFF_REPO / "style" / "README.md"
SPEC = CLIFF_REPO / "spec" / "cliff-1.1.0.md"

requires_spec = pytest.mark.skipif(
    not CLIFF_REPO.is_dir(), reason="cliff specification checkout is not available"
)

NAME_CHAR_RE = re.compile(r"^name-char\s*=\s*(?P<rhs>[^\r\n;]+)", re.M)
#: ``Diagnostic: category `x`` - the line Appendix C.2 gives each relaxation.
DIAGNOSTIC_CATEGORY_RE = re.compile(r"^ +Diagnostic: category `(?P<name>[a-z-]+)`", re.M)
TAGGED_BLOCK_RE = re.compile(
    r"^```[A-Za-z0-9_-]*[ \t]*\r?\n(?P<body>.*?)^```[ \t]*$"
    r"(?=\s*<!--\s*check:\s*(?P<marker>[a-z-]+)\s*-->)",
    re.M | re.S,
)


def _marked_blocks(text: str) -> dict[str, str]:
    """Return each fenced block that a following comment marks, keyed by marker."""
    return {
        match.group("marker"): match.group("body").strip()
        for match in TAGGED_BLOCK_RE.finditer(text)
    }


@requires_spec
def test_abnf_name_char_matches_the_implementation() -> None:
    """`name-char` in the grammar is the character set the code enforces."""
    text = ABNF.read_text(encoding="utf-8")
    match = NAME_CHAR_RE.search(text)
    assert match is not None, "cliff-1.1.abnf no longer defines 'name-char'"
    alternatives = {part.strip() for part in match.group("rhs").split("/")}
    assert alternatives == set(identifiers.NAME_CHAR_ALTERNATIVES), (
        f"grammar says {sorted(alternatives)}, "
        f"implementation allows {sorted(identifiers.NAME_CHAR_ALTERNATIVES)}"
    )


@requires_spec
def test_abnf_name_accepts_every_implementation_name() -> None:
    """Every name the implementation accepts is a name the grammar accepts.

    The grammar is expressed as a character set, so a differential check over a
    representative corpus is the strongest statement available without writing
    an ABNF interpreter.
    """
    assert identifiers.NAME_CHAR_CLASS == "[A-Za-z0-9_-]"
    for value in ("resolution", "Resolution", "bad_id", "200", "x-1", "a-_b", "_x", "X-"):
        assert identifiers.is_name(value), value


@requires_spec
def test_style_guide_regexes_match_the_implementation() -> None:
    """The machine-readable regexes in the style guide are the ones in code."""
    blocks = _marked_blocks(STYLE.read_text(encoding="utf-8"))
    assert blocks.get("style-kebab") == identifiers.STYLE_KEBAB_PATTERN
    assert blocks.get("style-pascal") == identifiers.STYLE_PASCAL_PATTERN
    assert blocks.get("name-char-class") == identifiers.NAME_CHAR_CLASS


@requires_spec
def test_style_predicate_is_stricter_than_the_name_rule() -> None:
    """Style asks a narrower question than validity, and the two must differ.

    If ``is_style_identifier`` ever becomes identical to ``is_name``, the style
    guide has silently become normative — which is exactly what 1.1 removed.
    """
    for value in ("bad_id", "-x", "x-", "Bad_ID"):
        assert identifiers.is_name(value)
        assert not identifiers.is_style_identifier(value), value
    for value in ("inv-sword-iron", "InvSwordIron", "panel-2"):
        assert identifiers.is_style_identifier(value), value


@requires_spec
def test_specification_states_the_two_bare_word_kinds() -> None:
    """The spec keeps `name` and `tag` distinct, and so does the code."""
    text = SPEC.read_text(encoding="utf-8")
    assert "name-char" in text
    assert "tag-name" in text
    # The identifier character set is documented in the spec, not only in code.
    assert "`A`–`Z`" in text or "A–Z" in text
    # And the dot prohibition has a stated reason.
    assert "MUST NOT contain a dot" in text


@requires_spec
def test_tag_vocabularies_match_the_reference_tables() -> None:
    """The closed vocabularies match `cliff/references/`, the stated source."""
    counts = {
        "content-types.md": TYPE_TAGS,
        "emotion-tags.md": EMOTION_TAGS,
        "status-tags.md": STATUS_TAGS,
    }
    lines_by_file = {
        name: (CLIFF_REPO / "references" / name).read_text(encoding="utf-8").splitlines()
        for name in counts
    }
    for name, tags in counts.items():
        text = "\n".join(lines_by_file[name])
        missing = sorted(tag for tag in tags if f"`{tag}`" not in text)
        assert missing == [], f"{name} does not document {missing}"


@requires_spec
def test_spec_version_lines_are_the_supported_ones() -> None:
    """The grammar accepts exactly the version lines this implementation does."""
    from cliff_format.parser import SUPPORTED_VERSIONS

    text = ABNF.read_text(encoding="utf-8")
    for version in SUPPORTED_VERSIONS:
        assert f'%s"{version}"' in text, f"grammar omits version {version}"
    assert SUPPORTED_VERSIONS == ("1.0", "1.1")


@requires_spec
def test_examples_of_the_current_version_are_present() -> None:
    """The 1.1 example directory exists and every spec example validates."""
    import cliff_format

    examples = sorted((CLIFF_REPO / "spec" / "examples" / "cliff-1.1.0").rglob("*.cliff"))
    assert examples, "spec/examples/cliff-1.1.0 is missing or empty"
    for path in examples:
        text = path.read_text(encoding="utf-8")
        document = cliff_format.parse(text, path=path)
        errors = [
            issue
            for issue in cliff_format.validate_document(document)
            if issue.category not in ("warning", "extension")
        ]
        assert errors == [], [i.message for i in errors]


@requires_spec
def test_repair_categories_match_appendix_c() -> None:
    """The categories Appendix C.2 names are the ones the parser can report.

    A relaxation is only usable if the repair that implements it is reported under
    the category the specification attaches to it: a pipeline keys its handling on
    the category. The appendix states one ``Diagnostic: category`` line per
    relaxation, so the two lists are comparable as written, and a relaxation added
    to the specification without a matching implementation fails here rather than
    in a downstream consumer.

    The categories are deliberately fewer than the relaxations: C.2.4 and C.2.7 are
    both a quoted name and share ``name-quote``.
    """
    from cliff_format.parser import TOLERANT_RELAXATION_COUNT, TOLERANT_REPAIR_CATEGORIES

    text = SPEC.read_text(encoding="utf-8")
    named = DIAGNOSTIC_CATEGORY_RE.findall(text)
    assert len(named) == TOLERANT_RELAXATION_COUNT, (
        f"Appendix C.2 states {len(named)} diagnostics but the implementation "
        f"expects {TOLERANT_RELAXATION_COUNT} relaxations; a new relaxation needs a "
        f"diagnostic line and an implementation"
    )
    assert set(named) == set(TOLERANT_REPAIR_CATEGORIES), (
        f"specification names {sorted(set(named))}, "
        f"implementation emits {sorted(TOLERANT_REPAIR_CATEGORIES)}"
    )


def test_repository_paths_exist() -> None:
    """Guard the guard: a typo in a path would silently skip every check."""
    if not CLIFF_REPO.is_dir():
        pytest.skip("cliff specification checkout is not available")
    for path in (ABNF, STYLE, SPEC):
        assert path.is_file(), path
