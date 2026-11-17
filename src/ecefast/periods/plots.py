"""``ecefast <period> plot``: maps of the main output of a period, compared with a reference tree.

The test tree is the period's ``output``; the reference is another EC-Earth tree, by default the period's
``input`` (the present-day tree), or any tree given on the command line (e.g. another run). Both periods draw the
same groups; each period chooses which domains of the reference tree, and which bathymetry source, its NEMO domain
is compared with (:func:`ecefast.periods.eocene.pipeline.plot`, :func:`ecefast.periods.present.pipeline.plot`).

Groups, each in its own folder of the plot directory:

- ``nemo``: the depth, basins, one-cell passages, inlets (dead-end channels one cell wide) and cells at the
  minimum depth of the NEMO domain; its land-sea mask compared with the
  reference domains (on the same grid: the cells that change and the depth difference; on another grid: its ocean
  mask remapped conservatively onto the domain's cells) and with the source of its bathymetry (remapped the same
  way); the same domain map of every reference domain; the geothermal heat flux and the tidal mixing
  forcing (``nemo/initial``) that differ from the reference.
- ``oifs``: the OIFS surface files (initial state and climate files) that differ from the reference.
- ``coupling``: the OIFS land-sea mask against the NEMO ocean mask of the test tree, on the NEMO grid: the OIFS
  mask (land where ``lsm > 0.5``) is remapped conservatively onto the NEMO cells, and a cell counts as OIFS land
  when OIFS land points cover more than half of it. The same map is drawn for the coupled configurations of the
  reference tree (``REFERENCE_COUPLINGS`` and the grids of the configuration), as a measure of the mismatch of an
  existing setup.

The test tree is named in every title and legend with the data version it was made with (``eocene v1``), read
from its ``provenance.yml``, and ``summary.yml`` records it (``unknown`` for a tree without one). ``summary.yml`` holds the numbers (ocean cells, basins, one-cell passages, cells per mask class, the OIFS
variables that differ), so two runs can be compared without opening every figure. Plots are diagnostics: they
are written outside the EC-Earth trees, never into an ``input`` or ``output``.
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime

import numpy as np
import yaml

from ecefast import __version__
from ecefast.components.nemo.bathymetry import BathymetryProcessor
from ecefast.components.nemo.plots import (
    compare_forcing,
    domain_classes,
    domain_summary,
    forcing_files,
    fill_empty_cells,
    ocean_on,
    plot_agreement,
    plot_domain,
    plot_same_grid,
    read_domain,
    write_cell_bounds,
    write_source_ocean,
)
from ecefast.components.oifs.plots import compare_oifs, land_fraction_on, oifs_files
from ecefast.core.io import atomic_write
from ecefast.core.layout import oifs_initial_dir
from ecefast.core.plotting import save_figure
from ecefast.core.provenance import PROVENANCE_FILE, read_data_version
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)

GROUPS = ("nemo", "oifs", "coupling")
SUMMARY_FILE = "summary.yml"
# coupled configurations of EC-Earth4 (OIFS grid, NEMO grid; folders oasis/TL63-ORCA2 and oasis/TL255-eORCA1 of
# ECE4-DATA): the mismatch of their masks is drawn for comparison when the reference tree holds them
REFERENCE_COUPLINGS = (("TL63L31", "ORCA2"), ("TL255L91", "eORCA1"))
# share of a NEMO cell that OIFS land points must cover for the cell to count as OIFS land in the coupling maps:
# more than half, the rule that makes the NEMO land-sea mask of a bathymetry (remapcon fraction against 0.5)
LAND_COVER_THRESHOLD = 0.5


def domain_file(tree: str, grid: str) -> str:
    """The ``domain_cfg.nc`` of the NEMO grid ``grid`` in an EC-Earth tree."""
    return os.path.join(tree, "nemo", "domain", grid, "domain_cfg.nc")


def check_plot_dir(ctx: Context, out_dir: str) -> None:
    """Refuse a plot directory inside a read-only tree or inside the output tree of a period.

    Raises
    ------
    PipelineError
        If ``out_dir`` lies inside an ``input``, ``eocene.herold`` or an ``output`` of the configuration.
    """
    ctx.check_writable(out_dir, "plot")
    real = os.path.realpath(out_dir)
    for period in ("present", "eocene"):
        section = getattr(ctx.config, period)
        if section is None:
            continue
        root = os.path.realpath(section.output)
        if real == root or real.startswith(root + os.sep):
            raise PipelineError(
                f"Plot directory {out_dir} lies inside '{period}.output' {root}: keep plots out of the EC-Earth trees"
            )


def clear_plot_dir(out_dir: str) -> None:
    """Erase the plot directory of an earlier run, so no figure of that run is left among the new ones.

    Only a directory that holds a ``summary.yml`` (written by every plot run) is erased; an empty or missing
    directory is left as it is.

    Raises
    ------
    PipelineError
        If ``out_dir`` holds files but no ``summary.yml``: it is not a plot directory, and nothing is erased.
    """
    if not os.path.isdir(out_dir) or not os.listdir(out_dir):
        return
    if not os.path.isfile(os.path.join(out_dir, SUMMARY_FILE)):
        raise PipelineError(
            f"Plot directory {out_dir} is not empty and holds no {SUMMARY_FILE}: it is not a plot directory of "
            "ecefast and is not erased. Choose another directory, or empty it yourself."
        )
    logger.info("Erasing the plots of an earlier run in %s", out_dir)
    shutil.rmtree(out_dir)


def plot_period(
    ctx: Context,
    out_dir: str,
    reference: str,
    reference_domains: list[str],
    source: tuple[type[BathymetryProcessor], str] | None = None,
    groups: list[str] | None = None,
) -> dict:
    """Draw the plots of a period and write ``summary.yml`` into ``out_dir``.

    Every input file is checked before anything is erased or drawn.

    Parameters
    ----------
    ctx : Context
        The configuration and the period; the test tree is the period's ``output``.
    out_dir : str
        Plot directory, created if needed; the plots of an earlier run are erased first (:func:`clear_plot_dir`).
    reference : str
        Root of the reference tree.
    reference_domains : list of str
        ``domain_cfg.nc`` files the NEMO domain is compared with; the one in a folder named like
        ``grids.nemo.name`` is compared cell by cell.
    source : tuple, optional
        The bathymetry processor of the period and its source file: the NEMO mask is compared with it.
    groups : list of str, optional
        Groups to draw (``GROUPS``); ``None`` draws all of them.

    Returns
    -------
    dict
        The content of ``summary.yml``.

    Raises
    ------
    PipelineError
        If a group is unknown, the plot directory is inside an EC-Earth tree or holds files that are not plots, or
        an input file is missing.
    """
    groups = list(GROUPS) if groups is None else groups
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        raise PipelineError(f"Unknown plot group(s): {', '.join(unknown)} (known: {', '.join(GROUPS)})")
    check_plot_dir(ctx, out_dir)
    if "nemo" in groups and not reference_domains:
        raise PipelineError(f"plot: no NEMO domain to compare with in the reference tree {reference}/nemo/domain")

    config, test = ctx.config, ctx.section.output
    grid = config.grids.nemo.name
    oifs = config.grids.oifs
    test_domain = domain_file(test, grid)
    test_oifs = oifs_files(test, oifs.name, oifs.startdate, oifs.climate_version)
    reference_oifs = oifs_files(reference, oifs.name, oifs.startdate, oifs.climate_version)
    needed = {
        "nemo": [test_domain, *reference_domains]
        + ([source[1]] if source else [])
        + [*forcing_files(test).values(), *forcing_files(reference).values()],
        "oifs": [*test_oifs.values(), *reference_oifs.values()],
        "coupling": [test_domain, test_oifs["ICMGGECE4INIT"]],
    }
    missing = sorted({path for group in groups for path in needed[group] if not os.path.isfile(path)})
    if missing:
        raise PipelineError(
            f"plot: {len(missing)} input file(s) missing: {', '.join(missing)}. Check {ctx.period}.output and the "
            "reference tree (--reference), or leave out the group that needs them (--only)."
        )

    clear_plot_dir(out_dir)
    # the test tree is named with the data version it was made with, in every title and legend
    data_version = read_data_version(test)
    if data_version is None:
        logger.warning("Plots: no data version in %s, the plots do not name it", os.path.join(test, PROVENANCE_FILE))
    test_label = f"{ctx.period} {data_version}" if data_version else ctx.period
    labels = ("reference", test_label)
    summary: dict = {
        "period": ctx.period,
        "data_version": data_version or "unknown",
        "test": test,
        "reference": reference,
        "ecefast": __version__,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    domain = read_domain(test_domain, f"{test_label} {grid}") if {"nemo", "coupling"} & set(groups) else None
    if "nemo" in groups:
        summary["nemo"] = plot_nemo(domain, os.path.join(out_dir, "nemo"), reference_domains, grid, source)
        summary["nemo"]["forcing"] = compare_forcing(
            forcing_files(reference), forcing_files(test), os.path.join(out_dir, "nemo", "forcing"), labels
        )
    if "coupling" in groups:
        coupling_dir = os.path.join(out_dir, "coupling")
        summary["coupling"] = plot_coupling(
            domain, test_oifs["ICMGGECE4INIT"], oifs.name, os.path.join(coupling_dir, "oifs_lsm_vs_nemo.png")
        )
        pairs = dict.fromkeys([(oifs.name, grid), *REFERENCE_COUPLINGS])
        summary["coupling"]["reference"] = plot_reference_couplings(reference, pairs, oifs.startdate, coupling_dir)
    if "oifs" in groups:
        summary["oifs"] = compare_oifs(reference_oifs, test_oifs, os.path.join(out_dir, "oifs"), labels)

    os.makedirs(out_dir, exist_ok=True)
    with atomic_write(os.path.join(out_dir, SUMMARY_FILE)) as tmp, open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(summary, f, sort_keys=False)
    logger.info("Plots written to %s (numbers in %s)", out_dir, SUMMARY_FILE)
    return summary


def plot_nemo(domain, out_dir: str, reference_domains: list[str], grid: str, source) -> dict:
    """The ``nemo`` group: map of the test domain and of each reference domain, comparison with each reference
    domain and with the source. Masks on another grid are remapped conservatively onto the cells of the domain."""
    classes, basins, inlets = domain_classes(domain)
    save_figure(plot_domain(domain, classes), os.path.join(out_dir, "domain.png"))
    result = domain_summary(domain, basins, inlets, classes)
    logger.info(
        "Plots: %s, %d ocean cells, %d basins, %d one-cell passages, %d inlets (%d cells)",
        domain.label,
        result["ocean_cells"],
        result["basins"],
        result["one_cell_passages"],
        result["inlets"],
        result["inlet_cells"],
    )
    comparisons, references = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        cells = os.path.join(tmp, "cells.nc")
        write_cell_bounds(domain.path, cells)
        for path in reference_domains:
            other_grid = os.path.basename(os.path.dirname(path))
            other = read_domain(path, f"reference {other_grid}")
            other_classes, other_basins, other_inlets = domain_classes(other)
            save_figure(plot_domain(other, other_classes), os.path.join(out_dir, f"domain_reference_{other_grid}.png"))
            references[other_grid] = domain_summary(other, other_basins, other_inlets, other_classes)
            if other_grid == grid:
                fig, counts = plot_same_grid(domain, other)
            else:
                other_cells = os.path.join(tmp, f"{other_grid}.nc")
                write_cell_bounds(path, other_cells, other.ocean)
                remapped = ocean_on(domain, other_cells, cells)
                title = f"{domain.label} vs {other.label} (conservative)"
                fig, counts = plot_agreement(domain, remapped, other.label, title)
            save_figure(fig, os.path.join(out_dir, f"vs_reference_{other_grid}.png"))
            comparisons[other.label] = {"domain": path} | counts
        if source is not None:
            processor, path = source
            source_file = os.path.join(tmp, "source.nc")
            write_source_ocean(processor, path, source_file)
            title = f"{domain.label} vs bathymetry source {os.path.basename(path)} (conservative)"
            fig, counts = plot_agreement(domain, ocean_on(domain, source_file, cells), "source", title)
            save_figure(fig, os.path.join(out_dir, "vs_source.png"))
            comparisons["bathymetry source"] = {"file": path} | counts
    result["reference_domains"] = references
    result["comparisons"] = comparisons
    return result


def plot_coupling(domain, icmgg: str, oifs_grid: str, path: str) -> dict:
    """Map of the OIFS land-sea mask against the ocean mask of a NEMO domain, on the NEMO grid.

    The OIFS mask (land where ``lsm > 0.5``) is remapped conservatively onto the NEMO cells
    (:func:`ecefast.components.oifs.plots.land_fraction_on`); a cell is OIFS land when OIFS land points cover more
    than ``LAND_COVER_THRESHOLD`` of it.

    Parameters
    ----------
    domain : Domain
        The NEMO domain.
    icmgg : str
        The ``ICMGGECE4INIT`` with the land-sea mask.
    oifs_grid : str
        Name of the OIFS grid, e.g. ``TL63L31``.
    path : str
        PNG file to write.

    Returns
    -------
    dict
        The number of cells of each class (``test`` is NEMO, ``other`` is OIFS) and ``mismatch_percent``, the
        share of the NEMO cells that are ocean in only one of the two models.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bounds = os.path.join(tmp, "nemo_cells.nc")
        write_cell_bounds(domain.path, bounds)
        land = land_fraction_on(icmgg, oifs_grid, bounds, tmp)
    oifs_ocean = fill_empty_cells(domain, land) <= LAND_COVER_THRESHOLD
    title = f"{domain.label}: NEMO ocean vs OIFS {oifs_grid} land-sea mask"
    fig, counts = plot_agreement(domain, oifs_ocean, "OIFS", title)
    save_figure(fig, path)
    mismatch = counts["ocean_only_in_test"] + counts["ocean_only_in_other"]
    counts["mismatch_percent"] = round(100 * mismatch / domain.ocean.size, 2)
    logger.info(
        "Plots: coupling %s with OIFS %s, %d cells ocean only in NEMO, %d only in OIFS (%.2f%% of the cells)",
        domain.label,
        oifs_grid,
        counts["ocean_only_in_test"],
        counts["ocean_only_in_other"],
        counts["mismatch_percent"],
    )
    return counts


