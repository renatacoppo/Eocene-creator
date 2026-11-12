"""The ``ecefast`` command: dispatches to the workflow entry points.

Argument parsing only. Each subcommand passes the rest of the command line to its own ``main``::

    ecefast eocene -c configs/eocene.yml --run all --copy
    ecefast nemo-domain --config nemo_workflow.yaml
"""

import argparse

from ecefast import __version__

SUBCOMMANDS = {
    "eocene": "Eocene (DeepMIP) modifications of OIFS, NEMO, OASIS and runoff-mapper input",
    "nemo-domain": "NEMO domain pipeline (coordinates, bathymetries, DOMAINcfg namelists)",
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
        from ecefast.cli.eocene import main as subcommand_main
    else:
        from ecefast.components.nemo.domain.pipeline import main as subcommand_main
    subcommand_main(args.args)


if __name__ == "__main__":
    main()
