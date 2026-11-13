"""Pipeline steps and the runner.

A step is a class that subclasses :class:`ComponentStep`: it declares its ``name``, its ``component``, the steps it
``needs``, the paths it ``reads`` and ``writes`` (templates expanded by :meth:`ecefast.core.workspace.Context.expand`),
and implements :meth:`~ComponentStep.from_context` and :meth:`~ComponentStep.run`. A pipeline is an ordered list of
step classes, run by :func:`run_pipeline`.
"""

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace import Context

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """The pipeline cannot start, or a step did not write what it declares."""


class ComponentStep:
    """Base class of a pipeline step.

    Subclasses set the class attributes and override :meth:`from_context` and :meth:`run`. The first line of the
    class docstring is shown by the dry run.

    Attributes
    ----------
    name : str
        Short name, used by ``needs`` and to select steps (``oifs``, ``nemo``, ...).
    component : str or None
        The model component it makes files for (``oifs``, ``nemo``, ``oasis``, ``rnfm``), used by
        ``ecefast <component> run``; ``None`` for a step of the whole tree (``stage``).
    needs : list of str
        Names of the steps that must run before this one.
    reads : list of str
        Path templates of the inputs (files or directories). All must exist before the pipeline starts, unless an
        earlier selected step writes them.
    writes : list of str
        Path templates of the outputs. All must exist after :meth:`run`.
    sources : dict of str to str
        Where to get an input of ``reads`` that is not part of the standard input trees, by its path template.
        Shown in the error when that input is missing.
    """

    name: str = ""
    component: str | None = None
    needs: list[str] = []
    reads: list[str] = []
    writes: list[str] = []
    sources: dict[str, str] = {}

    @classmethod
    def from_context(cls, ctx: "Context") -> "ComponentStep":
        """Build the step from the run context (config and paths)."""
        raise NotImplementedError(f"{cls.__name__} does not implement from_context()")

    def run(self) -> None:
        """Do the work: call the ``create_*`` methods."""
        raise NotImplementedError(f"{type(self).__name__} does not implement run()")

    def dry_run(self) -> None:
        """Log what :meth:`run` would do beyond the declared ``writes`` (default: nothing)."""

    def planned_writes(self) -> list[str]:
        """Paths this step writes beyond the class-level ``writes``, because they depend on the configuration
        (e.g. the final and intermediate files of a component pipeline). Listed in the recap of the run.

        Returns
        -------
        list of str
            Absolute paths; empty by default.
        """
        return []


def step_summary(step: type[ComponentStep]) -> str:
    """First line of the step docstring (shown by the dry run and ``ecefast eocene steps``)."""
    doc = step.__doc__ or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _covered(path: str, written: list[str]) -> bool:
    """``path`` is one of ``written`` or lies inside one of them."""
    return any(path == w or path.startswith(w.rstrip(os.sep) + os.sep) for w in written)


def _check_order(steps: list[type[ComponentStep]]) -> None:
    """Every step comes after the steps it needs."""
    seen: list[str] = []
    all_names = [s.name for s in steps]
    for step in steps:
        for need in step.needs:
            if need not in all_names:
                raise PipelineError(f"Step '{step.name}' needs '{need}', which is not in the pipeline")
            if need not in seen:
                raise PipelineError(f"Step '{step.name}' needs '{need}', which must come before it in the pipeline")
        seen.append(step.name)


def _select(steps: list[type[ComponentStep]], select: list[str] | None) -> list[type[ComponentStep]]:
    """The steps to run, in pipeline order."""
    if select is None:
        return list(steps)
    names = [s.name for s in steps]
    unknown = [n for n in select if n not in names]
    if unknown:
        raise PipelineError(f"Unknown step(s): {', '.join(unknown)} (known: {', '.join(names)})")
    return [s for s in steps if s.name in select]


def _check_unselected_needs(steps: list[type[ComponentStep]], selected: list[type[ComponentStep]], ctx) -> None:
    """A needed step that is not selected must have run before: all its ``writes`` exist."""
    by_name = {s.name: s for s in steps}
    selected_names = {s.name for s in selected}
    for step in selected:
        for need in step.needs:
            if need in selected_names:
                continue
            missing = [p for p in (ctx.expand(t) for t in by_name[need].writes) if not os.path.exists(p)]
            if missing:
                raise PipelineError(
                    f"Step '{step.name}' needs '{need}', which is not selected and has not run before "
                    f"(missing: {', '.join(missing)}). Select '{need}' too."
                )


def _preflight(selected: list[type[ComponentStep]], ctx) -> None:
    """Check every write path is allowed and every read path exists; fail once listing all problems."""
    for step in selected:
        for template in step.writes:
            ctx.check_writable(ctx.expand(template), step.name)

    missing: list[tuple[str, str]] = []
    sources: dict[str, str] = {}
    written: list[str] = []
    for step in selected:
        for template in step.reads:
            path = ctx.expand(template)
            if not os.path.exists(path) and not _covered(path, written):
                missing.append((step.name, path))
                if template in step.sources:
                    sources[path] = step.sources[template]
        written.extend(ctx.expand(t) for t in step.writes)
    if missing:
        raise PipelineError(missing_inputs_message(missing, sources))


