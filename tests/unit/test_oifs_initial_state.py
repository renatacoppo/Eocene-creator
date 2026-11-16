"""Unit tests for the OIFS initial state processes (``ecefast.components.oifs.initial_state``)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from ecefast.components.oifs.initial_state import UPPER_AIR_FIELDS, select_upper_air_fields

pytestmark = pytest.mark.unit

needs_tools = pytest.mark.skipif(
    shutil.which("cdo") is None or shutil.which("grib_copy") is None, reason="needs cdo and grib_copy"
)


def grib_field(path: Path, param: str) -> Path:
    """A one-message GRIB2 file of the GRIB2 parameter ``param`` (discipline.category.number)."""
    subprocess.run(["cdo", "-s", "-f", "grb2", f"-setparam,{param}", "-const,1,r4x2", str(path)], check=True)
    return path


def short_names(path: Path) -> list[str]:
    result = subprocess.run(["grib_get", "-p", "shortName", str(path)], capture_output=True, text=True, check=True)
    return result.stdout.split()


def test_upper_air_fields_are_those_of_the_tl63l31_file() -> None:
    assert UPPER_AIR_FIELDS == ["q", "o3", "crwc", "cswc", "clwc", "ciwc", "cc"]


@needs_tools
def test_select_upper_air_fields_drops_other_fields(tmp_path: Path) -> None:
    """A source ICMGGECE4INIUA with fields OIFS does not read (here temperature): only the listed ones are kept."""
    q = grib_field(tmp_path / "q.grb", "0.1.0")  # specific humidity
    t = grib_field(tmp_path / "t.grb", "0.0.0")  # temperature
    source = tmp_path / "ICMGGECE4INIUA"
    source.write_bytes(t.read_bytes() + q.read_bytes() + t.read_bytes())
    assert short_names(source) == ["t", "q", "t"]

    select_upper_air_fields(str(source), str(tmp_path / "upper_air.grb"))
    assert short_names(tmp_path / "upper_air.grb") == ["q"]
