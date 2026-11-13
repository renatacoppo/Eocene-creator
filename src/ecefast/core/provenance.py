"""Provenance of a run: what ran, with which configuration and which tool versions.

:func:`write_provenance` writes ``provenance.yml`` into the output directory at the end of a successful run.
"""

import hashlib
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from ecefast import __version__

from .io import atomic_write

PROVENANCE_FILE = "provenance.yml"


def sha256(path: str | os.PathLike) -> str:
    """Hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _command_output(command: list[str], cwd: str | None = None) -> str:
    """First line of the output of ``command``, or ``"unknown"`` if it cannot run."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else "unknown"


def git_commit() -> str:
    """Git commit of the ``ecefast`` source tree, or ``"unknown"`` (e.g. installed from a wheel)."""
    return _command_output(["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).parent))


def eccodes_version() -> str:
    """Version of the ecCodes command-line tools first on ``PATH`` (``codes_info -v``), or ``"unknown"``."""
    return _command_output(["codes_info", "-v"])


def write_provenance(
    output_dir: str,
    steps: list[str],
    config_file: str,
    cdo_version: str,
    start: datetime,
    end: datetime,
) -> str:
    """Write ``provenance.yml`` into ``output_dir`` (atomically).

    Parameters
    ----------
    output_dir : str
        Output directory of the run.
    steps : list of str
        Names of the steps that ran, in order.
    config_file : str
        Configuration file of the run; its absolute path and SHA-256 are recorded.
    cdo_version : str
        Version of the CDO binary used by the run.
    start, end : datetime
        Start and end time of the run.

    Returns
    -------
    str
        Path of the written file.
    """
    record = {
        "steps": list(steps),
        "config": {"file": os.path.abspath(config_file), "sha256": sha256(config_file)},
        "ecefast": {"version": __version__, "git_commit": git_commit()},
        "versions": {"python": platform.python_version(), "cdo": cdo_version, "eccodes": eccodes_version()},
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }
    path = os.path.join(output_dir, PROVENANCE_FILE)
    with atomic_write(path) as tmp, open(tmp, "w") as f:
        yaml.safe_dump(record, f, sort_keys=False)
    return path
