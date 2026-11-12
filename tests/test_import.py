"""Smoke test: every module under ``src/ecefast`` imports.

Modules that run their work at import time (standalone HPC scripts with hardcoded paths and no
``if __name__ == "__main__"`` guard) cannot be imported in a test. They are listed in ``NOT_IMPORTABLE`` with
the reason, and the test fails if the list goes stale.
"""

import importlib
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src"
MODULES = sorted(
    ".".join(path.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in (SRC / "ecefast").rglob("*.py")
)

NOT_IMPORTABLE = {
    "ecefast.components.oifs.convert_aka_bika": "script: converts grids/*.csv relative to the cwd at import time",
    "ecefast.components.oifs.create_corners": "script: runs CDO on hardcoded HPC paths at import time",
    "ecefast.components.oifs.descriptor_generator": "script: runs CDO on hardcoded HPC paths at import time",
}


@pytest.mark.unit
def test_not_importable_list_is_current() -> None:
    assert set(NOT_IMPORTABLE) <= set(MODULES)


@pytest.mark.unit
@pytest.mark.parametrize(
    "module",
    [pytest.param(m, marks=pytest.mark.skip(reason=NOT_IMPORTABLE[m])) if m in NOT_IMPORTABLE else m for m in MODULES],
)
def test_import(module: str) -> None:
    importlib.import_module(module)
