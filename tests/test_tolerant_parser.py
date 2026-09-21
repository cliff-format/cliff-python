"""Tolerant parsing (specification Appendix C).

The seven permitted relaxations, the repairs that are forbidden, and the two
invariants that make the mode usable in a pipeline:

* every repair is reported (an unreported repair is data loss), and
* the result is valid under the strict grammar (fixing the input is the point).

Each relaxation is tested twice: the strict parser must reject the input, and
the tolerant parser must accept it and produce the expected value. If the strict
half stops failing, the test is no longer proving anything.
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

ENTRY = '<Resolution>\nsource: "S"\nstatus: initial\n'


def document(*body: str, group: str = "[Video]", entry: str = ENTRY) -> str:
    return HEADER + f"\n{group}\ntype: label\n\n{entry}" + "".join(body)


def categories(corrections: list) -> list[str]:
    return [c.category for c in corrections]


def strict_errors(text: str) -> list[str]:
    issues = validate(text)
    return [i.message for i in issues if i.category not in ("warning", "extension", "style")]


def assert_strict_rejects(text: str) -> None:
    with pytest.raises(CliffParseError):
        parse(text)


# --- C.2.1 a bare scalar in a list-typed field ------------------------------


def test_bare_emotion_becomes_a_one_item_list() -> None:
    text = document("emotion: objective\n")
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].emotion == ["objective"]
    assert "list-shape" in categories(corrections)
    assert corrections[0].before == "objective"
    assert corrections[0].after == "[objective]"


def test_bare_dependency_becomes_a_one_item_list() -> None:
    text = HEADER.replace(
        "target-language: zh-CN\n",
        'target-language: zh-CN\ndependency: "../shared/terms.zh-CN.cliff"\n',
    ) + "\n[Video]\ntype: label\n\n" + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.header.dependency == ["../shared/terms.zh-CN.cliff"]
    assert "list-shape" in categories(corrections)


def test_bare_reference_becomes_a_one_item_list() -> None:
    text = document('reference: "src/ui.cpp:12"\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].reference == ["src/ui.cpp:12"]
    assert "list-shape" in categories(corrections)


def test_bare_comma_series_becomes_a_multi_item_list() -> None:
    text = document("emotion: calm, neutral\n")
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].emotion == ["calm", "neutral"]
    assert corrections[0].after == "[calm, neutral]"


def test_nested_list_is_flattened() -> None:
    text = document("reference: [[\"a\"], [\"b\"]]\n")
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].reference == ["a", "b"]
    assert "list-shape" in categories(corrections)


# --- C.2.2 a repeated field -------------------------------------------------


def test_repeated_list_field_appends() -> None:
    text = document(
        'reference: ["a.cpp:1"]\n',
        'reference: ["b.cpp:2"]\n',
    )
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].reference == ["a.cpp:1", "b.cpp:2"]
    assert "field-repeat" in categories(corrections)


def test_repeated_string_field_concatenates_without_a_separator() -> None:
    text = document('target: "one "\n', 'target: "two"\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].target == "one two"
    assert "field-repeat" in categories(corrections)


def test_repeated_header_field_concatenates() -> None:
    text = HEADER.replace(
        "target-language: zh-CN\n",
        'target-language: zh-CN\ninfo: "a"\ninfo: "b"\n',
    )
    text += "\n[Video]\ntype: label\n\n" + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.header.info == "ab"
    assert "field-repeat" in categories(corrections)


def test_repeated_field_reports_every_line() -> None:
    text = document('reference: ["a"]\n', 'reference: ["b"]\n')
    _, corrections = parse_tolerant(text)
    repeat = [c for c in corrections if c.category == "field-repeat"]
    assert len(repeat) == 1
    assert repeat[0].line == 14


# --- C.2.3 a quoted tag -----------------------------------------------------


@pytest.mark.parametrize(
    ("body", "attr", "expected"),
    [
        ('status: "final"\n', "status", "final"),
        ("status: 'final'\n", "status", "final"),
        ('type: "noun"\n', "type", "noun"),
    ],
)
def test_quoted_tag_is_unwrapped(body: str, attr: str, expected: str) -> None:
    text = document(body, entry='<A>\nsource: "S"\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert getattr(parsed.groups[0].entries[0], attr) == expected
    assert "tag-quote" in categories(corrections)


def test_quoted_list_item_in_emotion() -> None:
    text = document('emotion: ["calm"]\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].emotion == ["calm"]
    assert "tag-quote" in categories(corrections)


def test_tag_casing_is_folded_only_to_a_vocabulary_word() -> None:
    text = document("status: Final\n", entry='<A>\nsource: "S"\n')
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].status == "final"
    assert "casing" in categories(corrections)


def test_a_tag_that_is_not_a_vocabulary_word_is_still_an_error() -> None:
    """Tolerant mode folds a spelling; it never guesses a word."""
    with pytest.raises(CliffParseError) as excinfo:
        parse(document("status: Finished\n", entry='<A>\nsource: "S"\n'), tolerant=True)
    assert excinfo.value.category == "vocabulary"
    assert "allowed:" in excinfo.value.message


# --- C.2.4 a quoted entry id ------------------------------------------------


@pytest.mark.parametrize("marker", ['<"Resolution">', "<'Resolution'>"])
def test_quoted_entry_id(marker: str) -> None:
    text = document("", entry=marker + '\nsource: "S"\nstatus: initial\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].id == "Resolution"
    assert "name-quote" in categories(corrections)


# --- C.2.5 an identifier with a reserved character --------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<Inv Sword>", "Inv-Sword"),
        ("<Save & Load>", "Save-Load"),
        ("<a/b>", "a-b"),
        ("<200%>", "200"),
        ("<   >", "entry"),
    ],
)
def test_entry_id_is_normalized(raw: str, expected: str) -> None:
    text = document("", entry=raw + '\nsource: "S"\nstatus: initial\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].id == expected
    assert "name-normalized" in categories(corrections)


def test_group_path_segments_are_normalized() -> None:
    text = document("", group="[Video Setup & Audio]")
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].path == "Video-Setup-Audio"
    assert "name-normalized" in categories(corrections)


def test_namespace_and_clan_are_left_alone_when_valid() -> None:
    text = HEADER.replace("namespace: demo", "namespace: Demo").replace(
        "clan: settings", "clan: Act3_Strings"
    )
    text += "\n[Video]\ntype: label\n\n" + ENTRY
    parsed, corrections = parse_tolerant(text)
    assert parsed.header.namespace == "Demo"
    assert parsed.header.clan == "Act3_Strings"
    assert categories(corrections) == []


# --- C.4 collisions ---------------------------------------------------------


def test_markup_is_not_an_entry_marker_and_is_not_normalized_into_one() -> None:
    """Specification C.2.5 applies to an identifier, and a closing tag is not one.

    Without the guard the tolerant reading normalized ``/terms`` into ``terms``
    (C.3 step 4 replaces the slash, step 6 strips it), so a stray closing tag became
    an entry with no fields and the document then failed on that entry's required
    fields - an entry the answer never contained, which is the guessing C.5 forbids.
    """
    for markup in ("</terms>", "<.hidden>"):
        text = document("", entry=ENTRY) + f"\n{markup}\n"
        try:
            parse_tolerant(text)
        except Exception as exc:  # noqa: BLE001 - the assertion is on the message
            assert "key: value" in str(exc), exc
        else:
            raise AssertionError(f"{markup} was read as an entry marker")


def test_markup_is_not_a_section() -> None:
    text = document("", group="[/terms]")
    try:
        parse_tolerant(text)
    except Exception as exc:  # noqa: BLE001
        assert "key: value" in str(exc), exc
    else:
        raise AssertionError("a closing tag was read as a section line")


def test_an_identifier_relaxation_still_accepts_leading_whitespace() -> None:
    """The guard must not narrow C.2.5: C.3 strips surrounding whitespace (step 2)."""
    text = document("", entry="<  resolution  >" + '\nsource: "S"\nstatus: initial\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].id == "resolution"
    assert "name-normalized" in categories(corrections)


# --- C.4 collisions ---------------------------------------------------------


def duplicate_id_document() -> str:
    """A document with two entries that spell the same id.

    Built literally rather than through :func:`document`, because the point is
    two complete entries rather than one entry plus extra fields.
    """
    return (
        HEADER
        + "\n[Video]\ntype: label\n\n"
        + '<Resolution>\nsource: "first"\nstatus: initial\n'
        + '\n<Resolution>\nsource: "second"\nstatus: initial\n'
    )


def test_duplicate_entry_id_is_disambiguated_not_overwritten() -> None:
    parsed, corrections = parse_tolerant(duplicate_id_document())
    entries = parsed.groups[0].entries
    assert [e.id for e in entries] == ["Resolution", "Resolution-2"]
    assert entries[0].source == "first"
    assert entries[1].source == "second"
    collision = [c for c in corrections if c.category == "id-collision"]
    assert len(collision) == 1
    assert collision[0].before == "Resolution"
    assert collision[0].after == "Resolution-2"
    # The repaired document is valid under the strict grammar.
    strict = validate(serialize(parsed))
    assert [i.message for i in strict if i.category not in ("warning", "extension")] == []


def test_normalization_collision_is_also_disambiguated() -> None:
    text = document(
        'source: "A"\nstatus: initial\n',
        '\n<Save & Load>\nsource: "B"\nstatus: initial\n'
        '\n<Save/Load>\nsource: "C"\nstatus: initial\n',
    )
    parsed, corrections = parse_tolerant(text)
    assert [e.id for e in parsed.groups[0].entries] == [
        "Resolution",
        "Save-Load",
        "Save-Load-2",
    ]
    assert len([c for c in corrections if c.category == "id-collision"]) == 1


def test_duplicate_entry_id_is_still_a_hard_error_in_strict_mode() -> None:
    issues = validate(duplicate_id_document())
    assert any(i.category == "id" and "duplicate entry id" in i.message for i in issues)
    assert any(i.category == "id" and "duplicate canonical id" in i.message for i in issues)


def test_duplicate_section_is_disambiguated() -> None:
    text = (
        HEADER
        + '\n[Video]\ntype: label\n\n<A>\nsource: "S"\nstatus: initial\n'
        + '\n[Video]\ntype: label\n\n<B>\nsource: "S"\nstatus: initial\n'
    )
    parsed, corrections = parse_tolerant(text)
    assert [g.path for g in parsed.groups] == ["Video", "Video-2"]
    assert "id-collision" in categories(corrections)


# --- C.2.6 the version line -------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("CLIFF 1.1.0", "1.1"),
        ("CLIFF 1.0.0", "1.0"),
        ("cliff 1.1", "1.1"),
        ("Cliff 1.1", "1.1"),
    ],
)
def test_version_line_spelling_is_tolerated(line: str, expected: str) -> None:
    text = line + "\n" + HEADER[len("CLIFF 1.1\n") :] + "\n[Video]\ntype: label\n\n" + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.spec_version == expected
    assert "version" in categories(corrections)


def test_version_line_trailing_whitespace_is_already_tolerated() -> None:
    """Whitespace around the version line is 1.0 grammar, so tolerant mode is quiet."""
    text = "CLIFF 1.1 \n" + HEADER[len("CLIFF 1.1\n") :] + "\n[Video]\ntype: label\n\n" + ENTRY
    assert parse(text).spec_version == "1.1"
    parsed, corrections = parse_tolerant(text)
    assert parsed.spec_version == "1.1"
    assert categories(corrections) == []


def test_version_line_is_not_guessed_from_content() -> None:
    with pytest.raises(CliffParseError, match="unsupported CLIFF version"):
        parse(document("").replace("CLIFF 1.1", "CLIFF 1.2"), tolerant=True)
    with pytest.raises(CliffParseError, match="unsupported CLIFF version"):
        parse(document("").replace("CLIFF 1.1", "CLIFF 2.0"), tolerant=True)


def test_missing_version_line_is_reported_not_guessed() -> None:
    text = HEADER[len("CLIFF 1.1\n") :] + "\n[Video]\ntype: label\n\n" + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.spec_version == "1.1"
    assert "version" in categories(corrections)
    assert corrections[0].line == 0


# --- C.2.7 a quoted key -----------------------------------------------------


@pytest.mark.parametrize("marker", ['"context"', "'context'"])
def test_quoted_key_is_unquoted(marker: str) -> None:
    text = document(f'{marker}: "Toolbar button."\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].context == "Toolbar button."
    assert "name-quote" in categories(corrections)
    assert corrections[0].before == marker
    assert corrections[0].after == "context"


def test_quoted_key_works_with_the_equals_separator() -> None:
    text = document('"context" = "Toolbar button."\n')
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].entries[0].context == "Toolbar button."
    assert "name-quote" in categories(corrections)


def test_quoted_key_is_read_in_header_scope() -> None:
    text = HEADER.replace(
        "target-language: zh-CN\n", 'target-language: zh-CN\n"title": "T"\n'
    ) + "\n[Video]\ntype: label\n\n" + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.header.title == "T"
    assert "name-quote" in categories(corrections)


def test_quoted_key_is_read_in_group_scope() -> None:
    text = HEADER + '\n[Video]\ntype: label\n"context": "Group context."\n\n' + ENTRY
    assert_strict_rejects(text)
    parsed, corrections = parse_tolerant(text)
    assert parsed.groups[0].context == "Group context."
    assert "name-quote" in categories(corrections)


def test_quoted_key_does_not_widen_the_key_sets() -> None:
    """The repair removes quotes; it never legalizes a word (C.5)."""
    with pytest.raises(CliffParseError, match="unknown entry key 'translater'"):
        parse(document('"translater": "x"\n'), tolerant=True)


def test_quoted_key_does_not_move_a_key_into_another_scope() -> None:
    """`status` is entry-only, and quoting it does not change that."""
    text = HEADER + '\n[Video]\ntype: label\n"status": translated\n\n' + ENTRY
    with pytest.raises(CliffParseError, match="unknown group key 'status'"):
        parse(text, tolerant=True)


def test_quoted_key_is_not_escape_processed() -> None:
    """The enclosed text must be a name, so a parser never guesses where it ends."""
    with pytest.raises(CliffParseError, match="invalid field name"):
        parse(document('"con\\ttext": "x"\n'), tolerant=True)


def test_quoted_key_does_not_steal_a_continuation_line() -> None:
    """A line of quoted strings continues the value; only a separator makes it a key."""
    text = document('context: "a"\n  "b: c"\n')
    parsed = parse(text)
    assert parsed.groups[0].entries[0].context == "ab: c"
    tolerant, corrections = parse_tolerant(text)
    assert tolerant.groups[0].entries[0].context == "ab: c"
    assert categories(corrections) == []


# --- C.5 repairs that are forbidden ----------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        'target: "t"\n',  # missing source
        'source: "S"\n',  # missing status
    ],
)
def test_missing_required_fields_are_not_repaired(body: str) -> None:
    text = document("", entry="<A>\n" + body)
    parsed, _ = parse_tolerant(text)
    issues = validate(serialize(parsed), tolerant=False)
    assert [i for i in issues if i.category == "semantic"], (
        "a missing required field must still be reported, never invented"
    )


def test_missing_type_is_not_invented() -> None:
    text = HEADER + '\n[Video]\n\n<A>\nsource: "S"\nstatus: initial\n'
    parsed, _ = parse_tolerant(text)
    assert parsed.groups[0].entries[0].type is None
    issues = validate(serialize(parsed))
    assert any("missing required field 'type'" in i.message for i in issues)


def test_unbalanced_icu_is_not_repaired() -> None:
    text = document('target: "a {b"\n')
    parsed, _ = parse_tolerant(text)
    issues = validate(serialize(parsed))
    assert any(i.category == "icu" for i in issues)


def test_status_target_contradiction_is_not_repaired() -> None:
    """Only the failing half of the status/target rule is reported."""
    # reviewed without a target: the contradiction exists and is reported.
    missing = document('status: reviewed\n', entry='<A>\nsource: "S"\n')
    parsed, _ = parse_tolerant(missing)
    assert any("requires a target" in i.message for i in validate(serialize(parsed)))

    # reviewed with a target: nothing to report, and nothing invented either.
    contradiction = document("", entry='<B>\nsource: "S"\ntarget: "t"\nstatus: reviewed\n')
    parsed, _ = parse_tolerant(contradiction)
    serialized = serialize(parsed)
    assert 'target: "t"' in serialized
    errors = [
        i.message
        for i in validate(serialized)
        if i.category not in ("warning", "extension")
    ]
    assert errors == []

    # initial with a target: a warning, never a silent fix.
    initial = document("", entry='<C>\nsource: "S"\ntarget: "t"\nstatus: initial\n')
    parsed, _ = parse_tolerant(initial)
    assert any(
        "status is 'initial'" in i.message for i in validate(serialize(parsed), tolerant=False)
    )


@pytest.mark.parametrize("line", ["this is not a field\n", "]dangling[\n"])
def test_malformed_lines_are_rejected_not_discarded(line: str) -> None:
    """A line that is not a field must not be swallowed like a comment."""
    text = document(line)
    with pytest.raises(CliffParseError):
        parse(text, tolerant=True)


def test_unknown_non_extension_key_is_an_error() -> None:
    with pytest.raises(CliffParseError, match="unknown entry key"):
        parse(document('nickname: "x"\n'), tolerant=True)


# --- C.6 the output guarantee ----------------------------------------------


def test_tolerant_output_is_strict_valid_and_idempotent() -> None:
    text = document(
        'target: "a"\n',
        'target: "b"\n',
        'emotion: calm, neutral\n',
        "",
        entry='<Save & Load>\nsource: "S"\nstatus: "final"\nreference: "src/a.cpp:1"\n',
    )
    parsed, corrections = parse_tolerant(text)
    assert corrections, "the input has repairs; the report must not be empty"
    once = serialize(parsed)
    strict_issues = validate(once)
    errors = [i for i in strict_issues if i.category not in ("warning", "extension")]
    assert errors == [], [i.message for i in errors]
    assert serialize(parse(once)) == once


def test_tolerant_parsing_can_be_selected_explicitly_and_has_a_default() -> None:
    """Strict is the default; the mode is never chosen for the caller."""
    text = document("emotion: objective\n")
    with pytest.raises(CliffParseError):
        parse(text)
    assert parse(text, tolerant=True).groups[0].entries[0].emotion == ["objective"]


def test_correct_parse_reports_nothing() -> None:
    text = HEADER + (
        '\n[Video]\ntype: label\n\n<Resolution>\nsource: "S"\nstatus: final\ntarget: "T"\n'
    )
    _, corrections = parse_tolerant(text)
    assert corrections == []


def test_corrections_are_recorded_on_the_document_too() -> None:
    parsed, corrections = parse_tolerant(document("emotion: objective\n"))
    assert parsed.corrections == corrections
