"""Subprocess execution utilities for NEMO workflow."""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Helper scripts live in the package (ecefast/components/nemo), not in the caller's cwd.
NEMO_DIR = Path(__file__).resolve().parents[1]


class SubprocessExecutor:
    """Centralized subprocess execution with logging and error handling.

    Provides a consistent interface for running Python scripts,
    with automatic logging and path construction relative to script_dir.
    Python scripts run with the current interpreter (``sys.executable``).
    """

    def __init__(self, script_dir=NEMO_DIR):
        """Initialize executor with base script directory.

        Args:
            script_dir: Absolute path to directory containing scripts
                (default: the ecefast.components.nemo package directory)
        """
        self.script_dir = script_dir

    def run_python_script(self, script_path, args=None, check=True):
        """Execute a Python script with arguments.

        Args:
            script_path: Path relative to script_dir (e.g. 'orca_bounds.py')
            args: List of command-line arguments (default: [])
            check: Raise CalledProcessError on non-zero exit (default: True)

        Returns:
            CompletedProcess instance
        """
        args = args or []
        full_path = os.path.join(self.script_dir, script_path)
        cmd = [sys.executable, full_path] + args

        logger.debug("Executing Python script: %s", " ".join(cmd))
        result = subprocess.run(cmd, check=check)
        return result
