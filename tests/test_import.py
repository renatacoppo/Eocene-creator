"""Smoke test: every module of the ``eocene`` package imports.

``ecefast/`` is not a package yet (flat imports, hyphenated scripts); it is added here in phase 2.
"""

import importlib
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).parents[1] / "eocene"
MODULES = sorted(
    ".".join(path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts).removesuffix(".__init__")
    for path in PACKAGE_DIR.rglob("*.py")
)


@pytest.mark.unit
@pytest.mark.parametrize("module", MODULES)
def test_import(module: str) -> None:
    importlib.import_module(module)
