"""Unit tests for the atomic-write helper."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core import io
from ecefast.core.io import atomic_write, temporary_path

pytestmark = pytest.mark.unit


def test_temporary_path_keeps_directory_and_suffix(tmp_path: Path) -> None:
    tmp = temporary_path(tmp_path / "rstos.nc")
    assert tmp.parent == tmp_path
    assert tmp.suffix == ".nc"
    assert tmp.name.startswith("rstos.tmp-")


def test_file_present_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    with atomic_write(target) as tmp:
        assert not target.exists()
        Path(tmp).write_text("done")
    assert target.read_text() == "done"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt"]


def test_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old")
    with atomic_write(target) as tmp:
        Path(tmp).write_text("new")
    assert target.read_text() == "new"


def test_no_partial_file_on_exception(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old")
    with pytest.raises(RuntimeError, match="boom"):
        with atomic_write(target) as tmp:
            Path(tmp).write_text("half")
            raise RuntimeError("boom")
    assert target.read_text() == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt"]


def test_nothing_written_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nothing was written"):
        with atomic_write(tmp_path / "out.txt"):
            pass
    assert list(tmp_path.iterdir()) == []


def test_xarray_to_netcdf(tmp_path: Path) -> None:
    target = tmp_path / "field.nc"
    ds = xr.Dataset({"sst": (("y", "x"), np.full((2, 3), 290.0))})
    with atomic_write(target) as tmp:
        ds.to_netcdf(tmp)
    with xr.open_dataset(target) as back:
        np.testing.assert_array_equal(back["sst"].values, ds["sst"].values)


@pytest.mark.skipif(shutil.which("cdo") is None, reason="cdo not on PATH")
def test_cdo_output(tmp_path: Path) -> None:
    from ecefast.core.cdo import get_cdo

    source = tmp_path / "in.nc"
    xr.Dataset({"sst": (("lat", "lon"), np.full((2, 3), 290.0))}).to_netcdf(source)
    target = tmp_path / "out.nc"
    with atomic_write(target) as tmp:
        get_cdo().mulc(2, input=str(source), output=tmp)
    with xr.open_dataset(target) as back:
        np.testing.assert_array_equal(back["sst"].values, np.full((2, 3), 580.0))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.nc", "out.nc"]


def test_replace_directory(tmp_path: Path) -> None:
    target, source = tmp_path / "out", tmp_path / "out.partial"
    target.mkdir()
    (target / "old.txt").write_text("old")
    source.mkdir()
    (source / "new.txt").write_text("new")
    io.replace_directory(str(source), str(target))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]
    assert sorted(p.name for p in target.iterdir()) == ["new.txt"]


def test_replace_directory_without_target(tmp_path: Path) -> None:
    source = tmp_path / "out.partial"
    source.mkdir()
    io.replace_directory(str(source), str(tmp_path / "out"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]


def test_partial_path() -> None:
    assert io.partial_path("/data/out/") == "/data/out.partial"
