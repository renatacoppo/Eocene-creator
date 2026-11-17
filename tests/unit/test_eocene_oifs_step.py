"""Unit tests for the ``oifs`` step (EoceneOIFS): declared paths, config mapping, no writes into Herold."""

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core.config import EoceneOIFS as EoceneOIFSOptions
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context, Stage
from ecefast.periods.eocene.oifs.eoceneOIFS import EoceneOIFS
from ecefast.periods.eocene.oifs.fields import flatten_grib_steps, replace_field
from synthetic import make_config

pytestmark = pytest.mark.unit

needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")
needs_grib_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("cdo", "grib_copy", "grib_count", "grib_get", "grib_set")),
    reason="needs cdo and the ecCodes tools grib_copy, grib_count, grib_get, grib_set",
)


def make_context(tmp_path: Path, aerosols: bool = False) -> Context:
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    config = make_config(tmp_path)
    config.eocene.oifs = EoceneOIFSOptions(aerosols=aerosols)
    return Context(config, "eocene")


def write_herold_topo(herold: Path) -> None:
    """Tiny synthetic Herold topography and subgrid standard deviation on a 30-degree grid."""
    lat = np.arange(-75.0, 90.0, 30.0)
    lon = np.arange(15.0, 360.0, 30.0)
    coords = {
        "lat": ("lat", lat, {"units": "degrees_north", "standard_name": "latitude"}),
        "lon": ("lon", lon, {"units": "degrees_east", "standard_name": "longitude"}),
    }
    topo = 1000.0 * np.cos(np.deg2rad(lat))[:, None] * np.sin(np.deg2rad(lon))[None, :]
    xr.Dataset({"topo": (("lat", "lon"), topo)}, coords=coords).to_netcdf(herold / "herold_etal_eocene_topo_1x1.nc")
    sd = np.abs(topo) / 10.0
    sd[0, 0] = np.nan
    xr.Dataset({"paleo_stddev_subgrid_topo": (("lat", "lon"), sd)}, coords=coords).to_netcdf(
        herold / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"
    )


def snapshot(folder: Path) -> dict[str, float]:
    return {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}


# --- declared paths ------------------------------------------------------------------------------------------------


def test_class_attributes() -> None:
    assert (EoceneOIFS.name, EoceneOIFS.component) == ("oifs", "oifs")
    assert EoceneOIFS.needs == ["stage"]
    assert EoceneOIFS.writes
    assert all(w.startswith(("{output}/oifs/", "{output}/initial_state/oifs/")) for w in EoceneOIFS.writes)
    # reads come only from the read-only trees: the step opens the original files, not the staged copies
    assert EoceneOIFS.reads and all(r.startswith(("{input}/", "{herold}/")) for r in EoceneOIFS.reads)
    assert len(set(EoceneOIFS.reads)) == len(EoceneOIFS.reads)
    assert len(set(EoceneOIFS.writes)) == len(EoceneOIFS.writes)


def test_writes_are_the_staged_copies_of_the_input_files() -> None:
    """Each output replaces the staged copy of an input GRIB file, inside a directory that stage writes."""
    grib_reads = {r.removeprefix("{input}/") for r in EoceneOIFS.reads if r.startswith("{input}/")}
    assert {w.removeprefix("{output}/") for w in EoceneOIFS.writes} == grib_reads
    staged = [s.removeprefix("{output}/") for s in Stage.writes]
    for w in EoceneOIFS.writes:
        assert any(w.removeprefix("{output}/").startswith(s + "/") for s in staged)


def test_dated_folders_come_from_the_config() -> None:
    """The initial-state date and the climate version are grids.oifs keys, not hardcoded."""
    for p in EoceneOIFS.reads + EoceneOIFS.writes:
        assert "19900101" not in p and "climate.v020" not in p
        assert "{grids.oifs.startdate}" in p or "{grids.oifs.climate_version}" in p or "{herold}" in p


