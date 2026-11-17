"""Unit tests for the grid files shipped in ``components/oifs/grids/`` (``ecefast.components.oifs.grid_files``)."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ecefast.components.oifs import grid_files
from ecefast.components.oifs.grid_files import (
    GRID_DESCRIPTIONS,
    GRIDS_DIR,
    HYBRID_LEVELS,
    grid_description,
    hybrid_coefficients,
    write_grid_descriptions,
    write_hybrid_coefficients,
)

pytestmark = pytest.mark.unit


def test_shipped_files_exist() -> None:
    for grid in GRID_DESCRIPTIONS:
        assert grid_description(grid).is_file()
    for levels in HYBRID_LEVELS:
        assert hybrid_coefficients(levels).is_file()
        assert (GRIDS_DIR / f"L{levels}.csv").is_file()
    assert grid_description("TL63") == GRIDS_DIR / "TL63.txt"
    assert hybrid_coefficients("31") == GRIDS_DIR / "L31.txt"


def test_write_hybrid_coefficients_reproduces_shipped_files(tmp_path: Path) -> None:
    written = write_hybrid_coefficients(tmp_path)
    assert written == [tmp_path / f"L{n}.txt" for n in HYBRID_LEVELS]
    for path in written:
        assert path.read_bytes() == (GRIDS_DIR / path.name).read_bytes()


def test_write_hybrid_coefficients_format(tmp_path: Path) -> None:
    (tmp_path / "L2.csv").write_text("n,a [Pa],b,ph [hPa]\n0,0.0,0.0,0\n1,500.5,0.25,1\n2,0.0,1.0,2\n")
    (path,) = write_hybrid_coefficients(tmp_path, levels=[2], csv_dir=tmp_path)
    lines = path.read_text().splitlines()
    assert lines == [
        "0\t0.00000000000000000\t0.00000000000000000",
        "1\t500.50000000000000000\t0.25000000000000000",
        "2\t0.00000000000000000\t1.00000000000000000",
    ]


def test_write_hybrid_coefficients_rejects_table_without_level_zero(tmp_path: Path) -> None:
    # as the shipped L19.csv, which starts at n=1
    (tmp_path / "L2.csv").write_text("n,a [Pa],b\n1,500.0,0.25\n2,0.0,1.0\n")
    with pytest.raises(ValueError, match=r"L2.csv: column 'n' must hold the half levels 0 \.\.\. 2"):
        write_hybrid_coefficients(tmp_path, levels=[2], csv_dir=tmp_path)
    assert not (tmp_path / "L2.txt").exists()
    with pytest.raises(ValueError, match="L19.csv"):
        write_hybrid_coefficients(tmp_path, levels=[19])


def test_write_grid_descriptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(command: list[str], stdout, check: bool) -> None:
        calls.append(command)
        stdout.write(f"gridtype  = gaussian_reduced\n# {command[-1]}\n")

    monkeypatch.setattr(grid_files, "get_cdo", lambda: SimpleNamespace(CDO="/bin/cdo"))
    monkeypatch.setattr(subprocess, "run", fake_run)
    written = write_grid_descriptions("/climate", tmp_path, grids=["TL63", "tco199"])
    assert written == [tmp_path / "TL63.txt", tmp_path / "TCO199.txt"]
    assert calls == [
        ["/bin/cdo", "griddes", "/climate/63l_2/10_bats_glcc.grb"],
        ["/bin/cdo", "griddes", "/climate/199_4/10_bats_glcc.grb"],
    ]
    assert written[0].read_text() == "gridtype  = gaussian_reduced\n# /climate/63l_2/10_bats_glcc.grb\n"
