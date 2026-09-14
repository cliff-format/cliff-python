"""Regression tests for the normative rules of CLIFF 1.0."""

from __future__ import annotations

from pathlib import Path

import pytest

from cliff_format import (
    Entry,
    Group,
    effective_context,
    effective_emotion,
    effective_max_width,
    effective_type,
    parse,
    serialize,
    validate,
)
from cliff_format.errors import CliffParseError
from cliff_format.validator import _display_cells

HEADER = (
    "CLIFF 1.0\n"
    "namespace: demo\n"
    "clan: settings\n"
    "source-language: en-US\n"
    "target-language: zh-CN\n"
)


def document(*body: str) -> str:
    return HEADER + "\n[video]\ntype: label\n\n<resolution>\n" + "".join(body)


def errors_of(text: str, **kwargs: object) -> list[str]:
    issues = validate(text, **kwargs)  # type: ignore[arg-type]
    return [i.message for i in issues if i.category not in ("warning", "extension")]


# Specification 6.1 - list-typed fields are always lists


@pytest.mark.parametrize(
    "field",
    ["emotion: neutral\n", 'reference: "src/ui.cpp:12"\n'],
)
def test_list_fields_reject_bare_scalars(field: str) -> None:
    text = document('source: "Resolution"\nstatus: initial\n', field)
    with pytest.raises(CliffParseError, match="list-typed field"):
        parse(text)


def test_list_fields_accept_single_item_lists() -> None:
    text = document(
        'source: "Resolution"\nstatus: initial\n',
        "emotion: [neutral]\n",
        'reference: ["src/ui.cpp:12"]\n',
    )
    entry = parse(text).groups[0].entries[0]
    assert entry.emotion == ["neutral"]
    assert entry.reference == ["src/ui.cpp:12"]


def test_list_items_may_contain_apostrophes() -> None:
    """A single quote inside a double-quoted item must not split the list."""
    text = document(
        'source: "Resolution"\nstatus: initial\n',
        'reference: ["it\'s/here.cpp:1", "b.cpp:2"]\n',
    )
    assert parse(text).groups[0].entries[0].reference == ["it's/here.cpp:1", "b.cpp:2"]


def test_lists_never_nest() -> None:
    text = document('source: "R"\nstatus: initial\nreference: [["a"]]\n')
    with pytest.raises(CliffParseError, match="nested lists"):
        parse(text)


# Specification 6.1 - tags are unquoted names


def test_quoted_tag_is_rejected() -> None:
    with pytest.raises(CliffParseError, match="unquoted"):
        parse(document('source: "R"\nstatus: "initial"\n'))


# Specification 6.1 - continuation lines


def test_adjacent_string_continuation_concatenates_verbatim() -> None:
    text = (
        HEADER
        + 'info: "one "\n      "two"\n'
        + '\n[video]\ntype: label\n\n<a>\nsource: "S"\nstatus: initial\n'
    )
    assert parse(text).header.info == "one two"


def test_bare_list_continuation_extends_the_list() -> None:
    text = (
        HEADER
        + 'dependency: ["a.cliff"]\n            ["b.md", "c.md"]\n'
        + '\n[video]\ntype: label\n\n<a>\nsource: "S"\nstatus: initial\n'
    )
    assert parse(text).header.dependency == ["a.cliff", "b.md", "c.md"]


def test_blank_line_ends_a_continuation() -> None:
    text = HEADER + '\n[video]\ntype: label\n\n<a>\nsource: "S"\n\n"orphan"\n'
    with pytest.raises(CliffParseError, match="key"):
        parse(text)


# Specification 5 - tolerant lexical rules


def test_tolerant_input_is_accepted() -> None:
    """BOM, CRLF, equals separators, single quotes and stray whitespace."""
    text = (
        "\ufeffCLIFF 1.0\r\n"
        "namespace = demo\r\n"
        "  clan:settings\r\n"
        "source-language: en-US\r\n"
        "target-language: zh-CN\r\n"
        "\r\n"
        "# a developer note\r\n"
        "[video]\r\n"
        "type: label\r\n"
        "\r\n"
        "<resolution>\r\n"
        "source: 'Resolution'\r\n"
        'target: "分辨率"\r\n'
        "status: final\r\n"
    )
    entry = parse(text).groups[0].entries[0]
    assert entry.source == "Resolution"
    assert entry.status == "final"


def test_bare_carriage_return_is_rejected() -> None:
    with pytest.raises(CliffParseError, match="bare CR"):
        parse("CLIFF 1.0\rnamespace: demo\n")


# Specification 9 - group inheritance


def test_effective_values_follow_the_inheritance_rules() -> None:
    group = Group(path="video", context="Video screen.", type="label", max_width=12)
    entry = Entry(id="a", context="Toggle label.", max_width=8)
    assert effective_context(entry, group) == "Video screen. Toggle label."
    assert effective_type(entry, group) == "label"
    assert effective_max_width(entry, group) == 8
    assert effective_emotion(entry, group) == ["objective"]