def test_declared_paths_expand(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    for template in EoceneOIFS.reads + EoceneOIFS.writes:
        assert "{" not in ctx.expand(template)
    for template in EoceneOIFS.writes:
        ctx.check_writable(ctx.expand(template), EoceneOIFS.name)


# --- from_context --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("aerosols", [False, True])
def test_from_context_maps_config(tmp_path: Path, aerosols: bool) -> None:
    ctx = make_context(tmp_path, aerosols=aerosols)
    step = EoceneOIFS.from_context(ctx)
    assert step.idir == ctx.section.input
    assert step.odir == ctx.section.output
    assert step.herold == ctx.section.herold
    assert step.startdate == "19900101"
    assert step.resolution == "TL63L31"
    assert step.gaussian == 32
    assert step.build_aerosols is aerosols
    assert step.tmpdir == ctx.tmpdir("oifs") == os.path.join(ctx.config.machine.tmpdir, "eocene", "oifs")
    assert os.path.isdir(step.tmpdir)
    assert not step.own_tmpdir
    assert step.idir_init == os.path.join(ctx.section.input, "initial_state", "oifs", "TL63L31", "19900101")
    assert step.odir_init == os.path.join(ctx.section.output, "initial_state", "oifs", "TL63L31", "19900101")
    assert step.odir_climate == os.path.join(ctx.section.output, "oifs", "TL63L31", "climate.v020")


def test_from_context_follows_grids_oifs(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    ctx.config.grids.oifs.startdate, ctx.config.grids.oifs.climate_version = "20000101", "climate.v015"
    step = EoceneOIFS.from_context(ctx)
    assert step.startdate == "20000101"
    assert step.idir_climate == os.path.join(ctx.section.input, "oifs", "TL63L31", "climate.v015")


def test_constructor_without_tmpdir_uses_a_temporary_directory(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    step = EoceneOIFS(ctx.section.input, ctx.section.output, ctx.section.herold, "19900101")
    try:
        assert step.own_tmpdir
        assert os.path.isdir(step.tmpdir)
        assert not step.tmpdir.startswith(ctx.section.herold)
    finally:
        shutil.rmtree(step.tmpdir)


def test_from_context_refuses_tmpdir_inside_herold(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    ctx.config.machine.tmpdir = os.path.join(ctx.section.herold, "tmp")
    with pytest.raises(PipelineError, match="herold"):
        EoceneOIFS.from_context(ctx)


# --- prepare_herold: intermediates in tmpdir, never in the Herold folder ------------------------------------------


@needs_cdo
@pytest.mark.parametrize("flag", ["landsea_mask", "mask_opensea", "bathymetry", "orography", "sd_orography"])
def test_prepare_herold_writes_only_to_tmpdir(tmp_path: Path, flag: str) -> None:
    ctx = make_context(tmp_path)
    herold = Path(ctx.section.herold)
    write_herold_topo(herold)
    before = snapshot(herold)

    step = EoceneOIFS.from_context(ctx)
    result = step.prepare_herold(flag=flag)

    assert snapshot(herold) == before
    assert os.path.dirname(result) == step.tmpdir
    ds = xr.open_dataset(result)
    assert flag in ds
    assert "topo" not in ds
    if flag in ("landsea_mask", "orography", "sd_orography"):
        assert result.endswith(f"{flag}_remap.nc")
        assert ds.sizes["lat"] == 2 * step.gaussian
    else:
        assert result.endswith(f"{flag}.nc")
    ds.close()


# --- GRIB helpers: atomic in-place writes ---------------------------------------------------------------------------


def make_grib(path: Path, param: str, value: float, fmt: str = "grb") -> None:
    cmd = ["cdo", "-s", "-f", fmt, "-setdate,1990-01-01", f"-setparam,{param}", f"-const,{value},r4x2", str(path)]
    subprocess.run(cmd, check=True)


def grib_values(path: Path, key: str) -> list[str]:
    out = subprocess.run(["grib_get", "-p", key, str(path)], capture_output=True, text=True, check=True)
    return out.stdout.split()


@needs_grib_tools
def test_replace_field_in_place(tmp_path: Path) -> None:
    base, t_new, u = tmp_path / "base.grb", tmp_path / "t_new.grb", tmp_path / "u.grb"
    make_grib(base, "130.128", 1)
    make_grib(u, "131.128", 2)
    base.write_bytes(base.read_bytes() + u.read_bytes())
    make_grib(t_new, "130.128", 5)

    replace_field(str(base), str(t_new), str(base), ["t"])

    assert grib_values(base, "shortName") == ["u", "t"]
    assert grib_values(base, "average") == ["2", "5"]
    assert not t_new.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base.grb", "u.grb"]


@needs_grib_tools
def test_flatten_grib_steps_writes_nothing_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    grib = tmp_path / "clim.grb"
    make_grib(grib, "130.128", 1, fmt="grb2")

    flatten_grib_steps(str(grib))

    assert list(work.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clim.grb", "work"]
    assert grib_values(grib, "step") == ["0"]
