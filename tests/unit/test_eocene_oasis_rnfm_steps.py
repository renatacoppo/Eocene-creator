"""Unit tests for the EoceneOASIS and EoceneRNFM pipeline steps."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core.config import Config, Eocene, EoceneOASIS as EoceneOASISOptions, Paths
from ecefast.core.workspace import Context
from ecefast.paleo.eocene.oasis.eoceneOASIS import EoceneOASIS
from ecefast.paleo.eocene.rnfm import eoceneRNFM
from ecefast.paleo.eocene.rnfm.eoceneRNFM import EoceneRNFM, create_basin_data

pytestmark = pytest.mark.unit

ICE_VARS = ["OIceFrc", "OIceTck", "OSnwTck", "O_AlbIce", "O_TepIce"]


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    paths = Paths(
        input=str(tmp_path / "input"),
        output=str(tmp_path / "out"),
        herold=str(tmp_path / "herold"),
        tmpdir=str(tmp_path / "tmp"),
    )
    eocene = Eocene(oasis=EoceneOASISOptions(constant_sst=280.5))
    return Context(Config(file="test.yml", paths=paths, eocene=eocene))


def write_rstos(path: Path) -> None:
    """A tiny rstos.nc with the variables create_rstos touches."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {var: (["y", "x"], np.ones((3, 4))) for var in ICE_VARS + ["O_SSTSST", "O_OCurx1"]}
    xr.Dataset(data).to_netcdf(path)


# --- reads / writes / from_context ---------------------------------------------------------------------------------


def test_oasis_paths_expand(ctx: Context) -> None:
    root = Path(ctx.paths.input).parent
    assert [ctx.expand(t) for t in EoceneOASIS.reads] == [str(root / "input/oasis/PALEORCA2/rstos.nc")]
    assert [ctx.expand(t) for t in EoceneOASIS.writes] == [str(root / "out/oasis/PALEORCA2/rstos.nc")]
    assert EoceneOASIS.name == "oasis" and EoceneOASIS.needs == ["stage"]


def test_rnfm_paths_expand(ctx: Context) -> None:
    root = Path(ctx.paths.input).parent
    assert [ctx.expand(t) for t in EoceneRNFM.reads] == [
        str(root / "herold/herold_etal_eocene_runoff_1x1.nc"),
        str(root / "input/runoff-mapper/runoff_maps.nc"),
    ]
    assert [ctx.expand(t) for t in EoceneRNFM.writes] == [str(root / "out/runoff-mapper/runoff_maps.nc")]
    assert EoceneRNFM.name == "rnfm" and EoceneRNFM.needs == ["stage"]


def test_oasis_from_context(ctx: Context) -> None:
    Path(ctx.paths.input).mkdir()
    step = EoceneOASIS.from_context(ctx)
    assert (step.idir, step.odir, step.nemo_resolution) == (ctx.paths.input, ctx.paths.output, "PALEORCA2")
    assert step.constant_sst == 280.5


def test_rnfm_from_context(ctx: Context) -> None:
    step = EoceneRNFM.from_context(ctx)
    assert (step.idir, step.odir, step.herold) == (ctx.paths.input, ctx.paths.output, ctx.paths.herold)


# --- EoceneOASIS ---------------------------------------------------------------------------------------------------


def test_oasis_run_writes_rstos(ctx: Context) -> None:
    write_rstos(Path(ctx.expand(EoceneOASIS.reads[0])))
    Path(ctx.paths.output).mkdir()
    EoceneOASIS.from_context(ctx).run()
    out_file = Path(ctx.expand(EoceneOASIS.writes[0]))
    with xr.open_dataset(out_file) as out:
        for var in ICE_VARS:
            assert (out[var] == 0.0).all()
        assert (out["O_SSTSST"] == 280.5).all()
        assert (out["O_OCurx1"] == 1.0).all()
    assert sorted(p.name for p in out_file.parent.iterdir()) == ["rstos.nc"]


