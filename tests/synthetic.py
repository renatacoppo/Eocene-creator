"""Small synthetic inputs shared by several tests (``tests/`` is on ``sys.path``: ``pythonpath`` in ``pyproject.toml``)."""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr
import yaml

from ecefast.components.nemo.bathymetry import PROCESSORS
from ecefast.components.nemo.domain import pipeline
from ecefast.core.config import Config, Eocene, EoceneDomain, Inputs
from ecefast.paleo.eocene.bathymetry import EOCENE_PROCESSORS

NY, NX = 6, 8

# NEMO domain pipeline steps that run on the synthetic grid (see nemo_domain_section)
STEPS_WITHOUT_GRIDS = {
    "coordinates": False,
    "bathymetry": False,
    "configure_domain": True,
    "domain_cfg": True,
    "generate_mask": True,
    "generate_subbasins": False,
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


def make_config(root: Path, tmpdir: str | None = None, **sections) -> Config:
    """A schema 2 :class:`Config` built in memory: inputs ``root/input`` and ``root/herold``, Eocene output ``root/out``,
    Eocene domain from ``root/precomputed``; ``sections`` override the other sections (``eocene=...``, ``nemo=...``).
    """
    inputs = Inputs(ece4_data=str(root / "input"), herold=str(root / "herold"))
    eocene = Eocene(output_dir=str(root / "out"), domain=EoceneDomain(from_=str(root / "precomputed")))
    return Config(file="test.yml", inputs=inputs, tmpdir=tmpdir, **({"eocene": eocene} | sections))


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
        for name in ("input", "herold"):
            (root / name).mkdir()
        config = {
            "schema": 2,
            "inputs": {"ece4_data": str(root / "input"), "herold": str(root / "herold")},
            "machine": {"name": "fake"},
            "nemo": {"domain": nemo_domain_section(root / "domain", root)},
        }
        (root / "config.yml").write_text(yaml.safe_dump(config))
        pipeline.run(str(root / "config.yml"), {**PROCESSORS, **EOCENE_PROCESSORS}, log_level="WARNING")
        shutil.copy(root / "domain" / "nemo" / "domain" / "PALEORCA2" / "eocene" / "domain_cfg.nc", path)


def _directory(path: Path) -> None:
    """A component directory read by ``stage`` as a whole: one empty subdirectory, so ``stage`` has one to copy."""
    (path / "TL63L31").mkdir(parents=True, exist_ok=True)


READ_WRITERS = {
    "{inputs.ece4_data}/oifs": _directory,
    "{inputs.ece4_data}/nemo": lambda path: path.mkdir(parents=True, exist_ok=True),
    "{inputs.ece4_data}/oasis/{nemo.grid}": lambda path: path.mkdir(parents=True, exist_ok=True),
    "{inputs.ece4_data}/nemo/domain/{nemo.grid}/domain_cfg.nc": _domain,
    "{inputs.ece4_data}/oasis/{nemo.grid}/rstos.nc": _rstos,
    "{inputs.herold}/Green_Huber_eocene_tidal_dissipation_1x1.nc": _tidal_dissipation,
    "{inputs.herold}/herold_etal_eocene_topo_1x1.nc": _herold_topo,
    "{inputs.herold}/age_depth_bath_55.xyadb": _age_depth,
    "{inputs.ece4_data}/nemo/initial/zdfiwm_forcing_r720x360.nc": _zdfiwm,
    "{inputs.ece4_data}/nemo/initial/Goutorbe_ghflux.nc": _ghflux,
    "{inputs.ece4_data}/nemo/initial/woa13-levitus-L31.nc": _woa,
    "{inputs.ece4_data}/nemo/domain/PALEORCA2/domain_cfg.nc": _domain,
    "{inputs.ece4_data}/nemo/domain/ORCA2/domain_cfg.nc": _domain,
    "{inputs.ece4_data}/nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc": _nemo_runoff,
    "{inputs.herold}/herold_etal_eocene_runoff_1x1.nc": _herold_runoff,
    "{inputs.ece4_data}/runoff-mapper/runoff_maps.nc": _runoff_maps,
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


def nemo_domain_section(output_dir: Path, root: Path, steps: dict | None = None, bathymetries=None) -> dict:
    """The ``nemo.domain`` config section for the synthetic grid, with the outputs of the steps that need real grids.

    ``coordinates`` and ``bathymetry`` are off (they need real grids; ``tests/local/test_nemo_domain_fake.py``):
    their outputs (``coords_halo.nc``, the remapped bathymetry) are written as small synthetic files where the
    pipeline expects them. ``configure_domain``, ``domain_cfg`` (fake DOMAINcfg) and ``generate_mask`` run.
    """
    write_domain_inputs(
        output_dir / "work" / "coordinates" / "PALEORCA2" / "coords_halo.nc",
        output_dir / "work" / "bathymetry" / "PALEORCA2" / "HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc",
    )
    if steps is None:
        steps = STEPS_WITHOUT_GRIDS
    if bathymetries is None:
        bathymetries = [{"name": "eocene", "processor": "EoceneBathymetry", "source_file": "{inputs.herold}/topo.nc"}]
    return {
        "output_dir": str(output_dir),
        "coords_ori": str(root / "coords_ori.nc"),
        "source_grid": "eORCA1",
        "minimum_depth": 30,
        "steps": steps,
        "bathymetries": bathymetries,
    }