def missing_inputs_message(missing: list[tuple[str, str]], sources: dict[str, str] | None = None) -> str:
    """Error message listing missing inputs, one line per ``(step name, path)``.

    Parameters
    ----------
    missing : list of (str, str)
        Step name and missing path.
    sources : dict of str to str, optional
        Where to get a missing path, by path; shown on the line below it.
    """
    sources = sources or {}
    n = len(missing)
    width = max(len(name) for name, _ in missing)
    lines = [f"Cannot start: {n} input file{'s are' if n > 1 else ' is'} missing. Nothing was written."]
    for name, path in missing:
        lines.append(f"  {name:<{width}}  needs  {path}")
        if path in sources:
            lines.append(f"  {'':<{width}}  get it from {sources[path]}")
    return "\n".join(lines)


def run_pipeline(
    steps: list[type[ComponentStep]],
    ctx: "Context",
    select: list[str] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Check and run a pipeline.

    Before anything runs: the ``needs`` order is checked, needed steps that are not selected must have run
    before (their ``writes`` exist), every ``writes`` path must be writable (not inside ``input`` or
    ``herold``) and every ``reads`` path must exist or be written by an earlier selected step. All missing reads
    are reported in one error. Then every selected step is built with ``from_context``, which checks what a
    class-level ``reads`` list cannot (inputs that depend on the configuration or the backend), also in a dry run.
    Then the selected steps run in order, and after each one its ``writes`` must exist.

    Parameters
    ----------
    steps : list of ComponentStep subclasses
        The pipeline, in order.
    ctx : Context
        Run context: config and path expansion.
    select : list of str, optional
        Names of the steps to run. ``None`` runs all of them.
    dry_run : bool
        Only check and log the plan; write nothing.

    Returns
    -------
    list of str
        Names of the steps that ran (or would run, for a dry run).

    Raises
    ------
    PipelineError
        If a check fails before the start, or a step did not write a declared output.
    """
    _check_order(steps)
    selected = _select(steps, select)
    _check_unselected_needs(steps, selected, ctx)
    _preflight(selected, ctx)
    instances = [step.from_context(ctx) for step in selected]

    names = [s.name for s in selected]
    if dry_run:
        width = max((len(n) for n in names), default=0)
        logger.info("Dry run: nothing is written. Plan:")
        for step in selected:
            logger.info("  %-*s  %s", width, step.name, step_summary(step))
            for template in step.writes:
                logger.debug("      → %s", ctx.expand(template))
        for instance in instances:
            instance.dry_run()
        logger.info("%s", files_recap(selected, instances, ctx, dry_run=True))
        return names

    for step, instance in zip(selected, instances):
        logger.info("Step %s: %s", step.name, step_summary(step))
        instance.run()
        missing = [p for p in (ctx.expand(t) for t in step.writes) if not os.path.exists(p)]
        if missing:
            raise PipelineError(f"Step '{step.name}' did not write: {', '.join(missing)}")
    logger.info("%s", files_recap(selected, instances, ctx, dry_run=False))
    return names


def files_recap(
    selected: list[type[ComponentStep]], instances: list[ComponentStep], ctx: "Context", dry_run: bool
) -> str:
    """Text listing every file the selected steps write, grouped by the period's ``output``, ``machine.tmpdir``
    and other places, with paths relative to their group.

    In a dry run, files that exist already are marked ``(exists)``; after a run, files that are not there are
    marked ``(not found)``.

    Parameters
    ----------
    selected : list of ComponentStep subclasses
        The steps that ran (or would run).
    instances : list of ComponentStep
        Their instances, in the same order: :meth:`ComponentStep.planned_writes` adds the configuration-dependent
        paths to the class-level ``writes``.
    ctx : Context
        Run context: path expansion, the period's output and the tmpdir.
    dry_run : bool
        Phrase it as files that would be written.

    Returns
    -------
    str
        The recap, one file per line.
    """
    paths = []
    for step, instance in zip(selected, instances):
        for path in [ctx.expand(t) for t in step.writes] + instance.planned_writes():
            if path not in paths:
                paths.append(path)
    groups = {
        f"{ctx.period}.output ({ctx.section.output})": ctx.section.output,
        f"machine.tmpdir ({ctx.config.machine.tmpdir})": ctx.config.machine.tmpdir,
    }
    lines = {label: [] for label in [*groups, "elsewhere"]}
    for path in paths:
        if dry_run:
            mark = "  (exists)" if os.path.exists(path) else ""
        else:
            mark = "" if os.path.exists(path) else "  (not found)"
        label = next((label for label, root in groups.items() if _covered(path, [root])), "elsewhere")
        shown = path if label == "elsewhere" else os.path.relpath(path, groups[label])
        lines[label].append(f"    {shown}{mark}")

    title = "Files that would be written" if dry_run else "Files written"
    text = [f"{title} ({len(paths)}):"]
    for label, entries in lines.items():
        if entries:
            text += [f"  in {label}:" if label != "elsewhere" else "  elsewhere:", *entries]
    return "\n".join(text)
