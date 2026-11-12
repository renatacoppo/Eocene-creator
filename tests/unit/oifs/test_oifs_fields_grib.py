"""Unit tests for the GRIB-level helpers of ``paleo.eocene.oifs.fields`` on tiny GRIB files made with CDO.

Checked: values written, message order, and the keys that EC-Earth reads (edition, grid, resolution, date).
"""

import logging
import subprocess
from pathlib import Path

import numpy as np
import pytest
from oifs_helpers import (
    grib_data,
    grib_keys,
    make_grib,
    needs_grib_tools,
    run,
)

from ecefast.paleo.eocene.oifs.fields import (
    flatten_grib_steps,
    modify_single_grib,
    modify_value,
    nullify_grib,
    replace_field,
)

pytestmark = [pytest.mark.unit, needs_grib_tools]

# A mixed GRIB1/GRIB2 surface file like ICMGGECE4INIT, on the reduced Gaussian N32 grid: (shortName, value, edition)
SURFACE = [("lsm", 1.0, 2), ("al", 0.3, 1), ("sd", 5.0, 2), ("tvh", 3.0, 2), ("aluvp", 0.2, 1)]
GRID_KEYS = "shortName,edition,gridType,numberOfValues,dataDate"


@pytest.fixture
def surface(tmp_path: Path) -> Path:
    return make_grib(tmp_path / "ICMGG", SURFACE)


@pytest.fixture(autouse=True)
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test in an empty directory, to check that the helpers leave nothing in the working directory."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


def keys_by_name(path: Path, keys: str = GRID_KEYS) -> dict[str, tuple[str, ...]]:
    return {row[0]: row[1:] for row in grib_keys(path, keys)}


# --- modify_single_grib --------------------------------------------------------------------------------------------


def test_modify_single_grib_grib1_field(surface: Path, tmp_path: Path, empty_cwd: Path) -> None:
    before = surface.read_bytes()
    keys_before = keys_by_name(surface)
    output = tmp_path / "out"

    modify_single_grib(str(surface), str(output), ["al"], modify_value, newvalue=0.7)

    assert surface.read_bytes() == before  # input untouched
    # replace_field appends the modified message after the others (the order the baseline was made with)
    assert [row[0] for row in grib_keys(output, "shortName")] == ["lsm", "sd", "tvh", "aluvp", "al"]
    # edition, reduced grid, size and date of every message are kept
    assert keys_by_name(output) == keys_before
    np.testing.assert_allclose(grib_data(output, "al"), 0.7, rtol=1e-6)
    for name, value, _ in SURFACE:
        if name != "al":
            np.testing.assert_allclose(grib_data(output, name), value, rtol=1e-6)
    assert list(empty_cwd.iterdir()) == []


def test_modify_single_grib_mixed_editions_take_the_first_one(surface: Path, tmp_path: Path) -> None:
    """All selected messages are written back in the edition of the first one (``detect_grib_version`` reads
    the first message only). Here lsm (GRIB2) comes first, so al (GRIB1, local table 128) is written as GRIB2 and
    loses its parameter: CDO cannot map table 128 code 174 to GRIB2. The EC-Earth4 files never select both
    editions in one call (in ICMGGECE4INIT only the snow fields asn, lwcs, rsn, sd, tsn are GRIB2).
    """
    output = tmp_path / "out"
    modify_single_grib(str(surface), str(output), ["al", "lsm"], modify_value, newvalue=0.5)

    assert grib_keys(output, "shortName,edition,paramId") == [
        ("sd", "2", "228141"),
        ("tvh", "2", "30"),
        ("aluvp", "1", "15"),
        ("lsm", "2", "172"),
        ("unknown", "2", "0"),  # was al, GRIB1
    ]


def test_modify_single_grib_missing_input(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        modify_single_grib(str(tmp_path / "missing"), str(tmp_path / "out"), ["al"], modify_value, newvalue=0)
    assert "does not exist" in caplog.text
    assert not (tmp_path / "out").exists()


# --- nullify_grib --------------------------------------------------------------------------------------------------


def test_nullify_grib_missing_input(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        nullify_grib(str(tmp_path / "missing"), str(tmp_path / "out"), ["sd"])
    assert "does not exist" in caplog.text
    assert not (tmp_path / "out").exists()


# --- replace_field -------------------------------------------------------------------------------------------------


def test_replace_field_paramid_and_list(tmp_path: Path) -> None:
    base = make_grib(tmp_path / "base.grb", [("code117", 1, 1), ("code118", 2, 1), ("code119", 3, 1)])
    new = make_grib(tmp_path / "new.grb", [("code117", 7, 1), ("code119", 9, 1)])

    replace_field(str(base), str(new), str(base), ["code117", "code119"], filter_method="paramId")

    assert grib_keys(base, "paramId,average") == [("118", "2"), ("117", "7"), ("119", "9")]
    assert not new.exists()


def test_replace_field_all_messages_replaced(tmp_path: Path) -> None:
    """When nothing is left after filtering, the replacement file is copied as is (``debug`` keeps it)."""
    base = make_grib(tmp_path / "base.grb", [("lsm", 1, 2)])
    new = make_grib(tmp_path / "new.grb", [("lsm", 0, 2)])
    output = tmp_path / "out.grb"

    replace_field(str(base), str(new), str(output), "lsm", debug=True)

    assert output.read_bytes() == new.read_bytes()
    assert new.exists()


def test_replace_field_unknown_filter(tmp_path: Path) -> None:
    base = make_grib(tmp_path / "base.grb", [("lsm", 1, 2)])
    with pytest.raises(ValueError, match="Unknown filter method"):
        replace_field(str(base), str(base), str(tmp_path / "out"), ["lsm"], filter_method="name")


# --- flatten_grib_steps --------------------------------------------------------------------------------------------


def monthly_climate(tmp_path: Path, edition: int) -> Path:
    """Three monthly messages of al, as in ICMCLECE4: steps 0, 744, 1416 h from 1990-01-01."""
    # GRIB1 needs timeRangeIndicator=10 for steps above 255 h
    extra = "timeRangeIndicator=10," if edition == 1 else ""
    clim = tmp_path / "ICMCL"
    with open(clim, "wb") as out:
        for value, step in ((0.1, 0), (0.2, 744), (0.3, 1416)):
            month = make_grib(tmp_path / "month", [("al", value, edition)])
            run(["grib_set", "-s", f"{extra}step={step}", str(month), str(tmp_path / "stepped")])
            out.write((tmp_path / "stepped").read_bytes())
    assert [row[0] for row in grib_keys(clim, "validityDate")] == ["19900101", "19900201", "19900301"]
    return clim


def test_flatten_grib_steps(tmp_path: Path) -> None:
    """Monthly steps become analyses (step 0) dated at their validity date, in the same order (ICMCLECE4 is GRIB2)."""
    clim = monthly_climate(tmp_path, edition=2)

    flatten_grib_steps(str(clim))

    assert grib_keys(clim, "dataDate,step,validityDate,edition,average") == [
        ("19900101", "0", "19900101", "2", "0.1"),
        ("19900201", "0", "19900201", "2", "0.2"),
        ("19900301", "0", "19900301", "2", "0.3"),
    ]


def test_flatten_grib_steps_grib2_only(tmp_path: Path) -> None:
    """GRIB1 messages have no ``forecastTime`` key: ``grib_set`` fails and the file is left as it was."""
    clim = monthly_climate(tmp_path, edition=1)
    before = clim.read_bytes()
    with pytest.raises(subprocess.CalledProcessError):
        flatten_grib_steps(str(clim))
    assert clim.read_bytes() == before
