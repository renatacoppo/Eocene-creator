"""Sphinx configuration for the ecefast documentation."""

import os
import sys

# Import the package from the repository, installed or not.
sys.path.insert(0, os.path.abspath("../src"))

try:
    from ecefast import __version__ as release
except ImportError:
    release = "unknown"

project = "ecefast"
author = "Renata Coppo, Paolo Davini"
copyright = "2026, Renata Coppo, Paolo Davini"
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

napoleon_google_docstring = False
napoleon_numpy_docstring = True

# Heavy compiled dependencies are mocked, so the docs build without CDO or ESMF.
autodoc_mock_imports = ["cdo", "xesmf", "cartopy", "eccodes"]

exclude_patterns = ["_build", "refactor-plan.md", "issue-refactor.md"]

html_theme = "sphinx_rtd_theme"
