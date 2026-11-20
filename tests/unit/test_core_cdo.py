"""Unit tests for the shared CDO accessor."""

import subprocess
import sys

import pytest

from ecefast.core import cdo as core_cdo

pytestmark = pytest.mark.unit


def test_get_cdo_returns_one_shared_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    created = []
    monkeypatch.setattr(core_cdo, "Cdo", lambda: created.append(object()) or created[-1])
    monkeypatch.setattr(core_cdo, "find_cdo_binary", lambda: "/usr/bin/cdo")
    core_cdo.get_cdo.cache_clear()
    try:
        first = core_cdo.get_cdo()
        assert core_cdo.get_cdo() is first
        assert len(created) == 1
    finally:
        core_cdo.get_cdo.cache_clear()


def test_get_cdo_without_binary_suggests_module_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDO", raising=False)
    monkeypatch.setenv("PATH", "")
    core_cdo.get_cdo.cache_clear()
    try:
        with pytest.raises(core_cdo.PipelineError, match="module load cdo"):
            core_cdo.get_cdo()
    finally:
        core_cdo.get_cdo.cache_clear()


def test_find_cdo_binary_prefers_cdo_variable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    binary = tmp_path / "my-cdo"
    binary.write_text("")
    monkeypatch.setenv("CDO", str(binary))
    monkeypatch.setenv("PATH", "")
    assert core_cdo.find_cdo_binary() == str(binary)


@pytest.mark.parametrize("found", ["2.5.0", "2.5.3", "2.5.10"])
def test_check_cdo_version_accepts_the_series(found: str) -> None:
    core_cdo.check_cdo_version(found, "v1")


@pytest.mark.parametrize("found", ["2.6.0", "2.6.5", "2.4.0", "3.5.0", "2.50.1"])
def test_check_cdo_version_rejects_other_versions(found: str) -> None:
    with pytest.raises(core_cdo.PipelineError) as error:
        core_cdo.check_cdo_version(found, "v1")
    message = str(error.value)
    assert f"data_version v1 needs CDO 2.5.x, found CDO {found}" in message
    assert "ocean fraction of exactly 0.5" in message
    assert "module avail cdo" in message and "cdo=2.5" in message


@pytest.mark.parametrize("found, accepted", [("2.6.0", True), ("2.6.4", True), ("2.5.0", False), ("2.7.0", False)])
def test_check_cdo_version_v2_needs_2_6(found: str, accepted: bool) -> None:
    if accepted:
        core_cdo.check_cdo_version(found, "v2")
    else:
        with pytest.raises(core_cdo.PipelineError, match=f"data_version v2 needs CDO 2.6.x, found CDO {found}"):
            core_cdo.check_cdo_version(found, "v2")


# Modules that used to create a Cdo() at import time.
CDO_MODULES = [
    "ecefast.cli.main",
    "ecefast.periods.eocene.pipeline",
    "ecefast.components.nemo.domain.pipeline",
    "ecefast.components.oifs.generator",
    "ecefast.components.oifs.initial_state",
    "ecefast.components.oifs.climate",
    "ecefast.components.oifs.corners",
    "ecefast.components.oifs.grid_files",
    "ecefast.periods.eocene.oifs.albedo",
    "ecefast.periods.eocene.oifs.eoceneOIFS",
    "ecefast.periods.eocene.oifs.subgrid_orog",
    "ecefast.periods.eocene.oifs.fields",
    "ecefast.periods.eocene.oifs.vegetation",
    "ecefast.periods.eocene.nemo.eoceneNEMO",
    "ecefast.core.plotting",
]

IMPORT_WITHOUT_SUBPROCESS = """
import importlib, subprocess, sys

def refuse(*args, **kwargs):
    raise AssertionError(f"subprocess started at import time: {args}")

subprocess.Popen.__init__ = refuse
for module in sys.argv[1:]:
    importlib.import_module(module)

from ecefast.core.cdo import get_cdo
assert get_cdo.cache_info().currsize == 0, "Cdo instance created at import time"
"""


def test_import_creates_no_cdo_instance() -> None:
    # fresh interpreter: the modules must not be imported yet
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_WITHOUT_SUBPROCESS, *CDO_MODULES], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
