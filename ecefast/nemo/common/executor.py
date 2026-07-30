"""Subprocess execution utilities for NEMO workflow."""

import logging
import os
import subprocess

logger = logging.getLogger("nemo.commands.executor")


class SubprocessExecutor:
    """Centralized subprocess execution with logging and error handling.
    
    Provides a consistent interface for running Python and bash scripts,
    with automatic logging and path construction relative to script_dir.
    """
    
    def __init__(self, script_dir):
        """Initialize executor with base script directory.
        
        Args:
            script_dir: Absolute path to directory containing scripts
        """
        self.script_dir = script_dir
    
    def run_python_script(self, script_path, args=None, check=True):
        """Execute a Python script with arguments.
        
        Args:
            script_path: Path relative to script_dir (e.g. 'utils/generate-orca-bounds.py')
            args: List of command-line arguments (default: [])
            check: Raise CalledProcessError on non-zero exit (default: True)
        
        Returns:
            CompletedProcess instance
        """
        args = args or []
        full_path = os.path.join(self.script_dir, script_path)
        cmd = ['python3', full_path] + args
        
        logger.debug("Executing Python script: %s", ' '.join(cmd))
        result = subprocess.run(cmd, check=check)
        return result
    
    def run_bash_script(self, script_path, args=None, check=True):
        """Execute a bash script with arguments.
        
        Args:
            script_path: Path relative to script_dir (e.g. 'domain-tools/run_domain_cfg.sh')
            args: List of command-line arguments (default: [])
            check: Raise CalledProcessError on non-zero exit (default: True)
        
        Returns:
            CompletedProcess instance
        """
        args = args or []
        full_path = os.path.join(self.script_dir, script_path)
        cmd = ['bash', full_path] + args
        
        logger.debug("Executing bash script: %s", ' '.join(cmd))
        result = subprocess.run(cmd, check=check)
        return result
