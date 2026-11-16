"""Tests for ``ecefast.components.nemo.sections``: the coordinates file of SECTIONS_DIADCT and the reader of
``section_ijglobal.diadct``, on synthetic data (a small grid, and a sections file written record by record as the
Fortran tool does)."""

import struct
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.sections import COORDINATE_VARIABLES, read_sections, write_sections_coordinates

pytestmark = pytest.mark.unit

NY, NX = 4, 6


def write_domain_cfg(path: Path, variables=COORDINATE_VARIABLES) -> dict[str, np.ndarray]:
    """A domain_cfg.nc with the horizontal grid as (time_counter, y, x), y defined before x as DOMAINcfg does."""
    rng = np.random.default_rng(0)
    fields = {name: rng.random((NY, NX)) for name in variables}
    ds = xr.Dataset({name: (("time_counter", "y", "x"), values[None]) for name, values in fields.items()})
    ds["bottom_level"] = (("time_counter", "y", "x"), np.ones((1, NY, NX), dtype="int32"))
    ds.to_netcdf(path)
    return fields


def test_coordinates_x_first(tmp_path: Path) -> None:
    """jpi, jpj of the tool are the first two dimensions of the file: x must be defined before y."""
    fields = write_domain_cfg(tmp_path / "domain_cfg.nc")
    with netCDF4.Dataset(tmp_path / "domain_cfg.nc") as nc:
        assert list(nc.dimensions)[1:] == ["y", "x"]
    write_sections_coordinates(tmp_path / "domain_cfg.nc", tmp_path / "coordinates.nc")
    with netCDF4.Dataset(tmp_path / "coordinates.nc") as nc:
        assert list(nc.dimensions) == ["x", "y"]
        assert (len(nc.dimensions["x"]), len(nc.dimensions["y"])) == (NX, NY)
        assert list(nc.variables) == list(COORDINATE_VARIABLES)
        for name, values in fields.items():
            assert nc[name].dimensions == ("y", "x") and nc[name].dtype == np.float64
            np.testing.assert_array_equal(nc[name][:], values)


def test_coordinates_missing_variable(tmp_path: Path) -> None:
    write_domain_cfg(tmp_path / "domain_cfg.nc", variables=("glamt", "gphit"))
    with pytest.raises(KeyError, match="glamf, gphif, e1t"):
        write_sections_coordinates(tmp_path / "domain_cfg.nc", tmp_path / "coordinates.nc")
    assert not (tmp_path / "coordinates.nc").exists()


def record(payload: bytes) -> bytes:
    """One Fortran unformatted sequential record (gfortran/ifort default 4-byte markers)."""
    marker = struct.pack("<i", len(payload))
    return marker + payload + marker


def section_records(number: int, name: str, coordinates, points, directions) -> bytes:
    """A section in the order of writesections.f90."""
    classes = np.full(10, 99.0).tobytes()  # zsigi, zsigp, zsal, ztem, zlay: nb_class_max = 10 REAL(8)
    out = record(struct.pack("<i", number)) + record(name.ljust(60).encode())
    out += b"".join(record(struct.pack("<i", flag)) for flag in (1, 0, 0))  # llstrpond, ice, date line
    out += record(struct.pack("<4d", *coordinates)) + record(struct.pack("<i", 0))  # coordSec, nb_class
    out += b"".join(record(classes) for _ in range(5)) + record(struct.pack("<d", -2.5))  # classes, slope
    out += record(struct.pack("<i", len(points)))
    out += b"".join(record(struct.pack("<2i", *point)) for point in points)
    if points:
        out += record(struct.pack(f"<{len(directions)}i", *directions))
    return out


def test_read_sections(tmp_path: Path) -> None:
    path = tmp_path / "section_ijglobal.diadct"
    path.write_bytes(
        section_records(1, "ACC_Drake_Passage", (-68.0, -54.5, -60.0, -64.7), [(3, 5), (3, 4)], [2, 1])
        + section_records(2, "ARC_Kara_Gate", (57.0, 70.7, 59.0, 70.2), [], [])
    )
    first, second = read_sections(path)
    assert first == {
        "number": 1,
        "name": "ACC_Drake_Passage",
        "coordinates": (-68.0, -54.5, -60.0, -64.7),
        "points": [(3, 5), (3, 4)],
        "directions": [2, 1],
    }
    assert (second["name"], second["points"], second["directions"]) == ("ARC_Kara_Gate", [], [])


def test_read_empty_file(tmp_path: Path) -> None:
    (tmp_path / "empty.diadct").write_bytes(b"")
    assert read_sections(tmp_path / "empty.diadct") == []
