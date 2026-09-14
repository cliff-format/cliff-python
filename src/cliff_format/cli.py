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
from .parser import load
from .serializer import serialize
from .validator import validate

CONVERT_FORMATS = ["cliff", "json", "yaml", "csv", "po", "xliff", "fluent", "android", "ios"]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _clan_from_path(path: Path) -> str:
    """Derive a valid CLIFF clan name from the source file name."""
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
        if issue.category not in ("warning", "extension"):
            errors += 1
    return 1 if errors else 0


def _cmd_parse(args: argparse.Namespace) -> int:
    doc = load(args.path)
    print(to_json(doc))
    return 0


def _cmd_serialize(args: argparse.Namespace) -> int:
    doc = load(args.path)
    sys.stdout.write(serialize(doc))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    text = _read_text(path)
    issues = validate(text, path=path, check_width=args.check_width)
    return _print_issues(issues, path)


def _cmd_convert(args: argparse.Namespace) -> int:
    path = Path(args.path)
    input_format = args.input_format or "cliff"
    output_format = args.output_format or "json"
    clan = _clan_from_path(path)

    if input_format == "cliff":
        doc = load(path)
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
        output = serialize(doc)
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
        description="CLIFF 1.0 Python parser, serializer, validator and converter",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="parse a .cliff file and print JSON")
    p.add_argument("path", type=Path)
    p.set_defaults(func=_cmd_parse)

    p = sub.add_parser("serialize", help="parse and print canonical CLIFF")
    p.add_argument("path", type=Path)
    p.set_defaults(func=_cmd_serialize)

    p = sub.add_parser("validate", help="validate a .cliff file")
    p.add_argument("path", type=Path)
    p.add_argument("--check-width", action="store_true")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("convert", help="convert between CLIFF and common formats")
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
