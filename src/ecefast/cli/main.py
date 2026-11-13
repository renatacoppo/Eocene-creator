"""The ``ecefast`` command: argument parsing only.

Commands (``-c CONFIG``, ``--dry-run``, ``--overwrite`` and ``-l LEVEL`` on every ``run``):

- ``ecefast <period> run [--steps a,b] [--oifs a,b] [--nemo a,b]``: the whole pipeline of a time period
  (``present``, ``eocene``); ``ecefast <period> steps`` lists its steps.
- ``ecefast <component> run [--period present|eocene] [--<component> a,b]``: the steps of one component
  (``oifs``, ``nemo``, ``oasis``, ``rnfm``) in one period, ``present`` by default.

``--oifs`` and ``--nemo`` run only the listed steps of that component's section (``present.oifs.steps``,
``present.nemo.steps``, ``eocene.nemo.steps``) instead of the configured ones.
"""

import argparse
import sys

from ecefast import __version__

PERIODS = {
    "present": "present-day period: OIFS base data and NEMO domain of the model grids (section present)",
    "eocene": "Eocene (DeepMIP) period: modifications of OIFS, NEMO, OASIS and runoff-mapper input (section eocene)",
}
COMPONENTS = {
    "oifs": "OIFS: base data (present), Eocene initial and climate files (eocene)",
    "nemo": "NEMO: domain (present), Eocene domain and NEMO input files (eocene)",
    "oasis": "OASIS: Eocene restart rstos.nc (eocene)",
    "rnfm": "runoff-mapper: Eocene basins (eocene)",
}
# components whose section has steps to select on the command line
STEP_COMPONENTS = ("oifs", "nemo")


def main(argv: list[str] | None = None) -> None:
    """Run ``ecefast <subcommand> [args ...]``.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments without the program name (default: ``sys.argv[1:]``).
    """
    subcommands = {**PERIODS, **COMPONENTS}
    parser = argparse.ArgumentParser(prog="ecefast", description="Build EC-Earth4 input data.")
    parser.add_argument("--version", action="version", version=f"ecefast {__version__}")
    parser.add_argument("subcommand", choices=subcommands, help=", ".join(f"{k}: {v}" for k, v in subcommands.items()))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the subcommand")
    args = parser.parse_args(argv)

    if args.subcommand in PERIODS:
        period_main(args.subcommand, args.args)
    else:
        component_main(args.subcommand, args.args)


def pipeline_module(period: str):
    """The pipeline module of a period (``PIPELINE`` and ``run``)."""
    if period == "present":
        from ecefast.periods.present import pipeline
    else:
        from ecefast.periods.eocene import pipeline
    return pipeline


def comma_list(text: str) -> list[str]:
    """``"a, b,c"`` -> ``["a", "b", "c"]``."""
    return [name.strip() for name in text.split(",") if name.strip()]


def add_run_options(parser: argparse.ArgumentParser, components: tuple[str, ...]) -> None:
    """Options of every ``run``, and ``--<component>`` for the given components."""
    parser.add_argument("-c", "--config", required=True, help="configuration file (schema 2)")
    for component in components:
        parser.add_argument(
            f"--{component}",
            type=comma_list,
            metavar="STEPS",
            help=f"run only these {component} steps (comma-separated), instead of <period>.{component}.steps",
        )
    parser.add_argument("--dry-run", action="store_true", help="check all inputs and show the plan; write nothing")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing outputs (after a warning and a 5 s pause; the Eocene 'stage' removes the whole tree)",
    )
    parser.add_argument("-l", "--loglevel", default="INFO", help="log level (DEBUG, INFO, WARNING, ...)")


def substep_help() -> str:
    """Help text: the steps that ``--oifs`` and ``--nemo`` select."""
    from ecefast.components.nemo.domain.pipeline import STEP_DESCRIPTIONS as NEMO_STEPS
    from ecefast.components.oifs.generator import STEP_DESCRIPTIONS as OIFS_STEPS

    return "\n\n".join(
        [
            format_step_list("--oifs steps (present.oifs.steps)", OIFS_STEPS),
            format_step_list("--nemo steps (present.nemo.steps, eocene.nemo.steps with domain: build)", NEMO_STEPS),
        ]
    )


