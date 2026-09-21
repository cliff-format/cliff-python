# cliff_format

Official Python implementation for [CLIFF 1.0 / 1.1](https://github.com/cliff-format/cliff) — the Contextual Localization Integrated File Format.

`cliff_format` provides the core pieces needed by a Python localization toolchain:

- **Parser** — read CLIFF text/files into a typed Python data model, in a **strict** mode that rejects everything the grammar rejects and a **tolerant** mode that repairs the documented format errors of an AI translation workflow.
- **Serializer** — write the data model back as canonical CLIFF, preserving the spec version the document declared.
- **Validator** — check required fields, fixed vocabularies, status rules, duplicate IDs, ICU brace balance, file layout, rendered display width, plus opt-in layout enforcement and style checking.
- **Converter** — bidirectional conversions for JSON, YAML, CSV, PO, XLIFF, Fluent, Android strings.xml, iOS Localizable.strings.

## Status

The parser, serializer, validator, and converters target CLIFF 1.1 and are checked against the normative specification examples (1.0 and 1.1) and the `cliff-test` conformance fixtures — the valid, invalid, layout, style, and tolerant suites.

## Installation

```bash
pip install cliff-python
```

For development:

```bash
git clone https://github.com/cliff-format/cliff-python.git
cd cliff-python
pip install -e ".[dev]"
```

## Quick start

```python
import cliff_format

text = '''CLIFF 1.1
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN

[Video]
type: label

<Resolution>
source: "Resolution"
target: "分辨率"
status: final
'''

doc = cliff_format.parse(text)
print(doc.header.namespace)          # demo
print(doc.spec_version)              # 1.1 — the version the document declared
print(doc.groups[0].path)            # Video
print(doc.groups[0].entries[0].id)   # Resolution
print(doc.groups[0].entries[0].target)

print(cliff_format.serialize(doc))

issues = cliff_format.validate(text)
for issue in issues:
    print(issue.line, issue.category, issue.message)
```

## Strict and tolerant parsing

CLIFF 1.1 defines two readings of the same syntax, and `cliff_format` exposes
both. Strict is the default; the mode is never chosen for you.

**Strict** (`parse`, `load`) rejects everything the grammar rejects, and accepts
everything it accepts:

- identifiers may use `A-Z a-z 0-9 _ -` and never `.`, are case-sensitive, and
  are **never rewritten** — `bad_id` and `BadVersion` stay as written, because
  an identifier is a translation match key;
- tags (`type`, `emotion`, `status`, `variant`) are the one thing 1.1 did **not**
  relax: lowercase words from a closed vocabulary;
- one optional trailing `,` or `;` per line is standard syntax, means nothing,
  and is never re-emitted by the serializer;
- a file-layout mismatch is a **warning** (the layout is a recommendation);
- resource limits (documented and configurable) are enforced.

**Tolerant** (`parse(..., tolerant=True)`, `parse_tolerant`) additionally applies
the seven relaxations of specification Appendix C and reports every repair:

| Relaxation | Input | Result |
| --- | --- | --- |
| C.2.1 bare scalar in a list-typed field | `emotion: objective` | `["objective"]` |
| C.2.2 repeated field in one scope | two `target:` lines | concatenated / appended in order |
| C.2.3 quoted tag | `status: "final"` | `final` |
| C.2.4 quoted entry id | `<"resolution">` | `resolution` |
| C.2.5 identifier with a reserved character | `<Save & Load>` | `Save-Load` (+ collision handling) |
| C.2.6 version-line spelling | `cliff 1.1.0` | `CLIFF 1.1` |
| C.2.7 quoted key | `"context": "…"` | `context: "…"` |

C.2.7 removes the quotes and nothing else: the enclosed text must be a `name`, no
escape is processed, and the key is then checked against the legal keys of its
scope exactly as a bare key is. A quoted word that is not a legal key, or a key
quoted in a scope that does not allow it, is still an error (§C.5) — the
relaxation cannot legalize a word.

Every repair is recorded, so nothing is fixed silently:

```python
doc, corrections = cliff_format.parse_tolerant(text)
for c in corrections:
    print(c.line, c.category, c.message, c.before, "->", c.after)
```

Categories: `list-shape`, `field-repeat`, `tag-quote`, `name-quote`,
`name-normalized`, `id-collision`, `version`, `casing`. A category names the
operation, not the clause, so `name-quote` covers both a quoted entry id (C.2.4)
and a quoted key (C.2.7).

And the mode never guesses. Appendix C.5 lists what a tolerant parser MUST
refuse — a missing required field, a word outside a closed vocabulary, an
unbalanced ICU brace, a malformed line, an unsupported version — and those raise
`CliffParseError` with a line number and a category, exactly as in strict mode.

Two guarantees make the mode usable in a pipeline:

```python
# 1. the repaired document is valid under the strict grammar
once = cliff_format.serialize(doc)
assert not [i for i in cliff_format.validate(once) if i.category not in ("warning", "extension")]

# 2. canonical output is a fixed point
assert cliff_format.serialize(cliff_format.parse(once)) == once
```

## Command line

```bash
cliff_format parse path/to/file.cliff
cliff_format serialize path/to/file.cliff
cliff_format validate path/to/file.cliff
cliff_format convert path/to/file.cliff --format po
cliff_format convert path/to/file.po --from po --format cliff

# Tolerant reading of a model's output, with the repair report on stderr
cliff_format parse path/to/model-output.cliff --tolerant
cliff_format validate path/to/model-output.cliff --tolerant
cliff_format convert path/to/model-output.cliff --tolerant --format json

# Opt-in checks: a layout mismatch as an error, style deviations as warnings
cliff_format validate path/to/file.cliff --check-layout
cliff_format validate path/to/file.cliff --style
cliff_format validate path/to/file.cliff --check-width

# Canonical output for a specific version, or with a canonical id style applied
cliff_format serialize path/to/file.cliff --spec-version 1.0
cliff_format serialize path/to/file.cliff --style
```

Supported convert formats: `cliff`, `json`, `yaml`, `csv`, `po`, `xliff`, `fluent`, `android`, `ios`.

`validate` exits `1` when the file has errors and `0` when it only has warnings, extension notes, corrections, or style findings. Every diagnostic carries a line number, a category, and the offending line.

## API overview

| Function | Description |
| --- | --- |
| `cliff_format.parse(text, path=None, tolerant=False, corrections=None, **limits)` | Parse CLIFF text into `CliffDocument`. |
| `cliff_format.parse_tolerant(text, path=None)` | Parse in tolerant mode; returns `(document, corrections)`. |
| `cliff_format.load(path, tolerant=False)` | Read and parse a `.cliff` file. |
| `cliff_format.serialize(doc, style=False)` | Serialize a `CliffDocument` to canonical CLIFF text. |
| `cliff_format.validate(text, check_width=False, check_layout=False, style=False, tolerant=False)` | Validate CLIFF text and return `list[ValidationIssue]`. |
| `cliff_format.validate_document(doc, check_width=False, check_layout=False, style=False)` | Validate an already parsed document. |
| `cliff_format.effective_context / effective_type / effective_emotion / effective_max_width` | Resolve a group-inherited value for one entry. |
| `cliff_format.is_name / is_tag / is_style_identifier / normalize_identifier / strip_line_terminator` | The identifier rules of specification §5.5 and Appendix C.3, and the terminator rule of §5.6. |
| `cliff_format.to_dict(doc)` / `cliff_format.from_dict(data)` | Convert between `CliffDocument` and a JSON-shaped dict. |
| `cliff_format.to_json(doc)` / `cliff_format.from_json(text)` | Convert between `CliffDocument` and JSON text. |

### Diagnostics

| Category | Meaning |
| --- | --- |
| `syntax`, `semantic`, `vocabulary`, `icu`, `id` | Errors: the file does not conform. |
| `warning` | A recommendation (layout mismatch, glossary shape, width overflow). |
| `extension` | An `x-` field was ignored, as the specification requires. |
| `correction` | A tolerant parse repaired something; reports `before` → `after`. |
| `style` | A deviation from the style guide (`--style`); never an error. |

### Resource limits

`parse` and `load` accept `max_lines`, `max_line_length`, and
`max_string_length`; the defaults bound a document at 1 000 000 lines, 1 MiB per
line, and 1 MiB per decoded string. Exceeding a limit raises a located error
instead of exhausting memory. The limits apply in strict and tolerant mode alike
(specification §19).

## Converter support

Current converter is **bidirectional** for:

- JSON (`to_json` / `from_json`, as well as `to_dict` / `from_dict`; `from_plain_json` for flat/nested localization JSON such as Minecraft-style files)
- YAML (`to_yaml` / `from_yaml`, requires PyYAML)
- CSV (`to_csv` / `from_csv`)
- PO (`to_po` / `from_po`)
- XLIFF 2.x (`to_xliff` / `from_xliff`); `to_xliff(doc, version="2.0" | "2.1" | "2.2")`, default `2.1`. Version `2.2` also writes the XLIFF 2.2 glossary module for a `variant: glossary` document, and `from_xliff` reads that module (and legacy XLIFF 1.2 exports)
- Fluent (`to_fluent` / `from_fluent`)
- Android strings.xml (`to_android_strings` / `from_android_strings`)
- iOS Localizable.strings (`to_ios_strings` / `from_ios_strings`)

API example:

```python
# CLIFF -> other format
po_text = cliff_format.to_po(doc)
yaml_text = cliff_format.to_yaml(doc)

# other format -> CLIFF
doc = cliff_format.from_po(po_text)
doc = cliff_format.from_yaml(yaml_text)
```

### Metadata channels

CLIFF carries context as first-class data, and every converter moves that data
through the target format's own documented metadata channel — never through an
invented one:

| Format | Channel used for CLIFF attributes | Channel used for context |
| --- | --- | --- |
| JSON / YAML / CSV | native fields of the CLIFF-shaped document | native field |
| XLIFF 2.x | metadata module (`mda:metadata` / `mda:metaGroup category="cliff"` / `mda:meta`), plus `state` on `segment` for status | `mda:meta type="context"` and a plain `note` |
| XLIFF 2.2 glossary | additionally the glossary module (`gls:glossEntry`) for `variant: glossary` | `gls:definition` |
| gettext PO | extracted comments `#. cliff:<key>: <value>`; `#:` for references; `msgctxt` for the group path and entry id | plain `#.` comment |
| Fluent | message comment `# cliff:<key> = <value>` (attributes are translatable content, so they are not used for metadata) | plain `#` comment |
| Android strings.xml | XML comment above the resource, `cliff:<key>: <value>` | first line of that comment |
| iOS Localizable.strings | `/* ... */` block comment above the pair, `cliff:<key>: <value>` | first line of that comment |

Because formats without a group level cannot express inheritance, the exporters
fold the group values into each entry (the effective context, type, emotion and
max-width) so nothing is lost.

The reverse direction is deliberately conservative. An importer reads only the
metadata the source format actually defines: namespaced `cliff:` entries become
CLIFF attributes, an ordinary comment becomes `context`, and everything else
falls back to a documented default (`type: sentence`, `status` derived from
whether a translation exists). **A converter never invents context, emotion,
references, widths or reviewers that the source file did not contain.**

### Round-trip fidelity

JSON, YAML, CSV, and XLIFF preserve the whole CLIFF data model, so `cliff -> format -> cliff` is lossless. The remaining formats have no slot for some CLIFF fields:

| Format | Fidelity | Dropped on the way back |
| --- | --- | --- |
| JSON / YAML / CSV | yes | — |
| XLIFF 2.0 / 2.1 / 2.2 | yes | — (CLIFF-only fields travel as `cliff:`-categorised notes) |
| PO | entry level | header prose (`variant`, `version`, `title`, `info`, `standard`, `dependency`) and the group structure; every entry attribute survives |
| Fluent | entry level | header prose and the group structure; Fluent attributes of foreign files cannot be represented |
| Android strings.xml | entry level | header prose and the group structure |
| iOS Localizable.strings | entry level | header prose and the group structure |

Importers keep foreign identifiers that are already valid CLIFF 1.1 names —
`InvSwordIron` and `bad_id` are valid names, and rewriting one silently would
break a translation memory. Only characters outside the name set are replaced,
by the documented normalization of specification Appendix C.3, and duplicates
are disambiguated with a numeric suffix so every generated document validates.

Install optional converter dependencies with:

```bash
pip install "cliff-python[converters]"
```

## Conversion samples

For every supported format, conversion samples are self-contained in two directories:

```text
examples/cliff_to_<format>/
├── <name>.cliff      # source CLIFF
└── <name>.<ext>     # CLIFF -> format result

examples/<format>_to_cliff/
├── <name>.<ext>     # source format file
└── <name>.cliff      # format -> CLIFF result
```

Supported sample formats: `json`, `yaml`, `csv`, `po`, `xliff`, `fluent`, `android`, `ios`.

The generated side of every sample is produced by `tools/regenerate_examples.py`; run it after changing a converter, and `python tools/regenerate_examples.py --check` verifies the samples are current (CI runs this).

Run the conversion tests with:

```bash
pytest tests/test_conversion.py
```

## Repository layout

```text
cliff-python/
├── pyproject.toml
├── src/
│   └── cliff_format/
│       ├── identifiers.py   # name / tag / terminator rules (specification §5.5, §5.6, Appendix C.3)
│       ├── vocabulary.py    # the closed tag vocabularies (§12, §13)
│       ├── model.py         # dataclasses for the CLIFF data model
│       ├── parser.py        # single-pass line parser, strict and tolerant
│       ├── serializer.py    # canonical serializer
│       ├── validator.py     # semantic validation, inheritance helpers, style and layout checks
│       ├── converter.py     # bidirectional format converters
│       └── cli.py           # cliff_format command line
├── tools/
│   └── regenerate_examples.py
├── examples/
└── tests/
```

## License

MIT
