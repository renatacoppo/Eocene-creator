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


# Modules that used to create a Cdo() at import time.
CDO_MODULES = [
    "ecefast.cli.main",
    "ecefast.periods.eocene.pipeline",
    "ecefast.components.nemo.domain.pipeline",
    "ecefast.components.oifs.generator",
    "ecefast.periods.eocene.oifs.albedo",
    "ecefast.periods.eocene.oifs.eoceneOIFS",
    "ecefast.periods.eocene.oifs.subgrid_orog",
    "ecefast.periods.eocene.oifs.fields",
    "ecefast.periods.eocene.oifs.vegetation",
    "ecefast.periods.eocene.nemo.eoceneNEMO",
    "ecefast.periods.eocene.plots.helper_functions",
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
