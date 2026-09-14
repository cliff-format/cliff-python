from __future__ import annotations

from pathlib import Path

import pytest

from cliff_format import (
    XLIFF_VERSIONS,
    CliffDocument,
    from_android_strings,
    from_csv,
    from_fluent,
    from_ios_strings,
    from_plain_json,
    from_po,
    from_xliff,
    from_yaml,
    load,
    parse,
    serialize,
    to_android_strings,
    to_csv,
    to_fluent,
    to_ios_strings,
    to_po,
    to_xliff,
    to_yaml,
    validate,
)
from cliff_format.errors import CliffError
from cliff_format.validator import effective_context

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "cliff_to_json" / "settings.zh-CN.cliff"

GLOSSARY_CLIFF = (
    "CLIFF 1.0\n"
    "namespace: studio\n"
    "clan: terms\n"
    "source-language: zh-CN\n"
    "target-language: en-US\n"
    "variant: glossary\n"
    "\n"
    "[combat]\n"
    "type: noun\n"
    "\n"
    "<iron-sword>\n"
    'source: "铁剑"\n'
    'target: "Iron Sword"\n'
    "status: final\n"
    'context: "Generic blade."\n'
)


def _assert_same_document(left: CliffDocument, right: CliffDocument) -> None:
    assert right.header.namespace == left.header.namespace
    assert right.header.clan == left.header.clan
    assert right.header.source_language == left.header.source_language
    assert right.header.target_language == left.header.target_language
    assert right.header.title == left.header.title
    assert right.header.info == left.header.info
    assert right.header.standard == left.header.standard
    assert right.header.dependency == left.header.dependency
    assert len(right.groups) == len(left.groups)

    for lg, rg in zip(left.groups, right.groups, strict=True):
        assert rg.path == lg.path
        assert rg.context == lg.context
        assert rg.type == lg.type
        assert rg.emotion == lg.emotion
        assert rg.max_width == lg.max_width
        assert len(rg.entries) == len(lg.entries)
        for le, re in zip(lg.entries, rg.entries, strict=True):
            assert re.id == le.id
            assert re.source == le.source
            assert re.target == le.target
            assert re.type == le.type
            assert re.emotion == le.emotion
            assert re.status == le.status
            assert re.context == le.context
            assert re.reference == le.reference
            assert re.reviewer == le.reviewer


def _assert_valid_cliff(doc: CliffDocument) -> None:
    text = serialize(doc)
    parse(text)
    issues = validate(text)
    errors = [issue for issue in issues if issue.category not in ("warning", "extension")]
    assert errors == [], [issue.as_dict() for issue in errors]


def test_yaml_roundtrip():
    doc = load(SAMPLE)
    result = from_yaml(to_yaml(doc))
    _assert_same_document(doc, result)
    _assert_valid_cliff(result)


def test_csv_roundtrip():
    doc = load(SAMPLE)
    result = from_csv(to_csv(doc))
    _assert_same_document(doc, result)
    _assert_valid_cliff(result)


def test_po_roundtrip():
    """PO keeps the group path in msgctxt and the attributes in comments."""
    document = load(SAMPLE)
    restored = from_po(to_po(document))
    assert restored.header.target_language == document.header.target_language
    assert [group.path for group in restored.groups] == [
        group.path for group in document.groups
    ]
    _assert_flat_roundtrip(document, restored)


def test_po_uses_its_own_metadata_channels():
    """References go to #:, the human comment to #., attributes to #. cliff:."""
    po_text = to_po(load(SAMPLE))
    assert "#. Video settings screen." in po_text
    assert "#. cliff:type: label" in po_text
    assert "#. cliff:max-width: 12" in po_text
    assert 'msgctxt "video.resolution"' in po_text


