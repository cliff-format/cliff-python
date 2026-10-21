# Changelog

All notable changes to `cliff-python` are recorded here. Each version lists the features that
changed behaviour, the packaging and documentation work around them, and the notes that matter
to people building against the library.

## 0.2.0 — 2026-10-21

First public release.

### New Features

- Added a strict CLIFF 1.1 parser that rejects exactly what the grammar rejects: identifiers are
  case-sensitive and never rewritten, tags stay in their closed vocabularies, and resource limits
  are enforced.
- Added tolerant parsing with the seven relaxations of specification Appendix C, and a per-repair
  report covering list shape, repeated fields, quoted tags, quoted ids, quoted keys, identifier
  normalization, collisions and version spelling.
- Added a canonical serializer that preserves the version line the document declared and is a
  fixed point under parse/serialize.
- Added validation for required fields, closed vocabularies, status rules, duplicate ids, ICU
  brace balance, file layout, display width and style.
- Added bidirectional converters for JSON, YAML, CSV, gettext PO, XLIFF 2.0/2.1/2.2 (including
  the 2.2 glossary module), Fluent, Android `strings.xml` and iOS `Localizable.strings`.
- Added the `cliff-format` command line with `parse`, `serialize`, `validate` and `convert`
  subcommands.
- Added opt-in validation checks: `--check-layout` turns a layout mismatch into an error,
  `--style` reports style-guide deviations, `--check-width` reports display-width overflow.
- Added configurable resource limits (`max_lines`, `max_line_length`, `max_string_length`) so
  an oversized document fails with a located error instead of exhausting memory.

### Other Changes

- Added type annotations across the public API and shipped `py.typed`, verified with mypy.
- Added a PyPI release workflow based on Trusted Publishing, so publishing needs no long-lived
  API token.
- Added conversion samples for every supported format, with
  `tools/regenerate_examples.py --check` to keep them current.
- Rewrote the README around the CLIFF wordmark, the install path and the converter metadata
  channels.
- Renamed the console script to `cliff-format`, matching the documented commands and avoiding a
  collision with the OpenStack `cliff` package.

### For developers

- Python 3.11 or newer is required; 3.11, 3.12 and 3.13 are supported.
- The core package has no runtime dependencies; PyYAML is only needed for the converters extra.
- Build with `python -m build` and verify metadata with
  `python -m twine check --strict dist/*`.
- Run the test suite with `pytest`, and the example check with
  `python tools/regenerate_examples.py --check`.

---

## 0.1.0 — 2026-09-03 (unreleased)

Initial implementation, developed as `pyclif` and never published to PyPI.

### Added

- Added the reference parser, serializer and validator for CLIFF 1.0.
- Added bidirectional converters for JSON, YAML, CSV, gettext PO, XLIFF, Fluent, Android
  `strings.xml` and iOS `Localizable.strings`, each shipping conversion samples in both
  directions.
- Added the command line entry point, the API overview and the metadata channel documentation.

### Notes

- The distribution and import names (`pyclif`) changed before the first release; 0.2.0 is the
  first version published under `cliff-python` / `cliff_format`.
- Tolerant parsing, resource limits and CLIFF 1.1 support arrived in 0.2.0.
