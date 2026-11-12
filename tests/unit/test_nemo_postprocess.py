"""Tests for the NEMO domain post-processing: ``process_domain_cfg`` and ``extract_maskutil``.

The raw DOMAINcfg outputs (``domain_cfg_<name>.nc``, ``mesh_mask_<name>.nc``) exist only on Atos, so
the unit tests write tiny synthetic files with the same structure. The ``local_data`` test rebuilds
raw files from the real post-processed domains (``data/domain/PALEORCA2/<name>/`` under
``ECEFAST_TEST_DATA``), runs the post-processing on them and checks that the result matches the
real files.
"""

import os
from pathlib import Path

import netCDF4
import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.common.util import extract_maskutil, process_domain_cfg

DATA = os.environ.get("ECEFAST_TEST_DATA")
NAME = "test"
NY, NX, NZ = 3, 4, 2
NO_FILL = {"_FillValue": None}


def write_raw_domain_cfg(path: Path) -> None:
    """A tiny ``domain_cfg_<name>.nc`` as DOMAINcfg writes it: ``nav_lev`` is the vertical dimension."""
    rng = np.random.default_rng(0)
    t2d = ("time_counter", "y", "x")
    ds = xr.Dataset(
        {
            "nav_lon": (("y", "x"), rng.random((NY, NX), dtype="float32")),
            "nav_lat": (("y", "x"), rng.random((NY, NX), dtype="float32")),
            "jpiglo": ((), np.int32(NX)),
            "jpkglo": ((), np.int32(NZ)),
            "glamt": (t2d, rng.random((1, NY, NX))),
            "e3t_1d": (("time_counter", "nav_lev"), rng.random((1, NZ))),
            "e3t_0": (("time_counter", "nav_lev", "y", "x"), rng.random((1, NZ, NY, NX))),
            "bottom_level": (t2d, rng.integers(0, NZ + 1, (1, NY, NX), dtype="int32")),
            "bathy_metry": (t2d, rng.random((1, NY, NX))),
        },
        coords={
            "nav_lev": ("nav_lev", np.array([5.0, 15.0], dtype="float32")),
            "time_counter": ("time_counter", np.array([0.0], dtype="float32")),
        },
        attrs={"DOMAIN_number_total": 1, "DOMAIN_type": "BOX"},
    )
    ds.to_netcdf(path, encoding={v: NO_FILL for v in ds.variables}, unlimited_dims=["time_counter"])


def write_raw_mesh_mask(path: Path) -> None:
    """A tiny ``mesh_mask_<name>.nc``: the three ``*maskutil`` variables plus others that must be dropped."""
    rng = np.random.default_rng(1)
    t2d = ("time_counter", "y", "x")
    masks = {f"{p}maskutil": (t2d, rng.integers(0, 2, (1, NY, NX), dtype="int8")) for p in "tuv"}
    ds = xr.Dataset(
        {
            "tmask": (("time_counter", "nav_lev", "y", "x"), rng.integers(0, 2, (1, NZ, NY, NX), dtype="int8")),
            **masks,
            "fmaskutil": (t2d, rng.integers(0, 2, (1, NY, NX), dtype="int8")),
            "glamt": (t2d, rng.random((1, NY, NX))),
        },
        coords={
            "nav_lev": ("nav_lev", np.array([5.0, 15.0], dtype="float32")),
            "time_counter": ("time_counter", np.array([0.0], dtype="float32")),
        },
        attrs={"DOMAIN_number_total": 1, "DOMAIN_type": "BOX"},
    )
    ds.to_netcdf(path, encoding={v: NO_FILL for v in ds.variables}, unlimited_dims=["time_counter"])


def header(path: Path) -> dict:
    """Structure of a NetCDF file: dimensions (size, unlimited), variables (dims, dtype, attributes), globals."""
    with netCDF4.Dataset(path) as nc:
        return {
            "dims": {n: (len(d), d.isunlimited()) for n, d in nc.dimensions.items()},
            "vars": {n: (v.dimensions, v.dtype, v.ncattrs()) for n, v in nc.variables.items()},
            "globals": {a: np.asarray(nc.getncattr(a)).tolist() for a in nc.ncattrs()},
        }