def test_po_import_treats_plain_comments_as_context_only():
    """A foreign PO file yields context plus defaults, never invented data."""
    po_text = (
        'msgid ""\nmsgstr ""\n"Language: zh-CN\\n"\n\n'
        "#. Shown on the settings screen.\n"
        "#: src/ui.cpp:42\n"
        'msgctxt "video.resolution"\n'
        'msgid "Resolution"\n'
        'msgstr "分辨率"\n'
    )
    entry = from_po(po_text).groups[0].entries[0]
    assert entry.context == "Shown on the settings screen."
    assert entry.reference == ["src/ui.cpp:42"]
    assert entry.type == "sentence"
    assert entry.emotion == []
    assert entry.max_width is None
    assert entry.reviewer is None


def test_xliff_roundtrip():
    doc = load(SAMPLE)
    result = from_xliff(to_xliff(doc))
    _assert_same_document(doc, result)
    _assert_valid_cliff(result)


def test_po_plural_import_maps_to_icu():
    po_text = '''msgid ""
msgstr ""
"Language: zh-CN\\n"

msgctxt "items.apple"
msgid "apple"
msgid_plural "apples"
msgstr[0] "苹果"
msgstr[1] "苹果们"
'''
    doc = from_po(po_text)
    entry = doc.groups[0].entries[0]
    assert "{count, plural" in (entry.source or "")
    assert "{count, plural" in (entry.target or "")
    assert entry.type == "sentence"
    assert entry.status == "translated"
    _assert_valid_cliff(doc)


def test_xliff_state_import_maps_to_status():
    """Legacy XLIFF 1.2 exports still import, and state becomes CLIFF status."""
    xliff_text = (
        '<xliff version="1.2">'
        '<file source-language="en-US" target-language="zh-CN"><body>'
        '<group id="main"><trans-unit id="hello" state="final">'
        "<source>Hello</source><target>你好</target>"
        "</trans-unit></group></body></file></xliff>"
    )
    doc = from_xliff(xliff_text)
    entry = doc.groups[0].entries[0]
    assert entry.id == "hello"
    assert entry.status == "final"
    _assert_valid_cliff(doc)


def test_fluent_roundtrip_preserves_attributes():
    document = load(SAMPLE)
    _assert_flat_roundtrip(document, from_fluent(to_fluent(document)))


def test_fluent_metadata_uses_comments_not_attributes():
    """Fluent attributes are translatable content, so metadata rides comments."""
    ftl = to_fluent(load(SAMPLE))
    assert "# cliff:type = label" in ftl
    assert ".type =" not in ftl


def test_fluent_comment_maps_to_context():
    doc = from_fluent("# Button label.\nresolution = 分辨率\n")
    assert doc.groups[0].entries[0].context == "Button label."
    _assert_valid_cliff(doc)


def _assert_flat_roundtrip(document: CliffDocument, restored: CliffDocument) -> None:
    """A flat format keeps every entry attribute through its comment channel."""
    group = document.groups[0]
    assert len(restored.groups[0].entries) == len(group.entries)
    for original, imported in zip(group.entries, restored.groups[0].entries, strict=True):
        assert imported.id == original.id
        assert imported.source == original.source
        assert imported.target == original.target
        assert imported.type == (original.type or group.type)
        assert imported.status == original.status
        assert imported.emotion == (original.emotion or group.emotion)
        assert imported.context == effective_context(original, group)
        assert imported.max_width == (
            original.max_width if original.max_width is not None else group.max_width
        )
    _assert_valid_cliff(restored)


def test_android_strings_roundtrip():
    document = load(SAMPLE)
    _assert_flat_roundtrip(document, from_android_strings(to_android_strings(document)))


def test_ios_strings_roundtrip():
    document = load(SAMPLE)
    _assert_flat_roundtrip(document, from_ios_strings(to_ios_strings(document)))


