"""Fixtures shared by all tests."""

import logging

import pytest


@pytest.fixture(autouse=True)
def restore_ecefast_logger():
    """Restore the handlers, level and propagation of the ``ecefast`` logger after each test.

    The CLI and the NEMO helper scripts call ``setup_logger``, which attaches a handler to the ``ecefast`` logger
    and turns propagation off; without this the handler leaks into later tests.
    """
    logger = logging.getLogger("ecefast")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    yield
    logger.handlers[:], logger.level, logger.propagate = handlers, level, propagate
