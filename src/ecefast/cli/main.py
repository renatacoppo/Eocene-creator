"""The ``ecefast`` command: argument parsing only.

Commands: ``ecefast eocene run -c CONFIG [--steps a,b] [--dry-run] [--overwrite] [-l LEVEL]``,
``ecefast eocene steps`` and ``ecefast nemo domain -c CONFIG [--bathymetry NAME ...] [-l LEVEL]``.
"""

import argparse
import sys

from ecefast import __version__

SUBCOMMANDS = {
    "eocene": "Eocene (DeepMIP) modifications of OIFS, NEMO, OASIS and runoff-mapper input",
    "nemo": "NEMO tools: the domain pipeline (coordinates, bathymetries, DOMAINcfg, masks)",
}


def main(argv: list[str] | None = None) -> None:
    """Run ``ecefast <subcommand> [args ...]``.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments without the program name (default: ``sys.argv[1:]``).
    """
    parser = argparse.ArgumentParser(prog="ecefast", description="Build EC-Earth4 input data.")
    parser.add_argument("--version", action="version", version=f"ecefast {__version__}")
    parser.add_argument("subcommand", choices=SUBCOMMANDS, help=", ".join(f"{k}: {v}" for k, v in SUBCOMMANDS.items()))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the subcommand")
    args = parser.parse_args(argv)

    if args.subcommand == "eocene":
        eocene_main(args.args)
    else:
        nemo_main(args.args)


def eocene_main(argv: list[str]) -> None:
    """Run ``ecefast eocene run|steps [args ...]``.

    Exits with code 1, after logging the error, if the configuration is invalid or the pipeline cannot start.

    Parameters
    ----------
    argv : list of str
        Arguments after ``ecefast eocene``.
    """
    parser = argparse.ArgumentParser(prog="ecefast eocene", description=SUBCOMMANDS["eocene"])
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="run the Eocene pipeline (all steps, or the ones in --steps)")
    run_parser.add_argument("-c", "--config", required=True, help="configuration file (schema 1)")
    run_parser.add_argument(
        "--steps", type=lambda s: [n.strip() for n in s.split(",") if n.strip()], help="comma-separated step names"
    )
    run_parser.add_argument("--dry-run", action="store_true", help="check all inputs and show the plan; write nothing")
    run_parser.add_argument(
        "--overwrite", action="store_true", help="let 'stage' replace an output directory that is not empty"
    )
    run_parser.add_argument("-l", "--loglevel", default="INFO", help="log level (DEBUG, INFO, WARNING, ...)")

    commands.add_parser("steps", help="list the steps: what each needs, reads and writes")

    args = parser.parse_args(argv)

    from ecefast.core import ConfigError, setup_logger
    from ecefast.core.steps import PipelineError
    from ecefast.paleo.eocene.pipeline import PIPELINE, run

    if args.command == "steps":
        print(format_steps(PIPELINE))
        return

    logger = setup_logger(level=args.loglevel)
    try:
        run(args.config, select=args.steps, dry_run=args.dry_run, overwrite=args.overwrite)
    except (ConfigError, PipelineError) as e:
        logger.error("%s", e)
        sys.exit(1)


def nemo_main(argv: list[str]) -> None:
    """Run ``ecefast nemo domain [args ...]``.

    The domain pipeline gets the generic bathymetry processors merged with the Eocene ones. Exits with code 1,
    after logging the error, if the configuration is invalid.

    Parameters
    ----------
    argv : list of str
        Arguments after ``ecefast nemo``.
    """
    parser = argparse.ArgumentParser(prog="ecefast nemo", description=SUBCOMMANDS["nemo"])
    commands = parser.add_subparsers(dest="command", required=True)

    domain_parser = commands.add_parser("domain", help="run the NEMO domain pipeline (section nemo_domain)")
    domain_parser.add_argument("-c", "--config", required=True, help="configuration file with a 'nemo_domain' section")
    domain_parser.add_argument(
        "--bathymetry", nargs="+", metavar="NAME", help="run only these bathymetries (default: all enabled ones)"
    )
    domain_parser.add_argument("-l", "--loglevel", default="INFO", help="log level (DEBUG, INFO, WARNING, ...)")

    args = parser.parse_args(argv)

    from ecefast.components.nemo.bathymetry import PROCESSORS
    from ecefast.components.nemo.domain.pipeline import run
    from ecefast.core import ConfigError, setup_logger
    from ecefast.paleo.eocene.bathymetry import EOCENE_PROCESSORS

    logger = setup_logger(level=args.loglevel)
    try:
        run(args.config, {**PROCESSORS, **EOCENE_PROCESSORS}, only=args.bathymetry, log_level=args.loglevel)
    except ConfigError as e:
        logger.error("%s", e)
        sys.exit(1)


def format_steps(steps: list) -> str:
    """One line per step: name, summary, then what it needs, reads and writes (path templates)."""
    from ecefast.core.steps import step_summary

    width = max(len(s.name) for s in steps)
    lines = []
    for step in steps:
        summary = step_summary(step)
        parts = [f"needs: {', '.join(step.needs) or '-'}", f"reads: {', '.join(step.reads) or '-'}"]
        parts.append(f"writes: {', '.join(step.writes) or '-'}")
        lines.append(f"{step.name:<{width}}  {summary}  |  " + "  |  ".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    main()
