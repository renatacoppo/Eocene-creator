"""Small synthetic inputs shared by several tests (``tests/`` is on ``sys.path``: ``pythonpath`` in ``pyproject.toml``)."""

import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.core.config import Config, DomainSteps, Eocene, EoceneNEMO, Grids, Machine, NemoGrid, Present
from ecefast.periods.eocene.bathymetry import EoceneBathymetry
from ecefast.tools.ecearth import FakeBackend

NY, NX = 6, 8

# NEMO domain pipeline steps that run on the synthetic grid (see write_domain_work)
STEPS_WITHOUT_GRIDS = {
    "coordinates": False,
    "bathymetry": False,
    "configure_domain": True,
    "domain_cfg": True,
    "generate_mask": True,
    "generate_subbasins": False,
}
# the bathymetry files of the period processors in the work directory of the domain pipeline
BATHYMETRY_FILES = {
    "eocene": "bathymetry/PALEORCA2/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc",
    "present": "bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc",
}


def write_domain_inputs(coords_file: Path, bathy_file: Path) -> None:
    """Write PALEORCA2-like coordinates without halo and a bathymetry, as the domain pipeline makes them.

    The bathymetry has a land strip (two columns), a 50 m point (five T levels) and a missing value (land).
    """
    coords_file.parent.mkdir(parents=True, exist_ok=True)
    bathy_file.parent.mkdir(parents=True, exist_ok=True)
    lon = np.linspace(0, 315, NX)[None].repeat(NY, axis=0)
    lat = np.linspace(-60, 60, NY)[:, None].repeat(NX, axis=1)
    coords = {}
    for point, shift in zip("tuvf", (0.0, 0.5, 0.0, 0.5)):
        coords[f"glam{point}"] = (("y", "x"), lon + shift)
        coords[f"gphi{point}"] = (("y", "x"), lat + shift)
        coords[f"e1{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
        coords[f"e2{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
    xr.Dataset(coords).to_netcdf(coords_file)

    depth = np.full((NY, NX), 4000.0)
    depth[:, :2] = 0.0  # a land strip
    depth[2, 4] = 50.0  # shallow point: five T levels
    depth[3, 5] = np.nan  # missing value = land
    xr.Dataset(
        {"bathy_metry": (("time_counter", "y", "x"), depth[None])},
        coords={"lon": (("y", "x"), lon), "lat": (("y", "x"), lat)},
    ).to_netcdf(bathy_file)


def make_config(root: Path, tmpdir: str | None = None, machine: str = "local", **sections) -> Config:
    """A schema 2 :class:`Config` built in memory.

    ``present``: input ``root/input``, output ``root/present``. ``eocene``: input ``root/input``, Herold data
    ``root/herold``, output ``root/out``, domain from ``root/precomputed``. Scratch ``tmpdir`` (default
    ``root/tmp``). ``sections`` override the sections (``eocene=...``, ``grids=...``).
    """
    present = Present(input=str(root / "input"), output=str(root / "present"))
    eocene = Eocene(
        input=str(root / "input"),
        herold=str(root / "herold"),
        output=str(root / "out"),
        nemo=EoceneNEMO(domain=str(root / "precomputed"), minimum_depth=30),
    )
    values = {
        "present": present,
        "eocene": eocene,
        "grids": Grids(nemo=NemoGrid(coords_ori=str(root / "coords_ori.nc"))),
    }
    return Config(
        file="test.yml", machine=Machine(tmpdir=tmpdir or str(root / "tmp"), name=machine), **(values | sections)
    )


def write_domain_work(workdir: Path, period: str = "eocene") -> None:
    """The outputs of the domain steps that need real grids (``coordinates``, ``bathymetry`` of the period's
    processor), written as small synthetic files where the pipeline expects them in its work directory."""
    write_domain_inputs(workdir / "coordinates" / "PALEORCA2" / "coords_halo.nc", workdir / BATHYMETRY_FILES[period])


# --- synthetic Eocene input tree ------------------------------------------------------------------------------------
#
# One writer per declared ``reads`` template of the steps run in CI (stage, domain, oasis, nemo, rnfm).
# :func:`write_input_tree` writes exactly the declared reads of the given steps, so a ``create_*`` method that reads
# an undeclared file fails, and a newly declared read without a writer here fails too. Grids are tiny except where
# the step hardcodes them: the Herold 1x1 files (rnfm tracks rivers on 180x360) and zdfiwm (remapped to r720x360).

LAT_1X1 = np.arange(-89.5, 90.0, 1.0)
LON_1X1 = np.arange(0.5, 360.0, 1.0)
DEGREES_NORTH = {"units": "degrees_north", "standard_name": "latitude"}
DEGREES_EAST = {"units": "degrees_east", "standard_name": "longitude"}


def _lat_lon_1x1(name: str, values: np.ndarray) -> xr.Dataset:
    """A field on the regular 1x1 degree grid of the Herold et al. (2014) files."""
    return xr.Dataset(
        {name: (("lat", "lon"), values.astype("float64"))},
        coords={"lat": ("lat", LAT_1X1, DEGREES_NORTH), "lon": ("lon", LON_1X1, DEGREES_EAST)},
    )


def _tidal_dissipation(path: Path) -> None:
    _lat_lon_1x1("eo_tidal_dissipation", np.full((180, 360), 1.0e-3)).to_netcdf(path)


def _herold_topo(path: Path) -> None:
    topo = np.full((180, 360), -3000.0)
    topo[60:120, 100:140] = 500.0  # one continent
    _lat_lon_1x1("topo", topo).astype("float32").to_netcdf(path)


def _age_depth(path: Path) -> None:
    """Whitespace table ``lon lat age depth bathymetry`` on a 10 degree grid, ages 1 to 100 Myr."""
    lon, lat = np.meshgrid(np.arange(-180.0, 181.0, 10.0), np.arange(90.0, -91.0, -10.0))
    age = 1.0 + 99.0 * (lat + 90.0) / 180.0
    rows = np.column_stack(
        [lon.ravel(), lat.ravel(), age.ravel(), np.full(lon.size, -4000.0), np.full(lon.size, -4000.0)]
    )
    np.savetxt(path, rows, fmt="%g", delimiter="\t")


def _herold_runoff(path: Path) -> None:
    """River flow direction on 1x1 (``nj``, ``ni``): sea (0) except one continent draining south (5)."""
    flowdir = np.zeros((180, 360))
    flowdir[60:120, 100:140] = 5.0
    xc, yc = np.meshgrid(LON_1X1, LAT_1X1)
    xr.Dataset(
        {
            "RTM_FLOW_DIRECTION": (("nj", "ni"), flowdir.astype("float32")),
            "xc": (("nj", "ni"), xc.astype("float32")),
            "yc": (("nj", "ni"), yc.astype("float32")),
        }
    ).to_netcdf(path)


def _zdfiwm(path: Path) -> None:
    """Internal-wave mixing forcing on r720x360 (the grid ``create_tidal_mixing`` remaps to)."""
    coords = {"latitude": np.arange(-89.75, 90.0, 0.5), "longitude": np.arange(0.25, 360.0, 0.5)}
    shape = (360, 720)
    names = ["power_bot", "power_cri", "power_nsq", "power_sho", "scale_cri", "scale_bot", "bathymetry"]
    xr.Dataset({n: (("latitude", "longitude"), np.ones(shape)) for n in names}, coords=coords).to_netcdf(path)


def _ghflux(path: Path) -> None:
    lat = np.arange(-85.0, 90.0, 10.0, dtype="float32")
    lon = np.arange(5.0, 360.0, 10.0, dtype="float32")
    flux = np.full((1, lat.size, lon.size), 80.0, dtype="float32")
    xr.Dataset({"gh_flux": (("time", "lat", "lon"), flux)}, coords={"time": [0.0], "lat": lat, "lon": lon}).to_netcdf(
        path, unlimited_dims=["time"]
    )


def _woa(path: Path) -> None:
    """WOA climatology: 2 months, 31 levels (the PALEORCA2 domains), on the synthetic NY x NX grid."""
    nt, nz = 2, 31
    lon = np.linspace(0, 315, NX)[None].repeat(NY, axis=0)
    lat = np.linspace(-60, 60, NY)[:, None].repeat(NX, axis=1)
    thetao = np.broadcast_to(np.linspace(25.0, 2.0, nz)[None, :, None, None], (nt, nz, NY, NX)).astype("float32")
    xr.Dataset(
        {
            "thetao": (("time_counter", "z", "y", "x"), thetao, {"units": "degC"}),
            "so": (("time_counter", "z", "y", "x"), np.full_like(thetao, 35.0), {"units": "psu"}),
        },
        coords={"time_counter": np.arange(nt, dtype="float32"), "lon": (("y", "x"), lon), "lat": (("y", "x"), lat)},
    ).to_netcdf(path, unlimited_dims=["time_counter"])


def _nemo_runoff(path: Path) -> None:
    xr.Dataset(
        {
            "socoefr": (("y", "x"), np.ones((NY, NX), dtype="float32")),
            "sorunoff": (("time", "y", "x"), np.ones((2, NY, NX), dtype="float32")),
        },
        coords={"time": [0.0, 1.0]},
    ).to_netcdf(path, unlimited_dims=["time"])


def _rstos(path: Path) -> None:
    names = ["OIceFrc", "OIceTck", "OSnwTck", "O_AlbIce", "O_TepIce", "O_SSTSST"]
    xr.Dataset({n: (("y", "x"), np.ones((NY, NX))) for n in names}).to_netcdf(path)


def _runoff_maps(path: Path) -> None:
    """Runoff-mapper target grid (regular lat/lon, coarse)."""
    lat, lon = np.linspace(-80.0, 80.0, 9), np.arange(0.0, 360.0, 20.0)
    zeros = np.zeros((lat.size, lon.size), dtype="int32")
    names = ["drainage_basin_id", "arrival_point_id", "calving_point_id"]
    xr.Dataset({n: (("lat", "lon"), zeros) for n in names}, coords={"lat": lat, "lon": lon}).to_netcdf(path)


def _domain(path: Path) -> None:
    """A present-day domain: the fake DOMAINcfg domain of the synthetic grid, so it shares the Eocene vertical grid."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_domain_work(root / "work")
        grids = {"target": "PALEORCA2", "source": None, "staggering_source": "T", "staggering_target": "T"}
        workflow = NEMOWorkflow(
            EoceneBathymetry,
            str(root / "topo.nc"),
            grids,
            str(root / "coords_ori.nc"),
            str(root / "input"),
            str(root / "work"),
            str(path.parent),
            30,
            STEPS_WITHOUT_GRIDS,
            FakeBackend(),
            log_level="WARNING",
        )
        workflow.run()
    (path.parent / "maskutil.nc").unlink()


def _directory(path: Path) -> None:
    """A component directory read by ``stage`` as a whole: one empty subdirectory, so ``stage`` has one to copy."""
    (path / "TL63L31").mkdir(parents=True, exist_ok=True)


READ_WRITERS = {
    "{input}/oifs": _directory,
    "{input}/nemo": lambda path: path.mkdir(parents=True, exist_ok=True),
    "{input}/oasis/{grids.nemo.name}": lambda path: path.mkdir(parents=True, exist_ok=True),
    "{input}/nemo/domain/{grids.nemo.name}/domain_cfg.nc": _domain,
    "{input}/oasis/{grids.nemo.name}/rstos.nc": _rstos,
    "{herold}/Green_Huber_eocene_tidal_dissipation_1x1.nc": _tidal_dissipation,
    "{herold}/herold_etal_eocene_topo_1x1.nc": _herold_topo,
    "{herold}/age_depth_bath_55.xyadb": _age_depth,
    "{input}/nemo/initial/zdfiwm_forcing_r720x360.nc": _zdfiwm,
    "{input}/nemo/initial/Goutorbe_ghflux.nc": _ghflux,
    "{input}/nemo/initial/woa13-levitus-L31.nc": _woa,
    "{input}/nemo/domain/ORCA2/domain_cfg.nc": _domain,
    "{input}/nemo/climatology/runoff_DaiTrenberth_{grids.nemo.name}.nc": _nemo_runoff,
    "{herold}/herold_etal_eocene_runoff_1x1.nc": _herold_runoff,
    "{input}/runoff-mapper/runoff_maps.nc": _runoff_maps,
}


def write_input_tree(steps: list, ctx) -> list[Path]:
    """Write a synthetic file for every declared ``reads`` path of ``steps``, and nothing else.

    Parameters
    ----------
    steps : list of ComponentStep subclasses
        Steps whose inputs to write.
    ctx : Context
        Run context, to expand the templates.

    Returns
    -------
    list of Path
        The paths written.
    """
    written = []
    for step in steps:
        for template in step.reads:
            assert template in READ_WRITERS, f"No synthetic writer for {template!r} (read by step '{step.name}')"
            path = Path(ctx.expand(template))
            if path.exists():  # read by two steps, or two templates for the same path
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            READ_WRITERS[template](path)
            written.append(path)
    return written
