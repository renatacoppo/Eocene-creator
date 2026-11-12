"""Unit tests for the shared CDO accessor."""

import subprocess
import sys

import pytest

from ecefast.core import cdo as core_cdo

pytestmark = pytest.mark.unit


def test_get_cdo_returns_one_shared_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    created = []
    monkeypatch.setattr(core_cdo, "Cdo", lambda: created.append(object()) or created[-1])
    core_cdo.get_cdo.cache_clear()
    try:
        first = core_cdo.get_cdo()
        assert core_cdo.get_cdo() is first
        assert len(created) == 1
    finally:
        core_cdo.get_cdo.cache_clear()


# Modules that used to create a Cdo() at import time.
CDO_MODULES = [
    "ecefast.cli.main",
    "ecefast.paleo.eocene.pipeline",
    "ecefast.components.nemo.domain.pipeline",
    "ecefast.components.oifs.generator",
    "ecefast.paleo.eocene.oifs.albedo",
    "ecefast.paleo.eocene.oifs.eoceneOIFS",
    "ecefast.paleo.eocene.oifs.subgrid_orog",
    "ecefast.paleo.eocene.oifs.fields",
    "ecefast.paleo.eocene.oifs.vegetation",
    "ecefast.paleo.eocene.nemo.eoceneNEMO",
    "ecefast.paleo.eocene.plots.helper_functions",
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
