"""CLIFF 1.1 identifier rules: what the format decides and what the style guide does.

The specification separates two kinds of bare word (specification 5.5):

* a **name** — keys, entry ids, group path segments, ``namespace``, ``clan`` —
  may use ``A-Z a-z 0-9 _ -`` and never contains ``.``;
* a **tag** — ``type`` / ``emotion`` / ``status`` / ``variant`` — stays
  lowercase kebab-case from a closed vocabulary.

These tests pin the boundary. A failure in the "accepted" group means 1.1 got
narrower than intended; a failure in the "rejected" group means it got wider.
"""

from __future__ import annotations

import pytest

from cliff_format import parse, validate
from cliff_format.errors import CliffParseError
from cliff_format.identifiers import (
    NAME_CHAR_ALTERNATIVES,
    NAME_CHAR_CLASS,
    NAME_RE,
    STYLE_KEBAB_PATTERN,
    STYLE_NAME_PATTERN,
    STYLE_PASCAL_PATTERN,
    has_style_obligation,
    is_name,
    is_style_identifier,
    normalize_identifier,
    strip_line_terminator,
    unique_identifier,
)

HEADER = (
    "CLIFF 1.1\n"
    "namespace: demo\n"
    "clan: settings\n"
    "source-language: en-US\n"
    "target-language: zh-CN\n"
)


def document(*body: str, group: str = "[Video]", entry: str = "<Resolution>") -> str:
    return HEADER + f"\n{group}\ntype: label\n\n{entry}\n" + "".join(body)


def errors_of(text: str, **kwargs: object) -> list[str]:
    issues = validate(text, **kwargs)  # type: ignore[arg-type]
    return [i.message for i in issues if i.category not in ("warning", "extension", "style")]


# --- the name character set -------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "resolution",
        "Resolution",
        "RESOLUTION",
        "bad_id",
        "200",
        "x-1",
        "a-_b",
        "InvSwordIron",
        "_hidden",
        "x-",
        "-x",
        "a",
    ],
)
def test_accepted_names(name: str) -> None:
    assert is_name(name), f"{name!r} must be a valid CLIFF 1.1 name"


@pytest.mark.parametrize(
    "name",
    ["", "a.b", "a b", "a/b", "a+b", "a&b", "a,b", "a;b", "a:b", "a[b]", "a#b", "é"],
)
def test_rejected_names(name: str) -> None:
    assert not is_name(name), f"{name!r} must not be a CLIFF 1.1 name"


def test_dot_is_forbidden_inside_a_name() -> None:
    """The dot separates group path segments and canonical ID components."""
    assert not is_name("video.advanced")
    with pytest.raises(CliffParseError):
        parse(document('source: "S"\nstatus: initial\n', entry="<Video.Advanced>"))
    with pytest.raises(CliffParseError):
        parse(document('source: "S"\nstatus: initial\n', group="[Video Setup]"))


@pytest.mark.parametrize("entry_id", ["Resolution", "bad_id", "200", "_hidden", "InvSwordIron"])
def test_identifier_shapes_are_accepted_and_preserved(entry_id: str) -> None:
    """1.1 accepts shapes that 1.0 rejected, and never rewrites them."""
    text = document('source: "S"\nstatus: initial\n', entry=f"<{entry_id}>")
    parsed = parse(text)
    assert parsed.groups[0].entries[0].id == entry_id


def test_namespace_and_clan_may_mix_case() -> None:
    text = HEADER.replace("namespace: demo", "namespace: Demo").replace(
        "clan: settings", "clan: Act3_Strings"
    )
    text += '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S"\nstatus: initial\n'
    assert errors_of(text) == []
    document_parsed = parse(text)
    assert document_parsed.header.namespace == "Demo"
    assert document_parsed.header.clan == "Act3_Strings"
    assert document_parsed.canonical_id(
        document_parsed.groups[0], document_parsed.groups[0].entries[0]
    ) == "Demo.Act3_Strings.Video.Resolution"


def test_identifier_casing_is_significant_not_aliased() -> None:
    """<Save> and <save> are two entries, not one entry spelled twice."""
    text = document(
        'source: "S"\nstatus: initial\n',
        '\n<save>\nsource: "S2"\nstatus: initial\n',
        entry="<Save>",
    )
    parsed = parse(text)
    assert [e.id for e in parsed.groups[0].entries] == ["Save", "save"]
    assert errors_of(text) == []


# --- tags are NOT relaxed ---------------------------------------------------


@pytest.mark.parametrize("body", ["type: Noun\n", "status: Final\n", "status: REVIEWED\n"])
def test_tag_spelling_is_still_closed(body: str) -> None:
    text = document(f'source: "S"\n{body}', group="[Video]")
    categories = {i.category for i in validate(text)}
    assert "vocabulary" in categories or "syntax" in categories, (
        f"{body.strip()!r} must be rejected, got {[i.message for i in validate(text)]}"
    )