def test_oasis_rstos_is_atomic(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    write_rstos(Path(ctx.expand(EoceneOASIS.reads[0])))

    def broken(self, path, *args, **kwargs):
        Path(path).write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(xr.Dataset, "to_netcdf", broken)
    with pytest.raises(OSError, match="disk full"):
        EoceneOASIS.from_context(ctx).run()
    assert list(Path(ctx.expand(EoceneOASIS.writes[0])).parent.iterdir()) == []


# --- EoceneRNFM ----------------------------------------------------------------------------------------------------


def write_rnfm_inputs(ctx: Context) -> None:
    """Synthetic Herold runoff file (2D xc/yc) and runoff-mapper target grid."""
    lat = np.array([-45.0, 45.0])
    lon = np.array([0.0, 120.0, 240.0])
    herold = Path(ctx.expand(EoceneRNFM.reads[0]))
    herold.parent.mkdir(parents=True)
    xr.Dataset(
        {
            "RTM_FLOW_DIRECTION": (["nj", "ni"], np.array([[0.0, 3.0, 5.0], [1.0, 0.0, 7.0]])),
            "xc": (["nj", "ni"], np.tile(lon, (2, 1))),
            "yc": (["nj", "ni"], np.tile(lat, (3, 1)).T),
        }
    ).to_netcdf(herold)
    target = Path(ctx.expand(EoceneRNFM.reads[1]))
    target.parent.mkdir(parents=True)
    xr.Dataset(coords={"lat": np.linspace(-60, 60, 4), "lon": np.linspace(0, 300, 6)}).to_netcdf(target)


def test_rnfm_run_builds_arrival_and_calving(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    write_rnfm_inputs(ctx)
    basins = np.array([[0.0, 0.0, 1.0], [1.0, -2.0, 1.0]])
    rivers = {0: [np.array([0, 0])], 1: [np.array([1, 1]), np.array([0, 2])]}
    calls = {}

    def fake_iter_track(flowdir, lat):
        calls["flowdir"], calls["lat"] = flowdir, lat.values
        return basins, rivers, None, []

    def fake_create_basin_data(final_file, ds_target, drainage, arrival, calving, lon, lat):
        calls.update(final_file=final_file, target=ds_target, drainage=drainage, arrival=arrival, calving=calving)
        calls.update(lon=lon.values, lat_out=lat.values)

    monkeypatch.setattr(eoceneRNFM, "iter_track", fake_iter_track)
    monkeypatch.setattr(eoceneRNFM, "create_basin_data", fake_create_basin_data)
    EoceneRNFM.from_context(ctx).run()

    np.testing.assert_array_equal(calls["flowdir"], [[0, 3, 5], [1, 0, 7]])
    np.testing.assert_array_equal(calls["lat"], [-45, 45])
    np.testing.assert_array_equal(calls["lon"], [0, 120, 240])
    np.testing.assert_array_equal(calls["lat_out"], [-45, 45])
    expected_arrival = np.array([[0.0, -2.0, 1.0], [-2.0, 1.0, -2.0]])
    np.testing.assert_array_equal(calls["arrival"], expected_arrival)
    np.testing.assert_array_equal(calls["calving"], expected_arrival)
    assert calls["calving"] is not calls["arrival"]
    assert calls["drainage"] is basins
    assert calls["final_file"] == ctx.expand(EoceneRNFM.writes[0])
    assert Path(calls["final_file"]).parent.is_dir()
    assert list(calls["target"].coords) == ["lat", "lon"]


def basin_inputs():
    lat = xr.DataArray(np.array([-45.0, 45.0]), dims="lat")
    lon = xr.DataArray(np.array([0.0, 120.0, 240.0]), dims="lon")
    field = np.array([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]])
    target = xr.Dataset(coords={"lat": np.array([-45.0, 45.0]), "lon": np.array([0.0, 120.0, 240.0])})
    return target, field, lon, lat


def test_create_basin_data_writes_int32(tmp_path: Path) -> None:
    target, field, lon, lat = basin_inputs()
    out = tmp_path / "runoff_maps.nc"
    create_basin_data(str(out), target, field, field + 10, field + 20, lon, lat)
    with xr.open_dataset(out) as ds:
        assert list(ds.data_vars) == ["drainage_basin_id", "arrival_point_id", "calving_point_id"]
        assert ds["arrival_point_id"].dtype == np.int32
        np.testing.assert_array_equal(ds["drainage_basin_id"], field)
        np.testing.assert_array_equal(ds["calving_point_id"], field + 20)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runoff_maps.nc"]


def test_create_basin_data_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, field, lon, lat = basin_inputs()

    def broken(self, path, *args, **kwargs):
        Path(path).write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(xr.Dataset, "to_netcdf", broken)
    with pytest.raises(OSError, match="disk full"):
        create_basin_data(str(tmp_path / "runoff_maps.nc"), target, field, field, field, lon, lat)
    assert list(tmp_path.iterdir()) == []
