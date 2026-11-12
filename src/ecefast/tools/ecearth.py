"""EC-Earth tools: the NEMO DOMAINcfg program, reached through one small interface.

The domain pipeline writes one ``namelist_cfg_<name>`` per bathymetry and asks a backend to run DOMAINcfg on
them. Every backend returns, per bathymetry name, the raw ``domain_cfg_<name>.nc`` and ``mesh_mask_<name>.nc``
written next to the namelists; the pipeline then post-processes them. The backend is chosen with
``tools.backend`` in the configuration (:func:`get_backend`):

``atos``
    ECMWF Atos: loads the HPC modules of ``tools.atos.profile`` (``hpc_profiles.yaml``), compiles DOMAINcfg if
    needed and runs it, through ``run_domain_cfg.sh``.
``local``
    A laptop: DOMAINcfg is not available. Use the domain built on Atos (``tools.precomputed.domain``).
``fake``
    Tests and CI: writes small but valid files with the structure of the DOMAINcfg output, without running
    DOMAINcfg. See :class:`FakeBackend` for what it does not do.

Run as ``python -m ecefast.tools.ecearth <profile>`` it prints the modules of an HPC profile, separated by
spaces; ``run_domain_cfg.sh`` uses this to load them.
"""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from ecefast.core.config import Config, load_yaml
from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

PROFILES_FILE = Path(__file__).with_name("hpc_profiles.yaml")
# The script stays next to the domain pipeline, which still calls it directly; task 5.2 moves it into tools/
# when the pipeline switches to get_backend.
RUN_DOMAIN_CFG = Path(__file__).parents[1] / "components" / "nemo" / "domain" / "run_domain_cfg.sh"

# Earth rotation rate (rad/s), 2*pi/rsiday with the sidereal day rsiday = 86164 s, as in NEMO (phycst.F90)
OMEGA = 2.0 * np.pi / 86164.0
# NEMO namelist value meaning "not set"
UNSET = 999999.0


def hpc_modules(profile: str) -> list[str]:
    """Modules to load for an HPC profile of ``hpc_profiles.yaml``.

    Parameters
    ----------
    profile : str
        Profile name, e.g. ``atos``.

    Returns
    -------
    list of str
        Module names, in loading order.

    Raises
    ------
    ValueError
        If the profile is not defined.
    """
    profiles = load_yaml(PROFILES_FILE)
    if profile not in profiles:
        raise ValueError(f"HPC profile '{profile}' not found in {PROFILES_FILE.name}. Available: {', '.join(profiles)}")
    return list(profiles[profile]["modules"])


def output_files(namelist_dir: str | os.PathLike, names: list[str]) -> dict[str, tuple[Path, Path]]:
    """Raw DOMAINcfg outputs per bathymetry name: ``(domain_cfg_<name>.nc, mesh_mask_<name>.nc)``."""
    namelist_dir = Path(namelist_dir)
    return {name: (namelist_dir / f"domain_cfg_{name}.nc", namelist_dir / f"mesh_mask_{name}.nc") for name in names}


def _check_outputs(outputs: dict[str, tuple[Path, Path]], backend: str) -> None:
    missing = [str(path) for pair in outputs.values() for path in pair if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"DOMAINcfg ({backend} backend) did not write: {', '.join(missing)}")


class EcEarthTools:
    """Interface of the EC-Earth tools backends."""

    name = ""

    def available(self) -> bool:
        """Whether DOMAINcfg can run with this backend on this machine."""
        raise NotImplementedError

    def domaincfg(self, namelist_dir: str | os.PathLike, names: list[str]) -> dict[str, tuple[Path, Path]]:
        """Run DOMAINcfg once per bathymetry.

        Parameters
        ----------
        namelist_dir : str or os.PathLike
            Directory holding ``namelist_cfg_<name>`` for every name. The outputs are written here too.
        names : list of str
            Bathymetry names.

        Returns
        -------
        dict
            Per name, the paths of the raw ``domain_cfg_<name>.nc`` and ``mesh_mask_<name>.nc``.
        """
        raise NotImplementedError


