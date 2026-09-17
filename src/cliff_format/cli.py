from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .converter import (
    XLIFF_VERSIONS,
    from_android_strings,
    from_csv,
    from_fluent,
    from_ios_strings,
    from_json,
    from_po,
    from_xliff,
    from_yaml,
    to_android_strings,
    to_csv,
    to_fluent,
    to_ios_strings,
    to_json,
    to_po,
    to_xliff,
    to_yaml,
)
from .errors import CliffParseError
from .model import ValidationIssue
from .parser import SUPPORTED_VERSIONS, load
from .serializer import serialize
from .validator import ADVISORY_CATEGORIES, validate

CONVERT_FORMATS = ["cliff", "json", "yaml", "csv", "po", "xliff", "fluent", "android", "ios"]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _clan_from_path(path: Path) -> str:
    """Derive a CLIFF clan name from the source file name.

    The name is folded to kebab-case so the generated document also conforms to
    the recommended style of ``style/README.md``; CLIFF 1.1 itself would accept
    the original capitalization, but a generated document is the one place a
    tool legitimately chooses the style.
    """
    stem = path.stem
    first = stem.split(".")[0]
    clan = re.sub(r"[^a-z0-9-]+", "-", first.lower()).strip("-")
    return clan or "imported"


def _format_issue(path: Path, line: int, category: str, message: str, text: str) -> str:
    """One diagnostic line (plus the offending source line when known).

    Every CLIFF diagnostic carries a line number, a category and the offending
    line so that a human or an agent can make a single corrective edit.
    """
    location = f"{path}:{line}" if line else str(path)
    rendered = f"{location}: [{category.upper()}] {message}"
    return f"{rendered}\n    | {text}" if text else rendered


def _print_issues(issues: list[ValidationIssue], path: Path) -> int:
    errors = 0
    for issue in issues:
        print(_format_issue(path, issue.line, issue.category, issue.message, issue.text))
        if issue.category not in ADVISORY_CATEGORIES:
            errors += 1
    return 1 if errors else 0


def _cmd_parse(args: argparse.Namespace) -> int:
    doc = load(args.path, tolerant=args.tolerant)
    if args.tolerant:
        for correction in doc.corrections:
            print(
                _format_issue(
                    args.path,
                    correction.line,
                    correction.category,
                    correction.detail(),
                    "",
                ),
                file=sys.stderr,
            )
    print(to_json(doc))
    return 0


def _cmd_serialize(args: argparse.Namespace) -> int:
    doc = load(args.path, tolerant=args.tolerant)
    if args.spec_version:
        doc.spec_version = args.spec_version
    for correction in doc.corrections:
        print(
            _format_issue(
                args.path, correction.line, correction.category, correction.detail(), ""
            ),
            file=sys.stderr,
        )
    sys.stdout.write(serialize(doc, style=args.style))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    text = _read_text(path)
    issues = validate(
        text,
        path=path,
        check_width=args.check_width,
        check_layout=args.check_layout,
        style=args.style,
        tolerant=args.tolerant,
    )
    return _print_issues(issues, path)


