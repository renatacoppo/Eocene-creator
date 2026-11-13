"""Unit tests for the OIFS initial-state processes that need no CDO (``ecefast.components.oifs.initial_state``)."""

from pathlib import Path

import pytest

from ecefast.components.oifs.initial_state import IC_FILES, install_initial_state

pytestmark = pytest.mark.unit


def test_install_initial_state_moves_the_files(tmp_path: Path) -> None:
    work, target = tmp_path / "work", tmp_path / "target"
    work.mkdir()
    target.mkdir()
    for name in IC_FILES:
        (work / name).write_text(name)
    install_initial_state(str(work), str(target))
    assert list(work.iterdir()) == []
    assert sorted(p.name for p in target.iterdir()) == sorted(IC_FILES)
    for name in IC_FILES:
        assert (target / name).read_text() == name