def plot_reference_couplings(reference: str, pairs, startdate: str, out_dir: str) -> dict:
    """The coupling map of each coupled configuration that the reference tree holds.

    A configuration without its ``domain_cfg.nc`` or ``ICMGGECE4INIT`` in the reference tree is left out, with a
    log message: a tree staged for one resolution holds only some of them.

    Parameters
    ----------
    reference : str
        Root of the reference tree.
    pairs : iterable of tuple
        ``(OIFS grid, NEMO grid)`` of each configuration.
    startdate : str
        Initial-state date of the OIFS grids (``grids.oifs.startdate``).
    out_dir : str
        Folder of the figures ``reference_<OIFS grid>-<NEMO grid>.png``.

    Returns
    -------
    dict
        ``{"<OIFS grid>-<NEMO grid>": {"domain": ..., "icmgg": ..., counts}}`` (see :func:`plot_coupling`).
    """
    result = {}
    for oifs_grid, nemo_grid in pairs:
        name = f"{oifs_grid}-{nemo_grid}"
        files = {
            "domain": domain_file(reference, nemo_grid),
            "icmgg": os.path.join(oifs_initial_dir(reference, oifs_grid, startdate), "ICMGGECE4INIT"),
        }
        missing = [path for path in files.values() if not os.path.isfile(path)]
        if missing:
            logger.info("Plots: no reference coupling %s, not in the reference tree: %s", name, ", ".join(missing))
            continue
        domain = read_domain(files["domain"], f"reference {nemo_grid}")
        counts = plot_coupling(domain, files["icmgg"], oifs_grid, os.path.join(out_dir, f"reference_{name}.png"))
        result[name] = files | counts
    return result
