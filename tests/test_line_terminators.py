"""The optional trailing ``,`` / ``;`` terminator (specification 5.6).

A terminator is *standard* CLIFF 1.1 syntax: it is accepted on any line, carries
no meaning, and is never emitted by a canonical serializer. These tests pin all
three halves of that sentence, plus the boundary that keeps it decidable — one
terminator only, and never inside a quoted value.
"""

from __future__ import annotations

import pytest

from cliff_format import parse, parse_tolerant, serialize, validate
from cliff_format.errors import CliffParseError

HEADER = (
    "CLIFF 1.1\n"
    "namespace: demo\n"
    "clan: settings\n"
    "source-language: en-US\n"
    "target-language: zh-CN\n"
)


def errors_of(text: str, **kwargs: object) -> list[str]:
    issues = validate(text, **kwargs)  # type: ignore[arg-type]
    return [i.message for i in issues if i.category not in ("warning", "extension", "style")]


@pytest.mark.parametrize("terminator", [",", ";", " ,", " ;", ", ", "; ", " , "])
def test_every_line_kind_accepts_one_terminator(terminator: str) -> None:
    text = (
        HEADER.replace("clan: settings\n", f"clan: settings{terminator}\n")
        + f"\n[Video]{terminator}\ntype: label{terminator}\n"
        + f'\n<Resolution>{terminator}\nsource: "S"{terminator}\ntarget: "T"{terminator}\n'
        + f"status: final{terminator}\n"
    )
    document = parse(text)
    assert document.header.clan == "settings"
    assert document.groups[0].path == "Video"
    assert document.groups[0].type == "label"
    entry = document.groups[0].entries[0]
    assert entry.id == "Resolution"
    assert entry.source == "S"
    assert entry.target == "T"
    assert entry.status == "final"
    assert errors_of(text) == []

def test_terminator_on_the_version_line_is_accepted() -> None:
    text = "CLIFF 1.1,\n" + HEADER[len("CLIFF 1.1\n") :]
    text += '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S"\nstatus: initial\n'
    assert errors_of(text) == []


def test_comment_and_blank_lines_with_terminators_are_ignored() -> None:
    text = HEADER + (
        "# note,\n"
        "   \n"
        "[Video]\ntype: label\n\n"
        '<Resolution>\nsource: "S"\nstatus: initial\n'
    )
    assert errors_of(text) == []


def test_terminator_is_dropped_from_the_value() -> None:
    text = HEADER + (
        '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S",\nstatus: initial;\n'
    )
    entry = parse(text).groups[0].entries[0]
    assert entry.source == "S"
    assert entry.status == "initial"


@pytest.mark.parametrize(
    "value",
    ['"a,b;"', '"trailing comma,"', '"semicolon;"', "'a,b;'"],
)
def test_terminators_inside_a_string_are_payload(value: str) -> None:
    text = HEADER + (
        f'\n[Video]\ntype: label\n\n<Resolution>\nsource: {value}\nstatus: initial\n'
    )
    entry = parse(text).groups[0].entries[0]
    assert entry.source == value[1:-1]


def test_a_list_trailing_comma_is_not_a_terminator() -> None:
    text = HEADER + (
        "\n[Video]\ntype: label\nemotion: [calm, neutral,]\n\n"
        '<Resolution>\nsource: "S"\nstatus: initial\n'
    )
    assert parse(text).groups[0].emotion == ["calm", "neutral"]


def test_list_trailing_comma_and_terminator_together() -> None:
    text = HEADER + (
        "\n[Video]\ntype: label\nemotion: [calm, neutral,];\n\n"
        '<Resolution>\nsource: "S"\nstatus: initial\n'
    )
    assert parse(text).groups[0].emotion == ["calm", "neutral"]


@pytest.mark.parametrize("tail", [";;", ",,", ", ;", "; ,", ";;;", ",, "])
def test_more_than_one_terminator_is_a_syntax_error(tail: str) -> None:
    text = HEADER + (
        f'\n[Video]\ntype: label\n\n<Resolution>\nsource: "S"{tail}\nstatus: initial\n'
    )
    with pytest.raises(CliffParseError, match="at most one trailing"):
        parse(text)


def test_the_error_carries_a_line_number_and_the_text() -> None:
    text = HEADER + '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S"\nstatus: initial;;\n'
    with pytest.raises(CliffParseError) as excinfo:
        parse(text)
    assert excinfo.value.line == 12
    assert "status: initial;;" in excinfo.value.text


def test_other_trailing_punctuation_is_not_a_terminator() -> None:
    text = HEADER + (
        '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S".\nstatus: initial\n'
    )
    with pytest.raises(CliffParseError):
        parse(text)


def test_serializer_never_emits_a_terminator() -> None:
    text = HEADER.replace("clan: settings\n", "clan: settings;\n") + (
        ";\n[Video],\ntype: label;\n\n<Resolution>;\nsource: \"S\";\nstatus: final,\n"
    )
    once = serialize(parse(text))
    assert ";" not in once
    assert once.endswith("status: final\n")
    # Canonical output is a fixed point of the round trip.
    assert serialize(parse(once)) == once


def test_terminators_are_not_reported_as_repairs() -> None:
    """A terminator is legal syntax, so tolerant mode has nothing to repair."""
    text = HEADER + (
        '\n[Video];\ntype: label,\n\n<Resolution>,\nsource: "S";\nstatus: initial,\n'
    )
    document, corrections = parse_tolerant(text)
    assert corrections == []
    assert document.corrections == []
    assert [i for i in validate(text, tolerant=True) if i.category == "correction"] == []


def test_style_check_recommends_against_terminators() -> None:
    text = HEADER + '\n[Video];\ntype: label\n\n<Resolution>\nsource: "S";\nstatus: initial\n'
    assert errors_of(text) == []
    style = [i for i in validate(text, style=True) if i.category == "style"]
    assert len(style) == 2, [i.message for i in style]
    assert all("terminator" in i.message for i in style)
    assert {i.line for i in style} == {7, 11}
