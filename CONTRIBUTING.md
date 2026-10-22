# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Python 3.11 or newer is required. The package has no runtime dependencies; PyYAML is only needed for the YAML converter.

## Checks

```bash
ruff check src tests
mypy
pytest
python tools/regenerate_examples.py --check
```

The test suite covers the normative CLIFF 1.0 and 1.1 examples and the `cliff-test` conformance fixtures. When the sibling `cliff` and `cliff-test` checkouts are not available, the related tests skip. Set `CLIFF_REQUIRE_SIBLINGS=1` to make a missing sibling a failure.

## Tests and fixtures

- Tests live under `tests/`.
- Conversion samples live under `examples/`; the generated side is produced by `tools/regenerate_examples.py`.
- Do not edit generated samples by hand. Change the converter and regenerate them.
- Do not remove a test or fixture merely to make a run green; fix the implementation or update the fixture from its source repository.

## Commits and pull requests

- Use English Conventional Commits: `[AI] type(scope): description`.
- Use one logical change per commit.
- Allowed types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `style`, `chore`, `build`, `ci`, `revert`.
- The `[AI]` prefix is required for AI-generated or automated commits.
- Keep commit subjects at 72 characters or fewer and do not end them with a period.
- Use English for commit messages, branch names, pull request titles, tags and `CHANGELOG.md`.
- `main` is the release branch; `dev` is the integration branch.
- Create work branches from `dev` and target `dev` with pull requests.
- Release pull requests merge `dev` into `main` with a merge commit; `main` is not linear.
- See [docs/version-control.md](docs/version-control.md).
- Run the checks above before opening a pull request.

## Release

1. Update the version in `pyproject.toml` and `src/cliff_format/__init__.py`.
2. Update the English `CHANGELOG.md`.
3. Run the checks and build the distributions.
4. Commit with `[AI] build(release): prepare vX.Y.Z`.
5. Open a release pull request from `dev` to `main` and merge it with a merge commit.
6. Tag `main` with an annotated `vX.Y.Z` tag.
7. Publish a GitHub Release; the publish workflow uploads to PyPI with trusted publishing.

## Scope

CLIFF is a working and delivery format, not a runtime localization engine. Keep converters and the command line documented, and do not silently add fields or defaults that the source format did not carry.

See the [CLIFF specification](https://github.com/cliff-format/cliff/blob/main/spec/cliff-1.1.0.md) for the format and the [conformance fixtures](https://github.com/cliff-format/cliff-test/tree/main/tests/fixtures) for the validation contract.