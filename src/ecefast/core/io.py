"""Atomic file and directory writes.

Every output file is written to a temporary file in the same directory and renamed when complete, so a failed
or interrupted step never leaves a half-written file behind. A whole output tree is built next to its final place
(:func:`partial_path`) and moved there with :func:`replace_directory` when every step has succeeded.
"""

import os
import shutil
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


def partial_path(directory: str) -> str:
    """Directory where a run builds the tree of ``directory`` before :func:`replace_directory`: a sibling,
    ``<directory>.partial``, on the same filesystem so the final move is a rename.

    Parameters
    ----------
    directory : str
        Final directory.

    Returns
    -------
    str
        The partial directory next to it.
    """
    return directory.rstrip(os.sep) + ".partial"


def replace_directory(source: str, target: str) -> None:
    """Move the directory ``source`` to ``target``, replacing ``target`` if it exists.

    The old ``target`` is first renamed to ``<target>.old``, ``source`` is renamed to ``target``, then the old tree
    is removed. Both renames are on the same filesystem (``source`` is a sibling of ``target``), so ``target`` is
    either the old tree or the new one, never a mix of the two.

    Parameters
    ----------
    source : str
        The new tree, usually :func:`partial_path` of ``target``.
    target : str
        The final directory.
    """
    old = target.rstrip(os.sep) + ".old"
    if os.path.exists(old):  # left by an interrupted earlier swap
        shutil.rmtree(old)
    if os.path.exists(target):
        os.rename(target, old)
    os.rename(source, target)
    if os.path.exists(old):
        shutil.rmtree(old)