def test_group_and_entry_types_use_the_same_tag_rule() -> None:
    """A word outside the closed vocabulary is a vocabulary error, not syntax."""
    text = document('source: "S"\nstatus: initial\ntype: Label\n', group="[Video]")
    issues = [i for i in validate(text) if i.category == "vocabulary"]
    assert issues, [i.message for i in validate(text)]
    assert "invalid tag 'Label'" in " ".join(i.message for i in issues)


def test_misspelled_tag_is_a_vocabulary_error_with_the_allowed_values() -> None:
    text = document('source: "S"\nstatus: finall\n')
    issues = [i for i in validate(text) if i.category == "vocabulary"]
    assert len(issues) == 1
    assert "allowed:" in issues[0].message


def test_quoted_tag_is_still_an_error_in_strict_mode() -> None:
    with pytest.raises(CliffParseError, match="unquoted"):
        parse(document('source: "S"\nstatus: "initial"\n'))


# --- style is a recommendation, never a validity rule -----------------------


@pytest.mark.parametrize("value", ["inv-sword-iron", "InvSwordIron", "panel-2", "a", "200"])
def test_recommended_shapes_are_style_conformant(value: str) -> None:
    assert is_style_identifier(value)


@pytest.mark.parametrize("value", ["inv_sword_iron", "-x", "x-", "a--b", "Bad_ID"])
def test_non_style_names_are_valid_but_not_style_conformant(value: str) -> None:
    assert is_name(value)
    assert not is_style_identifier(value)


def test_positional_identifiers_carry_no_style_obligation() -> None:
    """No recommended shape fits ``200``, so a style report would be noise."""
    assert has_style_obligation("bad_id")
    assert has_style_obligation("BadID")
    assert not has_style_obligation("200")
    assert not has_style_obligation("1")


def test_style_deviations_are_warnings_not_errors() -> None:
    text = document('source: "S"\nstatus: initial\n', entry="<bad_id>")
    assert errors_of(text) == []
    style = [i for i in validate(text, style=True) if i.category == "style"]
    assert style, "a snake_case entry id must be reported by --style"
    assert any("bad_id" in i.message for i in style)


# --- normalization (specification Appendix C.3) -----------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Resolution", "Resolution"),
        ("bad_id", "bad_id"),
        ("200", "200"),
        ("inv sword", "inv-sword"),
        ("inv  sword", "inv-sword"),
        ("a&b", "a-b"),
        ("a/b+c", "a-b-c"),
        ("act 3: opening", "act-3-opening"),
        ("--x--", "--x--"),
        (" - - x - - ", "x"),
        ("&", "entry"),
        ("", "entry"),
        ("２０", "20"),
    ],
)
def test_normalize_identifier_is_deterministic(raw: str, expected: str) -> None:
    assert normalize_identifier(raw, kind="entry") == expected
    assert normalize_identifier(raw, kind="entry") == expected


def test_normalize_identifier_leaves_valid_names_alone() -> None:
    """Style is not a repair: only a *violating* identifier is rewritten."""
    for value in ("bad_id", "BadID", "200", "_x", "x-"):
        assert normalize_identifier(value, kind="entry") == value


def test_unique_identifier_continues_the_counter() -> None:
    used: set[str] = set()
    assert unique_identifier("save", used) == "save"
    assert unique_identifier("save", used) == "save-2"
    assert unique_identifier("save", used) == "save-3"
    assert unique_identifier("save-2", used) == "save-2-2"


# --- the terminator helper (specification 5.6) ------------------------------


@pytest.mark.parametrize(
    ("line", "body", "terminators", "extra"),
    [
        ("key: value", "key: value", "", 0),
        ("key: value,", "key: value", ",", 0),
        ("key: value;", "key: value", ";", 0),
        ("key: value, ", "key: value", ",", 0),
        ("key: value;;", "key: value", ";;", 1),
        ("key: value, ;", "key: value", ",;", 1),
        ('key: "a,b;"', 'key: "a,b;"', "", 0),
        ('key: "a,b;",', 'key: "a,b;"', ",", 0),
        ("emotion: [a, b,]", "emotion: [a, b,]", "", 0),
    ],
)
def test_strip_line_terminator(line: str, body: str, terminators: str, extra: int) -> None:
    assert strip_line_terminator(line) == (body, terminators, extra)


# --- the drift-guard constants ---------------------------------------------


def test_name_char_constants_agree_with_each_other() -> None:
    assert NAME_RE.match("a") is not None
    assert sorted(NAME_CHAR_ALTERNATIVES) == ['"-"', '"_"', "ALPHA", "DIGIT"]
    assert NAME_CHAR_CLASS == "[A-Za-z0-9_-]"
    assert STYLE_NAME_PATTERN == (
        f"(?:{STYLE_KEBAB_PATTERN})|(?:{STYLE_PASCAL_PATTERN})"
    ), "an unanchored alternative would silently accept any name"
    # The style predicates are distinct questions, so they must not agree.
    assert is_name("bad_id") and not is_style_identifier("bad_id")
    assert has_style_obligation("bad_id")
