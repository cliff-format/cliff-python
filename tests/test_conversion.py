from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT

from cliff_format import from_json, load, serialize, to_json

SAMPLE_DIR = REPO_ROOT / "examples" / "cliff_to_json"


def _sample_files() -> list[Path]:
    return sorted(SAMPLE_DIR.glob("*.cliff")) if SAMPLE_DIR.is_dir() else []


@pytest.mark.parametrize("cliff_path", _sample_files(), ids=lambda p: p.name)
def test_cliff_to_json_and_back(cliff_path: Path) -> None:
    """A CLIFF document survives a JSON round-trip with its data intact."""
    document = load(cliff_path)
    json_text = to_json(document, indent=2, ensure_ascii=False)
    roundtrip = from_json(json_text)

    assert roundtrip.header.namespace == document.header.namespace
    assert roundtrip.header.clan == document.header.clan
    assert roundtrip.header.source_language == document.header.source_language
    assert roundtrip.header.target_language == document.header.target_language
    assert len(roundtrip.groups) == len(document.groups)
    assert len(roundtrip.entries()) == len(document.entries())

    for (src_group, src_entry), (dst_group, dst_entry) in zip(
        document.entries(), roundtrip.entries(), strict=True
    ):
        assert dst_group.path == src_group.path
        assert dst_entry.id == src_entry.id
        assert dst_entry.source == src_entry.source
        assert dst_entry.target == src_entry.target
        assert dst_entry.status == src_entry.status

    # The regenerated CLIFF must itself be parseable and stable.
    once = serialize(roundtrip)
    assert serialize(from_json(to_json(roundtrip))) == once


def test_examples_are_up_to_date() -> None:
    """examples/ must match what the current converters produce."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from regenerate_examples import regenerate

    stale = regenerate(check=True)
    assert stale == [], [str(path.relative_to(REPO_ROOT)) for path in stale]
