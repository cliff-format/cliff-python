from __future__ import annotations

from cliff_format import (
    CliffParseError,
    from_dict,
    from_json,
    parse,
    serialize,
    to_dict,
    to_json,
    validate,
)

SAMPLE = """CLIFF 1.0
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN
title: "Demo"
info: "One "
      "Two"

[video]
type: label
emotion: [objective]
max-width: 12

<resolution>
source: "Resolution"
target: "分辨率"
status: final
reference: ["src/ui/video.cpp:42"]
"""


def test_parse_minimal():
    doc = parse(SAMPLE)
    assert doc.header.namespace == "demo"
    assert doc.header.clan == "settings"
    assert doc.header.source_language == "en-US"
    assert doc.header.target_language == "zh-CN"
    assert doc.header.title == "Demo"
    assert doc.header.info == "One Two"

    assert len(doc.groups) == 1
    group = doc.groups[0]
    assert group.path == "video"
    assert group.type == "label"
    assert group.emotion == ["objective"]
    assert group.max_width == 12

    entry = group.entries[0]
    assert entry.id == "resolution"
    assert entry.source == "Resolution"
    assert entry.target == "分辨率"
    assert entry.status == "final"
    assert entry.reference == ["src/ui/video.cpp:42"]


def test_duplicate_field_raises():
    text = """CLIFF 1.0
namespace: demo
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN
"""
    try:
        parse(text)
    except CliffParseError as exc:
        assert exc.category == "semantic"
        assert "may appear at most once" in exc.message
    else:
        raise AssertionError("expected duplicate header field to fail")


def test_serializer_canonical_roundtrip():
    doc = parse(SAMPLE)
    output = serialize(doc)
    assert output.startswith("CLIFF 1.0\n")
    assert "\nnamespace: demo\n" in output
    assert "\n[video]\n" in output
    assert "\n<resolution>\n" in output
    assert 'target: "分辨率"' in output

    doc2 = parse(output)
    assert doc2.header.namespace == doc.header.namespace
    assert doc2.header.info == doc.header.info
    assert doc2.groups[0].entries[0].target == doc.groups[0].entries[0].target


def test_validate_ok():
    assert validate(SAMPLE) == []


def test_validate_missing_type():
    text = """CLIFF 1.0
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN

[video]

<resolution>
source: "Resolution"
status: final
"""
    issues = validate(text)
    assert any(i.category == "semantic" and "type" in i.message for i in issues)


def test_validate_bad_status_and_icu():
    text = """CLIFF 1.0
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN

[video]
type: label

<bad>
source: "Hello {"
target: "你好"
status: final
"""
    issues = validate(text)
    assert any(i.category == "icu" for i in issues)
    # The sample uses a valid status, so it should not report a semantic
    # "requires a target" error.
    assert not any(i.category == "semantic" and "requires a target" in i.message for i in issues)


def test_validate_reviewed_without_target():
    text = """CLIFF 1.0
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN

[video]
type: label

<bad>
source: "Hello"
status: reviewed
"""
    issues = validate(text)
    assert any(i.category == "semantic" and "requires a target" in i.message for i in issues)


def test_json_roundtrip():
    doc = parse(SAMPLE)
    data = to_dict(doc)
    assert data["header"]["source-language"] == "en-US"
    assert data["groups"][0]["entries"][0]["target"] == "分辨率"

    doc2 = from_dict(data)
    assert doc2.header.namespace == doc.header.namespace
    assert doc2.groups[0].entries[0].source == doc.groups[0].entries[0].source

    text = to_json(doc)
    doc3 = from_json(text)
    assert doc3.groups[0].path == doc.groups[0].path
    assert doc3.groups[0].entries[0].status == doc.groups[0].entries[0].status
