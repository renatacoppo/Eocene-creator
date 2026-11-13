"""The ``ecefast`` logger.

Every module logs through ``logging.getLogger(__name__)``, so all loggers sit under ``ecefast``. Entry points
(the CLI and the NEMO helper scripts) call :func:`setup_logger` once to attach the handler and set the level.
"""

import logging

LOGGER_NAME = "ecefast"
LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)8s -> %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(level: str | int | None = None) -> logging.Logger:
    """Configure the ``ecefast`` logger and return it.

    Calling it again only updates the level; it never adds a second handler.

    Parameters
    ----------
    level : str, int or None
        Log level name (``"DEBUG"``, ``"INFO"``, ...) or number. ``None`` means ``"WARNING"``.

    Returns
    -------
    logging.Logger
        The ``ecefast`` logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(convert_logger(level))

    if not logger.handlers:
        # avoid duplication through the root logger
        logger.propagate = False
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)

    return logger


def convert_logger(loglev: str | int | None = None) -> str:
    """Convert a string or integer to a valid logging level name."""

    loglev_default = "WARNING"

    # If loglev is a string, convert it to uppercase
    if isinstance(loglev, str):
        loglev = loglev.upper()

    # If loglev is an integer, convert it to a string
    elif isinstance(loglev, int):
        loglev = logging.getLevelName(loglev)

    # If loglev is None, set it to the default log level
    elif loglev is None:
        loglev = loglev_default

    # If loglev is of an unsupported type, raise a ValueError
    else:
        raise ValueError("Invalid log level type. Must be a string or an integer.")

    # Check if the log level exists and retrieve its integer value
    loglev_int = getattr(logging, loglev, None)

    # If loglev_int is None, the log level doesn't exist
    if loglev_int is None:
        logging.warning(
            "Invalid logging level '%s' specified. Setting it back to default '%s'.", loglev, loglev_default
        )
        loglev = loglev_default

    return loglev