def test_emotion_defaults_depend_on_the_effective_type() -> None:
    speech = Group(path="d", type="dialogue")
    assert effective_emotion(Entry(id="a"), speech) == ["neutral"]
    assert effective_emotion(Entry(id="a", type="label"), speech) == ["objective"]
    assert effective_emotion(Entry(id="a", emotion=["playful"]), speech) == ["playful"]


# Specification 10.2 - duplicate identifiers


def test_duplicate_entry_id_reports_both_occurrences() -> None:
    text = document(
        'source: "R"\nstatus: initial\n',
        '\n<resolution>\nsource: "R2"\nstatus: initial\n',
    )
    messages = errors_of(text)
    assert any("duplicate entry id" in m and "also declared on line" in m for m in messages)
    assert any("demo.settings.video.resolution" in m for m in messages)


# Specification 11 - file layout must agree with the header


def test_flat_layout_mismatch_is_reported(tmp_path_factory: pytest.TempPathFactory) -> None:
    text = document('source: "R"\nstatus: initial\n')
    assert errors_of(text, path=Path("settings.zh-CN.cliff")) == []
    assert any(
        "flat layout mismatch" in m
        for m in errors_of(text, path=Path("other.zh-CN.cliff"))
    )


def test_folder_layout_mismatch_is_reported() -> None:
    text = document('source: "R"\nstatus: initial\n')
    assert errors_of(text, path=Path("zh-CN/settings.cliff")) == []
    assert any(
        "folder layout mismatch" in m
        for m in errors_of(text, path=Path("ja-JP/settings.cliff"))
    )


def test_word_like_directories_are_not_language_tags() -> None:
    """A generated file in a plain directory simply skips the layout check."""
    text = document('source: "R"\nstatus: initial\n')
    assert errors_of(text, path=Path("fixtures/corpus.cliff")) == []


# Specification 15 - display width


@pytest.mark.parametrize(
    ("text", "cells"),
    [
        ("OK", 2),
        ("分辨率", 6),
        ("OK 分辨率", 9),
        ("cafe\u0301", 4),
        ("A\ufe0f", 1),
        ("\u2764\ufe0f", 2),
        ("\U0001f642", 2),
        ("\U0001f469\u200d\U0001f4bb", 2),
        ("\u0915\u093f", 1),
        ("\u200b", 0),
    ],
)
def test_display_cells(text: str, cells: int) -> None:
    assert _display_cells(text) == cells


def test_max_width_is_checked_against_the_rendered_target() -> None:
    text = document('source: "Resolution"\ntarget: "分辨率显示设置"\nstatus: final\nmax-width: 6\n')
    warnings = [i.message for i in validate(text, check_width=True) if i.category == "warning"]
    assert any("exceeds max-width" in m for m in warnings)
    assert not [i for i in validate(text) if i.category == "warning"]


# Specification 13 / 20 - variants and extensions


def test_standard_variant_without_entries_warns() -> None:
    text = HEADER + "\n[video]\ntype: label\n"
    warnings = [i.message for i in validate(text) if i.category == "warning"]
    assert "standard variant file has no entries" in warnings


def test_extension_fields_warn_and_round_trip_verbatim() -> None:
    text = (
        HEADER
        + 'x-note: "hello"\n'
        + '\n[video]\ntype: label\n\n<a>\nsource: "S"\nstatus: initial\nx-flag: 5\n'
    )
    issues = validate(text)
    assert [i.category for i in issues if i.category == "extension"] == ["extension"] * 2
    assert errors_of(text) == []
    assert serialize(parse(text)) == text


def test_unknown_non_extension_key_is_an_error() -> None:
    with pytest.raises(CliffParseError, match="unknown header key"):
        parse(HEADER + 'nickname: "x"\n')


# Specification 14 - ICU payloads


def test_icu_payloads_survive_a_round_trip() -> None:
    icu = "{count, plural, =0 {No messages} other {# messages}}"
    text = document(f'source: "{icu}"\nstatus: initial\n')
    parsed = parse(text)
    assert parsed.groups[0].entries[0].source == icu
    assert icu in serialize(parsed)


def test_unbalanced_icu_braces_are_reported() -> None:
    text = document('source: "{count, plural, other {# messages}"\nstatus: initial\n')
    assert any("brace" in m for m in errors_of(text))


# Diagnostics always locate the problem


@pytest.mark.parametrize(
    "body",
    [
        'source: "unterminated\nstatus: initial\n',
        'source: "bad\\q"\nstatus: initial\n',
        "source: [1]\nstatus: initial\n",
    ],
)
def test_value_errors_carry_a_line_number_and_the_offending_text(body: str) -> None:
    text = document(body)
    with pytest.raises(CliffParseError) as excinfo:
        parse(text)
    assert excinfo.value.line > 0
    assert excinfo.value.text
    assert excinfo.value.category


def test_validate_never_raises_and_reports_syntax_errors_as_issues() -> None:
    issues = validate(document('source: "unterminated\nstatus: initial\n'))
    assert issues
    assert issues[0].line > 0
    assert issues[0].category == "syntax"