class AtosBackend(EcEarthTools):
    """Compile and run DOMAINcfg on ECMWF Atos with ``run_domain_cfg.sh``.

    ``namelist_dir`` must be the ``DOMAINcfg/`` folder of a NEMO tools directory (the one holding
    ``maketools``): the script compiles DOMAINcfg there if needed and runs it in ``DOMAINcfg/``.

    Parameters
    ----------
    profile : str
        HPC profile of ``hpc_profiles.yaml`` whose modules are loaded.
    oasis_lib_dir : str, optional
        Directory added to ``LD_LIBRARY_PATH`` (OASIS libraries of the EC-Earth build), if needed.
    """

    name = "atos"

    def __init__(self, profile: str = "atos", oasis_lib_dir: str | None = None):
        hpc_modules(profile)  # fail early on an unknown profile
        self.profile = profile
        self.oasis_lib_dir = oasis_lib_dir

    def available(self) -> bool:
        """True where an environment-modules system is set up (``MODULESHOME``), as on Atos."""
        return "MODULESHOME" in os.environ

    def command(self, namelist_dir: str | os.PathLike, names: list[str]) -> tuple[list[str], dict[str, str]]:
        """Command line and environment of ``run_domain_cfg.sh``.

        The arguments are the NEMO tools directory and the bathymetry names, as the domain pipeline passes them.
        The environment tells the script which Python reads the profile (this interpreter), which profile, and
        the optional OASIS library directory.
        """
        namelist_dir = Path(namelist_dir)
        if namelist_dir.name != "DOMAINcfg":
            raise ValueError(
                f"atos backend: the namelists must be in the DOMAINcfg/ folder of the NEMO tools directory, "
                f"got {namelist_dir}"
            )
        cmd = ["bash", str(RUN_DOMAIN_CFG), str(namelist_dir.parent), *names]
        env = {**os.environ, "ECEFAST_PYTHON": sys.executable, "ECEFAST_HPC_PROFILE": self.profile}
        if self.oasis_lib_dir:
            env["ECEFAST_OASIS_LIB_DIR"] = self.oasis_lib_dir
        return cmd, env

    def domaincfg(self, namelist_dir: str | os.PathLike, names: list[str]) -> dict[str, tuple[Path, Path]]:
        """Run ``run_domain_cfg.sh`` and return the raw outputs (see :meth:`EcEarthTools.domaincfg`)."""
        cmd, env = self.command(namelist_dir, names)
        logger.info("Running DOMAINcfg on Atos for %s", ", ".join(names))
        logger.debug("Executing: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, env=env)
        outputs = output_files(namelist_dir, names)
        _check_outputs(outputs, self.name)
        return outputs


class LocalBackend(EcEarthTools):
    """A laptop or workstation: DOMAINcfg is not available."""

    name = "local"

    def available(self) -> bool:
        """Always False."""
        return False

    def domaincfg(self, namelist_dir: str | os.PathLike, names: list[str]) -> dict[str, tuple[Path, Path]]:
        """Raise: DOMAINcfg cannot run locally."""
        raise RuntimeError(
            "DOMAINcfg cannot run with the 'local' backend (tools.backend: local). Use the domain built on Atos: "
            "set tools.precomputed.domain, which the Eocene 'domain' step installs; or run the domain pipeline "
            "on Atos with tools.backend: atos."
        )


def read_namelist(path: str | os.PathLike) -> dict[str, str]:
    """Read ``key = value`` pairs of a Fortran namelist file, without quotes and comments.

    Only single-valued entries are read; group names and the ``/`` terminators are skipped. Enough for the
    ``namelist_cfg`` written by the domain pipeline.
    """
    values = {}
    for line in Path(path).read_text().splitlines():
        match = re.match(r"\s*(\w+)\s*=\s*([^!]*)", line)
        if match:
            values[match.group(1).lower()] = match.group(2).strip().strip("'\"")
    return values


def _flag(value: str) -> bool:
    return value.strip(".").lower() in ("true", "t")


def vertical_grid(namelist: dict[str, str]) -> dict[str, np.ndarray]:
    """1-D vertical grid of DOMAINcfg from the analytic ORCA coefficients of the namelist (``namdom``).

    Same formula as NEMO DOMAINcfg (``zgr_z``, single tanh, ``ln_e3_dep = .true.``): depths of the T and W
    points from ``ppsur``, ``ppa0``, ``ppa1``, ``ppkth``, ``ppacr``, and the scale factors as depth differences.

    Returns
    -------
    dict
        ``gdept_1d``, ``gdepw_1d``, ``e3t_1d``, ``e3w_1d``, each of length ``jpkglo``.

    Raises
    ------
    NotImplementedError
        If the namelist uses another vertical grid definition (coefficients from ``ppdzmin``/``pphmax``,
        double tanh, or ``ln_e3_dep = .false.``).
    """
    coefs = {key: float(namelist[key]) for key in ("ppsur", "ppa0", "ppa1", "ppkth", "ppacr")}
    if (
        UNSET in coefs.values()
        or _flag(namelist.get("ldbletanh", ".false."))
        or not _flag(namelist.get("ln_e3_dep", ".false."))
    ):
        raise NotImplementedError(
            "fake backend: only the analytic ORCA vertical grid (ppsur, ppa0, ppa1, ppkth, ppacr set, single tanh, "
            "ln_e3_dep = .true.) is supported"
        )
    nk = int(namelist["jpkglo"])
    sur, a0, a1, kth, acr = (coefs[k] for k in ("ppsur", "ppa0", "ppa1", "ppkth", "ppacr"))
    zw = np.arange(1, nk + 1, dtype=float)
    zt = zw + 0.5
    gdepw = sur + a0 * zw + a1 * acr * np.log(np.cosh((zw - kth) / acr))
    gdept = sur + a0 * zt + a1 * acr * np.log(np.cosh((zt - kth) / acr))
    gdepw[0] = 0.0
    e3t = np.empty(nk)
    e3t[:-1] = np.diff(gdepw)
    e3t[-1] = e3t[-2]
    e3w = np.empty(nk)
    e3w[1:] = np.diff(gdept)
    e3w[0] = 2.0 * (gdept[0] - gdepw[0])
    return {"gdept_1d": gdept, "gdepw_1d": gdepw, "e3t_1d": e3t, "e3w_1d": e3w}


def _masks(bottom_level: np.ndarray, nk: int) -> dict[str, np.ndarray]:
    """T, U, V, F masks (z, y, x) from the bottom level; periodic in x, closed at the last row, no north fold."""
    tmask = (np.arange(1, nk + 1)[:, None, None] <= bottom_level[None]).astype("int8")
    east = np.roll(tmask, -1, axis=2)
    north = np.zeros_like(tmask)
    north[:, :-1] = tmask[:, 1:]
    north_east = np.roll(north, -1, axis=2)
    return {"tmask": tmask, "umask": tmask * east, "vmask": tmask * north, "fmask": tmask * east * north * north_east}


class FakeBackend(EcEarthTools):
    """Write small but valid DOMAINcfg outputs without running DOMAINcfg (tests and CI).

    For each ``namelist_cfg_<name>`` it reads the bathymetry (``cn_topo``, variable ``cn_bath``) and the
    coordinates (``cn_fcoord``) and writes ``domain_cfg_<name>.nc`` and ``mesh_mask_<name>.nc`` with the
    dimensions, variable names, dtypes and order of the DOMAINcfg output:

    - horizontal grid (``glam*``, ``gphi*``, ``e1*``, ``e2*``) copied from the coordinates file;
    - vertical grid (``nav_lev``, ``e3t_1d``, ...) computed as DOMAINcfg does (:func:`vertical_grid`);
    - ``bottom_level``: number of levels whose top lies above the sea floor, ``top_level`` 1 over ocean;
    - masks from ``bottom_level``.

    What it does not do: no partial steps (the 3-D scale factors are the 1-D ones), no minimum depth or
    ``rn_e3zps_*`` adjustment of the bathymetry, no closed seas, no ice-shelf cavities, no north-fold
    treatment of the masks, no ``gdept_0``/``gdepw_0`` and no ``DOMAIN_*`` global attributes. The numbers
    are not those of DOMAINcfg; only the structure is.
    """

    name = "fake"

    def available(self) -> bool:
        """Always True."""
        return True

    def domaincfg(self, namelist_dir: str | os.PathLike, names: list[str]) -> dict[str, tuple[Path, Path]]:
        """Write fake raw outputs (see :meth:`EcEarthTools.domaincfg`)."""
        outputs = output_files(namelist_dir, names)
        for name, (domain_file, mesh_file) in outputs.items():
            logger.info("Writing fake DOMAINcfg output for %s", name)
            namelist = read_namelist(Path(namelist_dir) / f"namelist_cfg_{name}")
            domain, mesh = self.build(namelist)
            for ds, path in ((domain, domain_file), (mesh, mesh_file)):
                encoding = {var: {"_FillValue": None} for var in ds.variables}
                with atomic_write(path) as tmp:
                    ds.to_netcdf(tmp, encoding=encoding, unlimited_dims=["time_counter"])
        return outputs

    @staticmethod
    def build(namelist: dict[str, str]) -> tuple[xr.Dataset, xr.Dataset]:
        """Fake ``domain_cfg`` and ``mesh_mask`` datasets from a parsed ``namelist_cfg``."""
        with xr.open_dataset(namelist["cn_fcoord"]) as coords, xr.open_dataset(namelist["cn_topo"]) as topo:
            coords = coords.load()
            depth = topo[namelist["cn_bath"]].squeeze(drop=True).values.astype(float)
        depth = np.where(np.isfinite(depth) & (depth > 0), depth, 0.0)

        zgr = vertical_grid(namelist)
        nk = len(zgr["gdept_1d"])
        ny, nx = depth.shape
        # number of W levels (tops of the T cells) above the sea floor; the last level is never ocean in NEMO
        bottom_level = np.minimum((zgr["gdepw_1d"][None, None, :] < depth[..., None]).sum(axis=-1), nk - 1)
        bottom_level = np.where(depth > 0, bottom_level, 0).astype("int32")
        masks = _masks(bottom_level, nk)

        t2d = ("time_counter", "y", "x")
        t3d = ("time_counter", "nav_lev", "y", "x")
        t1d = ("time_counter", "nav_lev")
        hgrid = {
            f"{kind}{point}": (t2d, coords[f"{kind}{point}"].values[None].astype("float64"))
            for kind in ("glam", "gphi", "e1", "e2")
            for point in "tuvf"
        }
        coriolis = {
            f"ff_{point}": (t2d, 2.0 * OMEGA * np.sin(np.deg2rad(coords[f"gphi{point}"].values))[None])
            for point in "ft"
        }
        nav = {
            "nav_lon": (("y", "x"), coords["glamt"].values.astype("float32")),
            "nav_lat": (("y", "x"), coords["gphit"].values.astype("float32")),
        }
        e3_1d = {key: (t1d, zgr[key][None]) for key in ("e3t_1d", "e3w_1d")}
        e3_3d = np.broadcast_to(zgr["e3t_1d"][None, :, None, None], (1, nk, ny, nx))
        e3w_3d = np.broadcast_to(zgr["e3w_1d"][None, :, None, None], (1, nk, ny, nx))
        coord_vars = {
            "nav_lev": ("nav_lev", zgr["gdept_1d"].astype("float32")),
            "time_counter": ("time_counter", np.zeros(1, dtype="float32")),
        }

        flags = {key: np.int32(_flag(namelist.get(key, ".false."))) for key in ("ln_zco", "ln_zps", "ln_sco")}
        domain = xr.Dataset(
            {
                **nav,
                "jpiglo": ((), np.int32(nx)),
                "jpjglo": ((), np.int32(ny)),
                "jpkglo": ((), np.int32(nk)),
                "jperio": ((), np.int32(namelist.get("jperio", 0))),
                **flags,
                "ln_isfcav": ((), np.int32(0)),
                **hgrid,
                **coriolis,
                **e3_1d,
                **{f"e3{p}_0": (t3d, e3_3d) for p in ("t", "u", "v", "f")},
                **{f"e3{p}_0": (t3d, e3w_3d) for p in ("w", "uw", "vw")},
                "bottom_level": (t2d, bottom_level[None]),
                "top_level": (t2d, (bottom_level > 0).astype("int32")[None]),
                "isf_draft": (t2d, np.zeros((1, ny, nx))),
                "bathy_metry": (t2d, depth[None]),
            },
            coords=coord_vars,
        )
        mesh = xr.Dataset(
            {
                **nav,
                **{key: (t3d, value[None]) for key, value in masks.items()},
                **{f"{p}maskutil": (t2d, masks[f"{p}mask"][:1]) for p in "tuv"},
                **hgrid,
                **coriolis,
                "mbathy": (t2d, bottom_level[None]),
                "misf": (t2d, np.zeros((1, ny, nx), dtype="int32")),
                **e3_1d,
                **{key: (t1d, zgr[key][None]) for key in ("gdept_1d", "gdepw_1d")},
            },
            coords=coord_vars,
        )
        return domain, mesh


def get_backend(config: Config) -> EcEarthTools:
    """The backend selected by ``tools.backend``.

    Parameters
    ----------
    config : Config
        Validated configuration.

    Returns
    -------
    EcEarthTools
        :class:`AtosBackend`, :class:`LocalBackend` or :class:`FakeBackend`.
    """
    tools = config.tools
    if tools.backend == "atos":
        return AtosBackend(profile=tools.atos.profile, oasis_lib_dir=tools.atos.oasis_lib_dir)
    if tools.backend == "local":
        return LocalBackend()
    if tools.backend == "fake":
        return FakeBackend()
    raise ValueError(f"Unknown tools.backend {tools.backend!r}: use atos, local or fake")


def main(argv: list[str] | None = None) -> None:
    """Print the modules of an HPC profile, separated by spaces (used by ``run_domain_cfg.sh``)."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("usage: python -m ecefast.tools.ecearth <profile>")
    try:
        modules = hpc_modules(argv[0])
    except ValueError as e:
        raise SystemExit(f"ERROR: {e}") from e
    sys.stdout.write(" ".join(modules) + "\n")


if __name__ == "__main__":
    main()