@pytest.mark.unit
def test_process_domain_cfg(tmp_path: Path) -> None:
    write_raw_domain_cfg(tmp_path / f"domain_cfg_{NAME}.nc")
    tgt = tmp_path / "out" / "present_day"

    process_domain_cfg(str(tmp_path), str(tgt), NAME)

    out = header(tgt / "domain_cfg.nc")
    assert out["dims"] == {"time_counter": (1, True), "y": (NY, False), "x": (NX, False), "z": (NZ, False)}
    # same variables and order as the input; nav_lev becomes a plain variable on z, after the data variables
    expected = ["nav_lon", "nav_lat", "jpiglo", "jpkglo", "glamt", "e3t_1d", "e3t_0", "bottom_level", "bathy_metry"]
    assert list(out["vars"]) == expected + ["nav_lev", "time_counter"]
    assert out["vars"]["nav_lev"][:2] == (("z",), np.dtype("float32"))
    assert out["vars"]["e3t_0"][:2] == (("time_counter", "z", "y", "x"), np.dtype("float64"))
    assert out["vars"]["bottom_level"][1] == np.dtype("int32")
    # no _FillValue (nor any other attribute) on any variable
    assert all(attrs == [] for _, _, attrs in out["vars"].values())
    assert out["globals"] == {"DOMAIN_number_total": 1, "DOMAIN_type": "BOX", "cn_cfg": "PALEORCA", "nn_cfg": 2}

    raw = xr.open_dataset(tmp_path / f"domain_cfg_{NAME}.nc")
    with xr.open_dataset(tgt / "domain_cfg.nc") as ds:
        assert "nav_lev" not in ds.coords
        np.testing.assert_array_equal(ds["nav_lev"].values, raw["nav_lev"].values)
        np.testing.assert_array_equal(ds["e3t_0"].values, raw["e3t_0"].values)
    raw.close()


@pytest.mark.unit
def test_extract_maskutil(tmp_path: Path) -> None:
    write_raw_mesh_mask(tmp_path / f"mesh_mask_{NAME}.nc")
    tgt = tmp_path / "out" / "present_day"

    extract_maskutil(str(tmp_path), str(tgt), NAME)

    out = header(tgt / "maskutil.nc")
    assert out["dims"] == {"t": (1, True), "y": (NY, False), "x": (NX, False)}
    assert out["vars"] == {f"{p}maskutil": (("t", "y", "x"), np.dtype("int8"), []) for p in "tuv"}
    assert list(out["vars"]) == ["tmaskutil", "umaskutil", "vmaskutil"]
    assert out["globals"] == {"Conventions": "CF-1.1"}

    with xr.open_dataset(tmp_path / f"mesh_mask_{NAME}.nc") as raw, xr.open_dataset(tgt / "maskutil.nc") as ds:
        for var in ["tmaskutil", "umaskutil", "vmaskutil"]:
            np.testing.assert_array_equal(ds[var].values, raw[var].values)
    # the raw mesh_mask is not copied to the target directory
    assert sorted(p.name for p in tgt.iterdir()) == ["maskutil.nc"]


@pytest.mark.local_data
@pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set")
@pytest.mark.parametrize("domain", ["present_day", "eocene"])
def test_postprocess_matches_real_domain(tmp_path: Path, domain: str) -> None:
    """Rebuild raw DOMAINcfg files from the real post-processed ones, post-process them, compare."""
    real = Path(DATA) / "data" / "domain" / "PALEORCA2" / domain
    src = tmp_path / "DOMAINcfg"
    src.mkdir()

    # domain_cfg: undo the post-processing (z -> nav_lev as index coordinate, drop the PALEORCA attributes)
    with xr.open_dataset(real / "domain_cfg.nc") as ds:
        raw = ds.swap_dims({"z": "nav_lev"})
        raw.attrs = {k: v for k, v in ds.attrs.items() if k not in ("cn_cfg", "nn_cfg")}
        raw.to_netcdf(
            src / f"domain_cfg_{domain}.nc",
            encoding={v: NO_FILL for v in raw.variables},
            unlimited_dims=["time_counter"],
        )
    # mesh_mask: t -> time_counter with its coordinate, plus a mask that must be dropped
    with xr.open_dataset(real / "maskutil.nc") as ds:
        raw = ds.rename_dims({"t": "time_counter"}).assign_coords(time_counter=np.array([0.0], dtype="float32"))
        raw["fmaskutil"] = raw["tmaskutil"]
        raw.attrs = {"DOMAIN_type": "BOX"}
        raw.to_netcdf(src / f"mesh_mask_{domain}.nc", unlimited_dims=["time_counter"])

    tgt = tmp_path / "out"
    process_domain_cfg(str(src), str(tgt), domain)
    extract_maskutil(str(src), str(tgt), domain)

    for name in ["domain_cfg.nc", "maskutil.nc"]:
        expected, got = header(real / name), header(tgt / name)
        assert got["dims"] == expected["dims"], name
        assert list(got["vars"]) == list(expected["vars"]), name
        assert got["vars"] == expected["vars"], name
        assert got["globals"] == expected["globals"], name
        with xr.open_dataset(real / name) as a, xr.open_dataset(tgt / name) as b:
            xr.testing.assert_identical(a, b)
