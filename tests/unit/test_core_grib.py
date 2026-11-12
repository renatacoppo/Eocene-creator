"""Unit tests for the shared GRIB and grid helpers, on tiny GRIB files made with CDO at test time."""

import shutil
import subprocess
from pathlib import Path

import pytest

from ecefast.core.grib import (
    count_grib_messages,
    detect_grib_version,
    ecmwf_grid,
    extract_grid_info,
    repack_grib_file,
    spectral2gaussian,
    unpack_grib_file,
)

pytestmark = pytest.mark.unit

needs_grib_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("cdo", "grib_copy", "grib_count", "grib_get")),
    reason="needs cdo and the ecCodes tools grib_copy, grib_count, grib_get",
)


def make_grib(path: Path, value: int, edition: int) -> Path:
    """A one-message 4x2 GRIB file of constant ``value``, in GRIB edition 1 or 2."""
    fmt = "grb1" if edition == 1 else "grb2"
    subprocess.run(["cdo", "-s", "-f", fmt, f"-const,{value},r4x2", str(path)], check=True)
    return path


def make_mixed_grib(tmp_path: Path) -> Path:
    """GRIB2, GRIB1, GRIB2, GRIB1 messages with values 1, 2, 3, 4, concatenated in this order."""
    editions = [2, 1, 2, 1]
    mixed = tmp_path / "mixed.grb"
    with open(mixed, "wb") as out:
        for value, edition in enumerate(editions, start=1):
            single = make_grib(tmp_path / f"single_{value}.grb", value, edition)
            out.write(single.read_bytes())
    return mixed


def edition_and_value(path: Path) -> list[tuple[int, int]]:
    """(edition, constant value) of each message, in file order."""
    result = subprocess.run(["grib_get", "-p", "edition,max", str(path)], check=True, capture_output=True, text=True)
    return [
        (int(edition), round(float(value))) for edition, value in (line.split() for line in result.stdout.splitlines())
    ]


@pytest.mark.parametrize(
    ("grid", "expected"),
    [
        ("TL63L31", ("L", 63, 31)),
        ("tl63l31", ("L", 63, 31)),
        ("TCO95L91", ("CO", 95, 91)),
        ("TL255L91", ("L", 255, 91)),
    ],
)
def test_extract_grid_info(grid: str, expected: tuple[str, int, int]) -> None:
    assert extract_grid_info(grid) == expected


@pytest.mark.parametrize("grid", ["TL63", "ORCA2", "T63L31", ""])
def test_extract_grid_info_bad_input_returns_none(grid: str) -> None:
    assert extract_grid_info(grid) is None


def test_spectral2gaussian() -> None:
    assert spectral2gaussian(63, "L") == 32
    assert spectral2gaussian(95, "CO") == 96
    with pytest.raises(ValueError):
        spectral2gaussian(63, "Q")


def test_ecmwf_grid() -> None:
    assert ecmwf_grid("L") == "l_2"
    assert ecmwf_grid("co") == "_4"


@needs_grib_tools
def test_detect_grib_version(tmp_path: Path) -> None:
    assert detect_grib_version(make_grib(tmp_path / "g1.grb", 1, edition=1)) == 1
    assert detect_grib_version(make_grib(tmp_path / "g2.grb", 1, edition=2)) == 2
    text = tmp_path / "not_grib.txt"
    text.write_text("not a GRIB file")
    assert detect_grib_version(text) is None


@needs_grib_tools
def test_unpack_repack_round_trip_groups_grib1_before_grib2(tmp_path: Path) -> None:
    mixed = make_mixed_grib(tmp_path)
    assert count_grib_messages(mixed) == 4

    grib1, grib2 = unpack_grib_file(str(mixed), str(tmp_path / "tmp"))
    assert edition_and_value(Path(grib1)) == [(1, 2), (1, 4)]
    assert edition_and_value(Path(grib2)) == [(2, 1), (2, 3)]

    output = tmp_path / "repacked.grb"
    repack_grib_file(grib1, grib2, str(output))
    # same messages, regrouped: all GRIB1 messages first, then all GRIB2, each group in its original order
    assert count_grib_messages(output) == 4
    assert edition_and_value(output) == [(1, 2), (1, 4), (2, 1), (2, 3)]
    # clean=True removes the split files
    assert not Path(grib1).exists()
    assert not Path(grib2).exists()


@needs_grib_tools
def test_repack_with_one_edition_only(tmp_path: Path) -> None:
    grib2_only = make_grib(tmp_path / "g2.grb", 5, edition=2)
    grib1, grib2 = unpack_grib_file(str(grib2_only), str(tmp_path / "tmp"))
    assert not Path(grib1).exists()

    output = tmp_path / "repacked.grb"
    repack_grib_file(grib1, grib2, str(output), clean=False)
    assert edition_and_value(output) == [(2, 5)]
    assert Path(grib2).exists()
