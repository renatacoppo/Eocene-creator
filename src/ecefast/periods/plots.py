"""``ecefast <period> plot``: maps of the main output of a period, compared with a reference tree.

The test tree is the period's ``output``; the reference is another EC-Earth tree, by default the period's
``input`` (the present-day tree), or any tree given on the command line (e.g. another run). Both periods draw the
same groups; each period chooses which domains of the reference tree, and which bathymetry source, its NEMO domain
is compared with (:func:`ecefast.periods.eocene.pipeline.plot`, :func:`ecefast.periods.present.pipeline.plot`).

Groups, each in its own folder of the plot directory:

- ``nemo``: the depth, basins and one-cell passages of the NEMO domain; its land-sea mask compared with the
  reference domains (on the same grid: the cells that change and the depth difference; on another grid: sampled
  at the domain's cells) and with the source of its bathymetry.
- ``oifs``: the OIFS surface files (initial state and climate files) that differ from the reference.
- ``coupling``: the OIFS land-sea mask against the NEMO ocean mask of the test tree.

``summary.yml`` holds the numbers (ocean cells, basins, one-cell passages, cells per mask class, the OIFS
variables that differ), so two runs can be compared without opening every figure. Plots are diagnostics: they
are written outside the EC-Earth trees, never into an ``input`` or ``output``.
"""

import logging
import os
from datetime import datetime

import numpy as np
import yaml

from ecefast import __version__
from ecefast.components.nemo.bathymetry import BathymetryProcessor
from ecefast.components.nemo.plots import (
    domain_classes,
    domain_summary,
    ocean_at,
    plot_agreement,
    plot_domain,
    plot_same_grid,
    read_domain,
    source_ocean,
)
from ecefast.components.oifs.plots import LAND_THRESHOLD, compare_oifs, oifs_files, read_land
from ecefast.core.io import atomic_write
from ecefast.core.plotting import save_figure
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)

GROUPS = ("nemo", "oifs", "coupling")
SUMMARY_FILE = "summary.yml"


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


def plot_period(
    ctx: Context,
    out_dir: str,
    reference: str,
    reference_domains: list[str],
    source: tuple[type[BathymetryProcessor], str] | None = None,
    groups: list[str] | None = None,
) -> dict:
    """Draw the plots of a period and write ``summary.yml`` into ``out_dir``.

    Every input file is checked before anything is drawn.

    Parameters
    ----------
    ctx : Context
        The configuration and the period; the test tree is the period's ``output``.
    out_dir : str
        Plot directory, created if needed; files of an earlier plot run are replaced.
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
        If a group is unknown, the plot directory is inside an EC-Earth tree, or an input file is missing.
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
        "nemo": [test_domain, *reference_domains] + ([source[1]] if source else []),
        "oifs": [*test_oifs.values(), *reference_oifs.values()],
        "coupling": [test_domain, test_oifs["ICMGGECE4INIT"]],
    }
    missing = sorted({path for group in groups for path in needed[group] if not os.path.isfile(path)})
    if missing:
        raise PipelineError(
            f"plot: {len(missing)} input file(s) missing: {', '.join(missing)}. Check {ctx.period}.output and the "
            "reference tree (--reference), or leave out the group that needs them (--only)."
        )

    labels = ("reference", ctx.period)
    summary: dict = {
        "period": ctx.period,
        "test": test,
        "reference": reference,
        "ecefast": __version__,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    domain = read_domain(test_domain, f"{ctx.period} {grid}") if {"nemo", "coupling"} & set(groups) else None
    if "nemo" in groups:
        summary["nemo"] = plot_nemo(domain, os.path.join(out_dir, "nemo"), reference_domains, grid, source)
    if "coupling" in groups:
        summary["coupling"] = plot_coupling(domain, test_oifs["ICMGGECE4INIT"], os.path.join(out_dir, "coupling"))
    if "oifs" in groups:
        summary["oifs"] = compare_oifs(reference_oifs, test_oifs, os.path.join(out_dir, "oifs"), labels)

    os.makedirs(out_dir, exist_ok=True)
    with atomic_write(os.path.join(out_dir, SUMMARY_FILE)) as tmp, open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(summary, f, sort_keys=False)
    logger.info("Plots written to %s (numbers in %s)", out_dir, SUMMARY_FILE)
    return summary


def plot_nemo(domain, out_dir: str, reference_domains: list[str], grid: str, source) -> dict:
    """The ``nemo`` group: map of the test domain, comparison with each reference domain and with the source."""
    classes, basins = domain_classes(domain)
    save_figure(plot_domain(domain, classes), os.path.join(out_dir, "domain.png"))
    result = domain_summary(domain, basins, classes)
    logger.info(
        "Plots: %s, %d ocean cells, %d basins, %d one-cell passages",
        domain.label,
        result["ocean_cells"],
        result["basins"],
        result["one_cell_passages"],
    )
    comparisons = {}
    for path in reference_domains:
        other_grid = os.path.basename(os.path.dirname(path))
        other = read_domain(path, f"reference {other_grid}")
        if other_grid == grid:
            fig, counts = plot_same_grid(domain, other)
        else:
            sampled = ocean_at(domain, other.lon, other.lat, other.ocean)
            fig, counts = plot_agreement(domain, sampled, other.label, f"{domain.label} vs {other.label} (nearest)")
        save_figure(fig, os.path.join(out_dir, f"vs_reference_{other_grid}.png"))
        comparisons[other.label] = {"domain": path} | counts
    if source is not None:
        processor, path = source
        sampled = ocean_at(domain, *source_ocean(processor, path))
        title = f"{domain.label} vs bathymetry source {os.path.basename(path)} (nearest)"
        fig, counts = plot_agreement(domain, sampled, "source", title)
        save_figure(fig, os.path.join(out_dir, "vs_source.png"))
        comparisons["bathymetry source"] = {"file": path} | counts
    result["comparisons"] = comparisons
    return result


def plot_coupling(domain, icmgg: str, out_dir: str) -> dict:
    """The ``coupling`` group: the OIFS land-sea mask (land where ``lsm > 0.5``) against the NEMO ocean mask."""
    land = read_land(icmgg)
    lon, lat = np.meshgrid(land["lon"].values, land["lat"].values)
    oifs_ocean = ocean_at(domain, lon, lat, land.values <= LAND_THRESHOLD)
    fig, counts = plot_agreement(domain, oifs_ocean, "OIFS", f"{domain.label}: NEMO ocean vs OIFS land-sea mask")
    save_figure(fig, os.path.join(out_dir, "oifs_lsm_vs_nemo.png"))
    logger.info(
        "Plots: coupling, %d cells ocean only in NEMO, %d only in OIFS",
        counts["ocean_only_in_test"],
        counts["ocean_only_in_other"],
    )
    return counts