def _cmd_convert(args: argparse.Namespace) -> int:
    path = Path(args.path)
    input_format = args.input_format or "cliff"
    output_format = args.output_format or "json"
    clan = _clan_from_path(path)

    if input_format == "cliff":
        # The tolerant mode exists exactly for this: an AI translation pipeline
        # that must not lose a translation to a formatting slip.
        doc = load(path, tolerant=args.tolerant)
        for correction in doc.corrections:
            print(
                _format_issue(
                    path, correction.line, correction.category, correction.detail(), ""
                ),
                file=sys.stderr,
            )
    else:
        text = _read_text(path)
        if input_format == "json":
            doc = from_json(text)
        elif input_format == "yaml":
            doc = from_yaml(text)
        elif input_format == "csv":
            doc = from_csv(text, clan=clan)
        elif input_format == "po":
            doc = from_po(text, clan=clan)
        elif input_format == "xliff":
            doc = from_xliff(text, clan=clan)
        elif input_format == "fluent":
            doc = from_fluent(text, clan=clan)
        elif input_format == "android":
            doc = from_android_strings(text, clan=clan)
        elif input_format == "ios":
            doc = from_ios_strings(text, clan=clan)
        else:  # pragma: no cover - argparse restricts choices
            raise ValueError(f"unsupported input format: {input_format}")

    if output_format == "cliff":
        output = serialize(doc, style=args.style)
    elif output_format == "json":
        output = to_json(doc)
    elif output_format == "yaml":
        output = to_yaml(doc)
    elif output_format == "csv":
        output = to_csv(doc)
    elif output_format == "po":
        output = to_po(doc)
    elif output_format == "xliff":
        output = to_xliff(doc, version=args.xliff_version)
    elif output_format == "fluent":
        output = to_fluent(doc)
    elif output_format == "android":
        output = to_android_strings(doc)
    elif output_format == "ios":
        output = to_ios_strings(doc)
    else:  # pragma: no cover - argparse restricts choices
        raise ValueError(f"unsupported output format: {output_format}")

    if not output.endswith("\n"):
        output += "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cliff_format",
        description="CLIFF 1.0 / 1.1 Python parser, serializer, validator and converter",
        epilog=(
            "Strict parsing is the default: anything the specification rejects is an "
            "error. --tolerant applies the documented relaxations of CLIFF 1.1 "
            "Appendix C and reports every repair; it never guesses missing data. "
            "A style deviation is never an error — use --style to see it."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "parse",
        help="parse a .cliff file and print JSON",
        description="Parse a .cliff file and print the data model as JSON.",
    )
    p.add_argument("path", type=Path)
    p.add_argument(
        "--tolerant",
        action="store_true",
        help="apply the Appendix C relaxations and report every repair on stderr",
    )
    p.set_defaults(func=_cmd_parse)

    p = sub.add_parser(
        "serialize",
        help="parse and print canonical CLIFF",
        description="Parse a .cliff file and print canonical CLIFF 1.1.",
    )
    p.add_argument("path", type=Path)
    p.add_argument(
        "--tolerant",
        action="store_true",
        help="apply the Appendix C relaxations before serializing",
    )
    p.add_argument(
        "--spec-version",
        choices=list(SUPPORTED_VERSIONS),
        default=None,
        help=(
            "version line to emit (default: the version the document declared, "
            "or 1.1 for a newly built document)"
        ),
    )
    p.add_argument(
        "--style",
        action="store_true",
        help="also normalize identifiers to the recommended shape of style/README.md",
    )
    p.set_defaults(func=_cmd_serialize)

    p = sub.add_parser(
        "validate",
        help="validate a .cliff file",
        description=(
            "Validate a .cliff file. Layout mismatches are warnings by default "
            "because CLIFF 1.1 recommends a layout rather than requiring it."
        ),
    )
    p.add_argument("path", type=Path)
    p.add_argument("--check-width", action="store_true", help="report max-width overflow")
    p.add_argument(
        "--check-layout",
        action="store_true",
        help="report a file-layout/header mismatch as an error instead of a warning",
    )
    p.add_argument(
        "--style",
        action="store_true",
        help="report style/README.md deviations as warnings",
    )
    p.add_argument(
        "--tolerant",
        action="store_true",
        help="repair the Appendix C deviations and report each repair",
    )
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser(
        "convert",
        help="convert between CLIFF and common formats",
        description="Convert between CLIFF and common localization formats.",
    )
    p.add_argument("path", type=Path)
    p.add_argument(
        "--from",
        dest="input_format",
        choices=CONVERT_FORMATS,
        default="cliff",
        help="input format (default: cliff)",
    )
    p.add_argument(
        "-f",
        "--format",
        dest="output_format",
        choices=CONVERT_FORMATS,
        default="json",
        help="output format (default: json)",
    )
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument(
        "--tolerant",
        action="store_true",
        help="apply the Appendix C relaxations when reading CLIFF input",
    )
    p.add_argument(
        "--style",
        action="store_true",
        help="normalize identifiers when the output format is CLIFF",
    )
    p.add_argument(
        "--xliff-version",
        choices=list(XLIFF_VERSIONS),
        default="2.1",
        help=(
            "XLIFF version to emit (default: 2.1). Version 2.2 additionally "
            "writes the glossary module for a variant: glossary document."
        ),
    )
    p.set_defaults(func=_cmd_convert)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliffParseError as exc:
        path = getattr(args, "path", Path("<input>"))
        print(
            _format_issue(path, exc.line, exc.category, exc.message, exc.text),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should report the error cleanly
        print(f"cliff_format: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
