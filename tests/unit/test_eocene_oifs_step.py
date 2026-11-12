"""Unit tests for the ``oifs`` step (EoceneOIFS): declared paths, config mapping, no writes into Herold."""

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core.config import Config, Eocene, Grids, Paths
from ecefast.core.config import EoceneOIFS as EoceneOIFSOptions
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context, Stage
from ecefast.paleo.eocene.oifs.eoceneOIFS import EoceneOIFS
from ecefast.paleo.eocene.oifs.fields import flatten_grib_steps, replace_field

pytestmark = pytest.mark.unit

needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")
needs_grib_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("cdo", "grib_copy", "grib_count", "grib_get", "grib_set")),
    reason="needs cdo and the ecCodes tools grib_copy, grib_count, grib_get, grib_set",
)


def make_context(tmp_path: Path, tmpdir: bool = True, aerosols: bool = False) -> Context:
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    paths = Paths(
        input=str(tmp_path / "input"),
        output=str(tmp_path / "out"),
        herold=str(tmp_path / "herold"),
        tmpdir=str(tmp_path / "tmp") if tmpdir else None,
    )
    eocene = Eocene(oifs=EoceneOIFSOptions(aerosols=aerosols))
    return Context(Config(file="test.yml", paths=paths, grids=Grids(oifs="TL63L31"), eocene=eocene))


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
    assert EoceneOIFS.name == "oifs"
    assert EoceneOIFS.needs == ["stage"]
    assert EoceneOIFS.writes and all(w.startswith("{output}/oifs/") for w in EoceneOIFS.writes)
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


def test_startdate_matches_declared_paths() -> None:
    assert all(f"/{EoceneOIFS.STARTDATE}/" in p or "/climate.v020/" in p or "{herold}" in p for p in EoceneOIFS.reads)


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
    assert step.idir == ctx.paths.input
    assert step.odir == ctx.paths.output
    assert step.herold == ctx.paths.herold
    assert step.startdate == "19900101"
    assert step.resolution == "TL63L31"
    assert step.gaussian == 32
    assert step.build_aerosols is aerosols
    assert step.tmpdir == os.path.join(ctx.paths.tmpdir, "oifs")
    assert os.path.isdir(step.tmpdir)
    assert not step.own_tmpdir
    assert step.odir_init == os.path.join(ctx.paths.output, "oifs", "TL63L31", "19900101")


def test_from_context_without_tmpdir_uses_a_temporary_directory(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, tmpdir=False)
    step = EoceneOIFS.from_context(ctx)
    try:
        assert step.own_tmpdir
        assert os.path.isdir(step.tmpdir)
        assert not step.tmpdir.startswith(ctx.paths.herold)
    finally:
        shutil.rmtree(step.tmpdir)


def test_from_context_refuses_tmpdir_inside_herold(tmp_path: Path) -> None:
    ctx = make_context(tmp_path)
    ctx.paths.tmpdir = os.path.join(ctx.paths.herold, "tmp")
    with pytest.raises(PipelineError, match="herold"):
        EoceneOIFS.from_context(ctx)


# --- prepare_herold: intermediates in tmpdir, never in the Herold folder ------------------------------------------


@needs_cdo
@pytest.mark.parametrize("flag", ["landsea_mask", "mask_opensea", "bathymetry", "orography", "sd_orography"])
def test_prepare_herold_writes_only_to_tmpdir(tmp_path: Path, flag: str) -> None:
    ctx = make_context(tmp_path)
    herold = Path(ctx.paths.herold)
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
