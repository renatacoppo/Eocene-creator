"""Helpers for the Eocene OIFS unit tests (imported by the test modules next to this file).

Tiny GRIB files are made at test time, nothing is stored in git:

- grid-point messages start from the ecCodes sample templates ``reduced_gg_pl_32_grib{1,2}``, the reduced Gaussian
  N32 grid of TL63 (6114 points); ``grib_set`` sets the parameter, the date and a constant value. GRIB1 messages get
  the ECMWF centre and local table 128, as in the EC-Earth4 files;
- spectral messages are made with CDO (``gp2spl``) from a field on the regular Gaussian grid ``F<N>``.
"""

import functools
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

GRIB_TOOLS = ("cdo", "codes_info", "grib_copy", "grib_count", "grib_get", "grib_get_data", "grib_set")

needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")
needs_grib_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in GRIB_TOOLS),
    reason=f"needs cdo and the ecCodes tools {', '.join(GRIB_TOOLS[1:])}",
)

DATE = "19900101"
N32_POINTS = 6114  # points of the reduced Gaussian grid N32 (ecCodes sample reduced_gg_pl_32)


def run(cmd: list[str]) -> str:
    """Run a command, fail with its stderr, return its stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{result.stderr}")
    return result.stdout


@functools.cache
def samples_dir() -> Path:
    """The ecCodes samples directory (``codes_info -s``)."""
    return Path(run(["codes_info", "-s"]).strip())


# GRIB2 encodings of the EC-Earth4 files (ECE4-DATA-V3, TL63L31) where a plain shortName would pick another one:
# ICMCLECE4 albedo and LAI use the ECMWF local discipline 192, category 128, number = GRIB1 code
GRIB2_LOCAL_ECMWF = {"al": 174, "aluvp": 15, "aluvd": 16, "alnip": 17, "alnid": 18, "lai_lv": 66, "lai_hv": 67}
GRIB2_PARAM_ID = {"sd": 228141}  # snow depth on snow layers
GRIB2_LEVEL = {"sd": "snowLayer", **{v: "hybrid" for v in ("q", "crwc", "cswc", "clwc", "ciwc", "cc", "o3")}}


def parameter_keys(short_name: str, edition: int) -> str:
    """``grib_set`` keys selecting a parameter and its level, encoded as in the EC-Earth4 files.

    GRIB1: ECMWF centre and local table 128, surface level; ``codeNNN`` sets ``indicatorOfParameter=NNN`` (as in
    ``bare_soil_albedos.grb``, parameters without a shortName). GRIB2: see ``GRIB2_*`` above, surface by default.
    """
    if edition == 1:
        parameter = (
            f"indicatorOfParameter={int(short_name[4:])}"
            if short_name.startswith("code")
            else f"shortName={short_name}"
        )
        return f"centre=98,table2Version=128,typeOfLevel=surface,level=0,{parameter}"
    assert not short_name.startswith("code"), "codeNNN parameters are only made in GRIB1"
    level = GRIB2_LEVEL.get(short_name, "surface")
    level_keys = f"typeOfLevel={level},level={0 if level == 'surface' else 1}"
    if short_name in GRIB2_LOCAL_ECMWF:
        return f"{level_keys},discipline=192,parameterCategory=128,parameterNumber={GRIB2_LOCAL_ECMWF[short_name]}"
    if short_name in GRIB2_PARAM_ID:
        return f"{level_keys},paramId={GRIB2_PARAM_ID[short_name]}"
    return f"{level_keys},shortName={short_name}"


def make_grib(path: Path, fields: list[tuple[str, float, int]]) -> Path:
    """Reduced Gaussian N32 GRIB file with one constant message per ``(shortName, value, edition)``, in order."""
    with open(path, "wb") as out:
        for short_name, value, edition in fields:
            single = path.with_name(f"{path.name}.{short_name}")
            template = samples_dir() / f"reduced_gg_pl_32_grib{edition}.tmpl"
            keys = f"{parameter_keys(short_name, edition)},dataDate={DATE}"
            run(["grib_set", "-s", keys, "-d", str(value), str(template), str(single)])
            out.write(single.read_bytes())
            single.unlink()
    return path


def make_spectral_grib(path: Path, fields: list[tuple[str, float | str, int]], gaussian: int) -> Path:
    """Spectral GRIB file, one message per ``(shortName, value, edition)``: ``value`` is a constant or a CDO
    generator (``topo``) on ``F<gaussian>``, transformed with ``gp2spl`` (linear grid: F32 gives T63).

    ecCodes cannot pack small truncations (T15) in GRIB2: use ``gaussian`` >= 16.
    """
    with open(path, "wb") as out:
        for short_name, value, edition in fields:
            raw, single = path.with_name(f"{path.name}.{short_name}.raw"), path.with_name(f"{path.name}.{short_name}")
            source = f"-const,{value},F{gaussian}" if isinstance(value, (int, float)) else f"-{value},F{gaussian}"
            run(["cdo", "-s", "-f", f"grb{edition}", f"-setdate,{DATE}", "-gp2spl", source, str(raw)])
            run(["grib_set", "-s", parameter_keys(short_name, edition), str(raw), str(single)])
            out.write(single.read_bytes())
            raw.unlink()
            single.unlink()
    return path


def grib_keys(path: Path | str, keys: str) -> list[tuple[str, ...]]:
    """Values of the comma-separated ``keys`` for each message, in file order (strings, as ``grib_get`` prints them)."""
    return [tuple(line.split()) for line in run(["grib_get", "-p", keys, str(path)]).splitlines()]


def grib_data(path: Path | str, short_name: str, where: str | None = None) -> np.ndarray:
    """Grid-point values of the messages named ``short_name`` (or matching ``where``, e.g. ``paramId=117``),
    concatenated in file order (``grib_get_data``)."""
    lines = run(["grib_get_data", "-w", where or f"shortName={short_name}", str(path)]).splitlines()
    return np.array([float(line.split()[2]) for line in lines if line.strip() and not line.lstrip().startswith("Lat")])


def spectral_coefficients(path: Path | str, short_name: str) -> np.ndarray:
    """Spectral coefficients (real and imaginary parts interleaved, m-major) of the message ``short_name``."""
    out = run(["cdo", "-s", "--eccodes", "outputf,%.10g,1", f"-selname,{short_name}", str(path)])
    return np.array([float(x) for x in out.split()])
