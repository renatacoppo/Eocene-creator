"""Unit tests for the checks of a finished Eocene run (``paleo/eocene/verify.py``)."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core.steps import ComponentStep, PipelineError
from ecefast.core.workspace import Context
from ecefast.paleo.eocene.nemo.domain import EoceneDomain
from ecefast.paleo.eocene.verify import missing_outputs, nan_variables, verify
from synthetic import make_config

pytestmark = pytest.mark.unit


class Writer(ComponentStep):
    """Declares one NetCDF file and one directory."""

    name = "writer"
    writes = ["{eocene.output_dir}/a/field.nc", "{eocene.output_dir}/b"]


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    return Context(make_config(tmp_path))


def write_outputs(ctx: Context, field: np.ndarray | None = None) -> Path:
    """The outputs of ``Writer``; ``field`` is the data of ``field.nc``."""
    out = Path(ctx.config.eocene.output_dir)
    (out / "b").mkdir(parents=True)
    (out / "a").mkdir()
    field = np.ones((2, 3)) if field is None else field
    xr.Dataset({"t": (("y", "x"), field), "n": (("y", "x"), np.zeros((2, 3), "int32"))}).to_netcdf(out / "a/field.nc")
    return out / "a/field.nc"


def vertical_grid(nav_lev: np.ndarray) -> xr.Dataset:
    return xr.Dataset({"nav_lev": ("z", nav_lev), "e3t_1d": (("time_counter", "z"), np.diff(nav_lev, prepend=0)[None])})


# --- missing_outputs -----------------------------------------------------------------------------------------------


def test_missing_outputs_none(ctx: Context) -> None:
    write_outputs(ctx)
    assert missing_outputs([Writer], ctx) == []


def test_missing_outputs_lists_files_and_directories(ctx: Context) -> None:
    out = Path(ctx.config.eocene.output_dir)
    assert missing_outputs([Writer], ctx) == [str(out / "a/field.nc"), str(out / "b")]


# --- nan_variables -------------------------------------------------------------------------------------------------


def test_nan_variables_none(tmp_path: Path) -> None:
    xr.Dataset({"t": ("x", [1.0, 2.0])}).to_netcdf(tmp_path / "f.nc")
    assert nan_variables(str(tmp_path / "f.nc")) == []


def test_nan_variables_finds_nan(tmp_path: Path) -> None:
    xr.Dataset({"ok": ("x", [1.0, 2.0]), "bad": ("x", [1.0, np.nan])}).to_netcdf(tmp_path / "f.nc")
    assert nan_variables(str(tmp_path / "f.nc")) == ["bad"]


def test_nan_variables_fill_value_is_not_nan(tmp_path: Path) -> None:
    """A masked point stored as a non-NaN ``_FillValue`` is fine (it would decode to NaN by default)."""
    ds = xr.Dataset({"t": ("x", [1.0, np.nan])})
    ds.to_netcdf(tmp_path / "f.nc", encoding={"t": {"_FillValue": -999.0}})
    assert nan_variables(str(tmp_path / "f.nc")) == []


def test_nan_variables_nan_fill_value_still_fails(tmp_path: Path) -> None:
    """EC-Earth reads raw values: a NaN is an error even when ``_FillValue`` is NaN."""
    ds = xr.Dataset({"t": ("x", [1.0, np.nan])})
    ds.to_netcdf(tmp_path / "f.nc", encoding={"t": {"_FillValue": np.nan}})
    assert nan_variables(str(tmp_path / "f.nc")) == ["t"]


# --- verify --------------------------------------------------------------------------------------------------------


def test_verify_passes(ctx: Context) -> None:
    write_outputs(ctx)
    verify([Writer], ctx)


def test_verify_missing_output(ctx: Context) -> None:
    with pytest.raises(PipelineError, match=r"missing output .*/a/field\.nc\n  missing output .*/b"):
        verify([Writer], ctx)


def test_verify_nan(ctx: Context) -> None:
    path = write_outputs(ctx, field=np.array([[1.0, np.nan, 1.0], [1.0, 1.0, 1.0]]))
    with pytest.raises(PipelineError, match=f"NaN in t of {path}"):
        verify([Writer], ctx)


def write_domains(ctx: Context, eocene_nav_lev: np.ndarray) -> None:
    """Present-day domain in the input tree and the installed Eocene domain, as the ``domain`` step leaves them."""
    present = Path(ctx.expand(EoceneDomain.reads[0]))
    present.parent.mkdir(parents=True)
    vertical_grid(np.arange(1.0, 32.0)).to_netcdf(present)
    for template in EoceneDomain.writes:
        Path(ctx.expand(template)).parent.mkdir(parents=True, exist_ok=True)
        vertical_grid(eocene_nav_lev).to_netcdf(ctx.expand(template))


def test_verify_vertical_grid_passes(ctx: Context) -> None:
    write_domains(ctx, np.arange(1.0, 32.0))
    verify([EoceneDomain], ctx)


def test_verify_vertical_grid_fails(ctx: Context) -> None:
    write_domains(ctx, np.arange(1.0, 76.0))
    with pytest.raises(PipelineError, match="does not have the same vertical grid") as err:
        verify([EoceneDomain], ctx)
    assert "31 levels" in str(err.value) and "75 levels" in str(err.value)


def test_verify_vertical_grid_only_after_domain(ctx: Context) -> None:
    """Without the ``domain`` step the domains are not compared (here they would differ)."""
    write_domains(ctx, np.arange(1.0, 76.0))
    write_outputs(ctx)
    verify([Writer], ctx)
