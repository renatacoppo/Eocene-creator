"""Atomic file writes.

Every output file is written to a temporary file in the same directory and renamed when complete, so a failed
or interrupted step never leaves a half-written file behind.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def temporary_path(path: str | os.PathLike) -> Path:
    """Temporary file name used by :func:`atomic_write` for ``path``.

    The name is ``<stem>.tmp-<pid><suffix>`` in the same directory: it keeps the suffix, so writers that infer
    the format from the extension (``.nc``, ``.grb``) still work.

    Parameters
    ----------
    path : str or os.PathLike
        Final file.

    Returns
    -------
    Path
        Temporary file next to ``path``.
    """
    path = Path(path)
    return path.with_name(f"{path.stem}.tmp-{os.getpid()}{path.suffix}")


@contextmanager
def atomic_write(path: str | os.PathLike) -> Iterator[str]:
    """Write a file atomically.

    Yields a temporary path in the same directory as ``path``. When the ``with`` block ends without error, the
    temporary file replaces ``path`` (``os.replace``). On an exception the temporary file is removed, ``path`` is
    left as it was and the exception propagates.

    Parameters
    ----------
    path : str or os.PathLike
        Final file. Its directory must exist.

    Yields
    ------
    str
        Temporary path to write to.

    Raises
    ------
    FileNotFoundError
        If the ``with`` block did not create the temporary file.

    Examples
    --------
    >>> with atomic_write("out/rstos.nc") as tmp:
    ...     ds.to_netcdf(tmp)
    """
    tmp = temporary_path(path)
    try:
        yield str(tmp)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if not tmp.exists():
        raise FileNotFoundError(f"atomic_write: nothing was written to the temporary file {tmp} for {path}")
    os.replace(tmp, path)
