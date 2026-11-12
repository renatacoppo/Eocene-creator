"""Unit tests for the ``ecefast`` logger setup."""

import logging

import pytest

from ecefast.core.logger import setup_logger

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_logger():
    """Remove the handlers of the ``ecefast`` logger before and after the test."""
    logger = logging.getLogger("ecefast")
    saved = logger.handlers[:], logger.level, logger.propagate
    logger.handlers.clear()
    yield
    logger.handlers[:], logger.level, logger.propagate = saved


def test_setup_logger_returns_ecefast_logger_with_level(clean_logger) -> None:
    logger = setup_logger("debug")
    assert logger.name == "ecefast"
    assert logger.level == logging.DEBUG
    assert logging.getLogger("ecefast.paleo.eocene.oifs.fields").getEffectiveLevel() == logging.DEBUG


def test_setup_logger_twice_keeps_one_handler(clean_logger) -> None:
    setup_logger("INFO")
    logger = setup_logger("WARNING")
    assert len(logger.handlers) == 1
    assert logger.level == logging.WARNING


def test_setup_logger_default_is_warning(clean_logger) -> None:
    assert setup_logger().level == logging.WARNING
