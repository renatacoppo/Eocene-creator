"""Unit tests of the provenance of a tree (``ecefast.core.provenance``)."""

from pathlib import Path

import pytest

from ecefast.core.provenance import PROVENANCE_FILE, read_data_version

pytestmark = pytest.mark.unit


def test_read_data_version(tmp_path: Path):
    (tmp_path / PROVENANCE_FILE).write_text("steps: [stage]\ndata_version: v1\n")
    assert read_data_version(tmp_path) == "v1"


@pytest.mark.parametrize("content", [None, "", "steps: [stage]\n"], ids=["no-file", "empty", "no-key"])
def test_read_data_version_of_a_tree_without_one(tmp_path: Path, content: str | None):
    if content is not None:
        (tmp_path / PROVENANCE_FILE).write_text(content)
    assert read_data_version(tmp_path) is None
