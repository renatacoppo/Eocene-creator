"""Logger configuration for NEMO workflow."""

import logging


def setup_logging(level_str):
    """Configure the root logger for NEMO with specified log level.
    
    Args:
        level_str: Log level as a string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    level = getattr(logging, level_str.upper(), logging.INFO)
    root = logging.getLogger("nemo")
    root.setLevel(level)
    root.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)8s -> %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(handler)