def period_main(period: str, argv: list[str]) -> None:
    """Run ``ecefast <period> run|steps [args ...]``.

    Exits with code 1, after logging the error, if the configuration is invalid or the pipeline cannot start.

    Parameters
    ----------
    period : str
        ``present`` or ``eocene``.
    argv : list of str
        Arguments after ``ecefast <period>``.
    """
    from ecefast.core.steps import step_summary

    pipeline = pipeline_module(period)
    parser = argparse.ArgumentParser(prog=f"ecefast {period}", description=PERIODS[period])
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser(
        "run",
        help=f"run the {period} pipeline (all steps, or the ones in --steps)",
        epilog=format_step_list(
            "steps, in run order (for --steps)", {s.name: step_summary(s) for s in pipeline.PIPELINE}
        )
        + "\n\n"
        + substep_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_parser.add_argument("--steps", type=comma_list, help="comma-separated step names")
    add_run_options(run_parser, STEP_COMPONENTS)
    commands.add_parser("steps", help="list the steps: what each needs, reads and writes")
    args = parser.parse_args(argv)

    if args.command == "steps":
        print(format_steps(pipeline.PIPELINE))
        return
    substeps = {c: getattr(args, c) for c in STEP_COMPONENTS if getattr(args, c) is not None}
    run(pipeline, args, select=args.steps, substeps=substeps)


def component_main(component: str, argv: list[str]) -> None:
    """Run ``ecefast <component> run [args ...]``: the steps of one component in one period.

    Exits with code 1, after logging the error, if the configuration is invalid or the pipeline cannot start.

    Parameters
    ----------
    component : str
        ``oifs``, ``nemo``, ``oasis`` or ``rnfm``.
    argv : list of str
        Arguments after ``ecefast <component>``.
    """
    parser = argparse.ArgumentParser(prog=f"ecefast {component}", description=COMPONENTS[component])
    commands = parser.add_subparsers(dest="command", required=True)
    own = (component,) if component in STEP_COMPONENTS else ()
    run_parser = commands.add_parser(
        "run",
        help=f"run the {component} steps of one period",
        epilog=substep_help() if own else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_parser.add_argument(
        "--period", choices=PERIODS, default="present", help="time period (section of the config), default present"
    )
    add_run_options(run_parser, own)
    args = parser.parse_args(argv)

    substeps = {component: getattr(args, component)} if own and getattr(args, component) is not None else {}
    run(pipeline_module(args.period), args, component=component, substeps=substeps)


def run(pipeline, args: argparse.Namespace, **options) -> None:
    """Call ``pipeline.run`` with the common options; log a configuration or pipeline error and exit 1."""
    from ecefast.core import ConfigError, setup_logger
    from ecefast.core.steps import PipelineError

    logger = setup_logger(level=args.loglevel)
    try:
        pipeline.run(args.config, dry_run=args.dry_run, overwrite=args.overwrite, **options)
    except (ConfigError, PipelineError) as e:
        logger.error("%s", e)
        sys.exit(1)


def format_step_list(title: str, descriptions: dict[str, str]) -> str:
    """Help text: ``title:`` then one line per step, its name and its description."""
    width = max(len(name) for name in descriptions)
    return "\n".join([f"{title}:", *(f"  {name:<{width}}  {text}" for name, text in descriptions.items())])


def format_steps(steps: list) -> str:
    """One line per step: name, summary, then its component and what it needs, reads and writes (path templates)."""
    from ecefast.core.steps import step_summary

    width = max(len(s.name) for s in steps)
    lines = []
    for step in steps:
        summary = step_summary(step)
        parts = [
            f"component: {step.component or '-'}",
            f"needs: {', '.join(step.needs) or '-'}",
            f"reads: {', '.join(step.reads) or '-'}",
            f"writes: {', '.join(step.writes) or '-'}",
        ]
        lines.append(f"{step.name:<{width}}  {summary}  |  " + "  |  ".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    main()