def test_android_comment_is_the_context_channel():
    """A plain Android comment becomes context; nothing else is invented."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?><resources>'
        "<!-- Shown on the settings screen. -->"
        '<string name="resolution">分辨率</string>'
        "</resources>"
    )
    entry = from_android_strings(xml).groups[0].entries[0]
    assert entry.context == "Shown on the settings screen."
    assert entry.type == "sentence"
    assert entry.emotion == []
    assert entry.reference == []


def test_ios_comment_is_the_context_channel():
    text = '/* Shown on the settings screen. */\n"resolution" = "分辨率";\n'
    entry = from_ios_strings(text).groups[0].entries[0]
    assert entry.context == "Shown on the settings screen."
    assert entry.type == "sentence"


def test_flat_formats_without_comments_only_get_defaults():
    """No comment means no context: importers must not invent one."""
    android = from_android_strings(
        '<resources><string name="a">A</string></resources>'
    ).groups[0].entries[0]
    ios = from_ios_strings('"a" = "A";\n').groups[0].entries[0]
    fluent = from_fluent("a = A\n").groups[0].entries[0]
    for entry in (android, ios, fluent):
        assert entry.context is None
        assert entry.emotion == []
        assert entry.reference == []
        assert entry.reviewer is None
        assert entry.max_width is None
        assert entry.type == "sentence"


def test_plain_json_import_does_not_invent_cliff_attributes():
    text = '{"menu.start": "开始", "menu.quit": "退出"}'
    doc = from_plain_json(text)
    assert len(doc.groups) == 1
    assert doc.groups[0].path == "menu"
    entries = doc.groups[0].entries
    assert len(entries) == 2
    assert entries[0].id == "start"
    assert entries[0].source == "menu.start"
    assert entries[0].target == "开始"
    assert entries[0].type == "sentence"
    assert entries[0].status == "translated"
    for entry in entries:
        assert entry.context is None
        assert entry.emotion == []
        assert entry.reference == []
        assert entry.max_width is None
        assert entry.reviewer is None
    _assert_valid_cliff(doc)


def test_xliff_uses_the_metadata_module():
    """The specification maps CLIFF attributes onto the XLIFF metadata module."""
    xml = to_xliff(load(SAMPLE))
    assert 'xmlns:mda="urn:oasis:names:tc:xliff:metadata:2.0"' in xml
    assert '<mda:metaGroup category="cliff">' in xml
    assert '<mda:meta type="type">label</mda:meta>' in xml
    # The human-readable context is also a plain note, which is what an XLIFF
    # editor shows to the translator.
    assert "<note>Video settings screen.</note>" in xml


def test_xliff_import_of_a_foreign_file_adds_no_metadata():
    """A note is translator context; nothing else may be inferred from it."""
    xml = (
        '<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.1" '
        'srcLang="en-US" trgLang="zh-CN"><file id="app" original="app">'
        '<group id="ui"><unit id="ok">'
        "<notes><note>Shown on the confirm button.</note></notes>"
        '<segment state="translated"><source>OK</source><target>确定</target>'
        "</segment></unit></group></file></xliff>"
    )
    document = from_xliff(xml)
    entry = document.groups[0].entries[0]
    assert entry.context == "Shown on the confirm button."
    assert entry.status == "translated"
    assert entry.type == "sentence"
    assert entry.emotion == []
    assert entry.max_width is None
    assert entry.reviewer is None
    assert document.header.variant == "standard"


def test_all_reverse_example_outputs_are_valid_cliff():
    examples = Path(__file__).resolve().parents[1] / "examples"
    files = sorted(examples.glob("*_to_cliff/*.cliff"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        parse(text)
        issues = validate(text)
        errors = [issue for issue in issues if issue.category not in ("warning", "extension")]
        assert errors == [], f"{path}: {[issue.as_dict() for issue in errors]}"


# XLIFF 2.x


@pytest.mark.parametrize("version", XLIFF_VERSIONS)
def test_xliff_versions_round_trip(version: str) -> None:
    """Every supported XLIFF version keeps the full CLIFF data model."""
    document = load(SAMPLE)
    xml = to_xliff(document, version=version)
    assert f'version="{version}"' in xml
    restored = from_xliff(xml)
    _assert_same_document(document, restored)
    _assert_valid_cliff(restored)


def test_unsupported_xliff_version_is_rejected() -> None:
    with pytest.raises(CliffError, match="unsupported XLIFF version"):
        to_xliff(load(SAMPLE), version="1.2")


def test_glossary_module_is_written_only_for_xliff_22_glossaries() -> None:
    glossary = parse(GLOSSARY_CLIFF)
    assert "<gls:glossary>" in to_xliff(glossary, version="2.2")
    assert "<gls:glossary>" not in to_xliff(glossary, version="2.1")
    assert "<gls:glossary>" not in to_xliff(load(SAMPLE), version="2.2")


def test_glossary_module_round_trips() -> None:
    glossary = parse(GLOSSARY_CLIFF)
    restored = from_xliff(to_xliff(glossary, version="2.2"))
    assert restored.header.variant == "glossary"
    _assert_same_document(glossary, restored)
    _assert_valid_cliff(restored)


def test_standalone_glossary_module_is_imported() -> None:
    """A foreign XLIFF 2.2 glossary with no units still yields CLIFF terms."""
    xml = (
        '<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" '
        'xmlns:gls="urn:oasis:names:tc:xliff:glossary:2.0" '
        'version="2.2" srcLang="zh-CN" trgLang="en-US">'
        '<file id="studio.terms" original="studio.terms"><gls:glossary>'
        '<gls:glossEntry ref="#studio.terms.combat.iron-sword">'
        '<gls:term source="cliff">铁剑</gls:term>'
        '<gls:translation id="iron-sword" source="cliff">Iron Sword</gls:translation>'
        '<gls:definition source="cliff">Generic blade.</gls:definition>'
        "</gls:glossEntry></gls:glossary></file></xliff>"
    )
    document = from_xliff(xml)
    assert document.header.variant == "glossary"
    _, entry = document.entries()[0]
    assert (entry.id, entry.source, entry.target) == ("iron-sword", "铁剑", "Iron Sword")
    assert entry.context == "Generic blade."




def test_csv_with_shifted_fields_raises_a_cliff_error() -> None:
    """A shifted CSV row must fail as a CliffError, never as a bare ValueError.

    A stray comma or a dropped header moves text into the max-width column.
    int() would raise ValueError from deep inside the converter, which tells a
    caller nothing; the error must name the column and the line instead.
    """
    from cliff_format import CliffError

    header = (
        "namespace,clan,source-language,target-language,version,variant,title,info,"
        "standard,dependency,group,group-context,group-type,group-emotion,"
        "group-max-width,id,source,target,type,emotion,status,context,max-width,"
        "reference,reviewer"
    )
    # The row below is what a shifted CSV looks like: a context sentence has
    # landed in the max-width column, where an integer belongs.
    shifted = (
        "demo,settings,en-US,zh-CN,,standard,,,,,video,,,,,resolution,Resolution,"
        "分辨率,label,,final,Dropdown label,Dropdown label on the video screen,,"
    )
    with pytest.raises(CliffError) as error:
        from_csv(header + "\n" + shifted + "\n")
    message = str(error.value)
    assert "max-width" in message
    assert "line" in message


def test_csv_without_shifted_fields_still_parses() -> None:
    header = (
        "namespace,clan,source-language,target-language,version,variant,title,info,"
        "standard,dependency,group,group-context,group-type,group-emotion,"
        "group-max-width,id,source,target,type,emotion,status,context,max-width,"
        "reference,reviewer"
    )
    row = (
        "demo,settings,en-US,zh-CN,,standard,,,,,video,,,,,resolution,Resolution,"
        "分辨率,label,,final,Dropdown label,12,,"
    )
    document = from_csv(header + "\n" + row + "\n")
    entry = document.groups[0].entries[0]
    assert entry.max_width == 12
    assert entry.target == "分辨率"
