"""Read and validate the ``ecefast`` configuration file (schema 1).

One YAML file per machine holds everything: paths, tools, grids, the NEMO domain pipeline and the
Eocene options. Each section is a small dataclass; :func:`load_config` checks the keys and returns a
:class:`Config`. See ``docs/configuration.rst`` and the templates in ``configs/``.
"""

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
TEMPLATE = "configs/laptop.tmpl"


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or does not match the schema."""


@dataclass
class Paths:
    """Root directories. ``input`` and ``herold`` are read-only."""

    input: str
    output: str
    herold: str
    tmpdir: str | None = None


@dataclass
class Precomputed:
    """Files built elsewhere and copied into the output."""

    domain: str | None = None


@dataclass
class Atos:
    """Options of the ``atos`` backend (DOMAINcfg on ECMWF Atos)."""

    profile: str = "atos"
    oasis_lib_dir: str | None = None


@dataclass
class Tools:
    """How external tools are reached."""

    backend: str = "local"
    precomputed: Precomputed = field(default_factory=Precomputed)
    atos: Atos = field(default_factory=Atos)


@dataclass
class Grids:
    """Model resolutions, named as in ECE4-DATA."""

    oifs: str = "TL63L31"
    nemo: str = "PALEORCA2"


@dataclass
class NemoDomain:
    """NEMO domain pipeline (``ecefast nemo-domain``)."""

    output_dir: str
    coords_ori: str
    mesh_mask: str
    grids: dict[str, Any]
    parameters: dict[str, Any]
    steps: dict[str, bool]
    bathymetries: list[dict[str, Any]]
    domaincfg_dir: str | None = None
    aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class EoceneOIFS:
    """Eocene OIFS options."""

    aerosols: bool = False


@dataclass
class EoceneOASIS:
    """Eocene OASIS options."""

    # SST (K) written everywhere in rstos.nc: the value hardcoded in EoceneOASIS.create_rstos
    # before it became an option, a placeholder for the first coupled step.
    constant_sst: float = 290.0


@dataclass
class Eocene:
    """Eocene (DeepMIP) workflow options."""

    oifs: EoceneOIFS = field(default_factory=EoceneOIFS)
    oasis: EoceneOASIS = field(default_factory=EoceneOASIS)


@dataclass
class Config:
    """A validated configuration file."""

    file: str
    paths: Paths
    tools: Tools = field(default_factory=Tools)
    grids: Grids = field(default_factory=Grids)
    nemo_domain: NemoDomain | None = None
    eocene: Eocene = field(default_factory=Eocene)


BACKENDS = ("atos", "local", "fake")
NEMO_DOMAIN_STEPS = (
    "coordinates",
    "bathymetry",
    "configure_domain",
    "domain_cfg",
    "generate_mask",
    "generate_subbasins",
)
# sections whose values are themselves sections
NESTED = {"tools": {"precomputed": Precomputed, "atos": Atos}, "eocene": {"oifs": EoceneOIFS, "oasis": EoceneOASIS}}


def load_yaml(path: str | Path) -> Any:
    """Read a YAML file with ``yaml.safe_load``.

    Parameters
    ----------
    path : str or Path
        YAML file.

    Returns
    -------
    Any
        The parsed content.

    Raises
    ------
    ConfigError
        If the file does not exist, cannot be parsed or is empty.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"File not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Cannot parse YAML file {path}: {e}") from e
    if data is None:
        raise ConfigError(f"YAML file is empty: {path}")
    return data


def _build(cls: type, raw: Any, where: str, file: str) -> Any:
    """Build the dataclass ``cls`` from the mapping ``raw``, rejecting unknown and missing keys."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: '{where}' must be a mapping, got {type(raw).__name__}")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ConfigError(f"{file}: unknown key(s) in '{where}': {', '.join(unknown)}")
    missing = [
        name
        for name, f in fields.items()
        if name not in raw and f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    ]
    if missing:
        raise ConfigError(f"{file}: missing key(s) in '{where}': {', '.join(f'{where}.{m}' for m in missing)}")
    nested = NESTED.get(where, {})
    values = {k: _build(nested[k], v, f"{where}.{k}", file) if k in nested else v for k, v in raw.items()}
    return cls(**values)


def _check_type(value: Any, expected: type | tuple[type, ...], key: str, file: str) -> None:
    if not isinstance(value, expected):
        names = " or ".join(t.__name__ for t in (expected if isinstance(expected, tuple) else (expected,)))
        raise ConfigError(f"{file}: '{key}' must be {names}, got {value!r}")


def _validate(config: Config) -> None:
    """Check values: types, existing read-only directories, allowed choices."""
    file = config.file
    for name in ("input", "output", "herold"):
        _check_type(getattr(config.paths, name), str, f"paths.{name}", file)
    _check_type(config.paths.tmpdir, (str, type(None)), "paths.tmpdir", file)
    for name in ("input", "herold"):
        if not Path(getattr(config.paths, name)).is_dir():
            raise ConfigError(f"{file}: 'paths.{name}' is not a directory: {getattr(config.paths, name)}")
    if config.tools.backend not in BACKENDS:
        raise ConfigError(f"{file}: 'tools.backend' must be one of {', '.join(BACKENDS)}, got {config.tools.backend!r}")
    _check_type(config.tools.precomputed.domain, (str, type(None)), "tools.precomputed.domain", file)
    _check_type(config.tools.atos.profile, str, "tools.atos.profile", file)
    _check_type(config.tools.atos.oasis_lib_dir, (str, type(None)), "tools.atos.oasis_lib_dir", file)
    _check_type(config.grids.oifs, str, "grids.oifs", file)
    _check_type(config.grids.nemo, str, "grids.nemo", file)
    _check_type(config.eocene.oifs.aerosols, bool, "eocene.oifs.aerosols", file)
    _check_type(config.eocene.oasis.constant_sst, (int, float), "eocene.oasis.constant_sst", file)

    domain = config.nemo_domain
    if domain is not None:
        for name in ("grids", "parameters", "steps", "aliases"):
            _check_type(getattr(domain, name), dict, f"nemo_domain.{name}", file)
        _check_type(domain.bathymetries, list, "nemo_domain.bathymetries", file)
        unknown = sorted(set(domain.steps) - set(NEMO_DOMAIN_STEPS))
        if unknown:
            raise ConfigError(
                f"{file}: unknown step(s) in 'nemo_domain.steps': {', '.join(unknown)} "
                f"(known: {', '.join(NEMO_DOMAIN_STEPS)})"
            )


def load_config(path: str | Path) -> Config:
    """Read and validate a schema-1 configuration file.

    Parameters
    ----------
    path : str or Path
        YAML configuration file.

    Returns
    -------
    Config
        The configuration, with defaults filled in.

    Raises
    ------
    ConfigError
        If the file is missing or unreadable, uses the old ``dirs:`` format, has a wrong ``schema``,
        unknown or missing keys, values of the wrong type, or ``paths.input``/``paths.herold`` do not exist.
    """
    file = str(path)
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: the configuration must be a mapping")
    if "dirs" in raw or "profiles" in raw:
        raise ConfigError(
            f"{file}: old configuration format ('dirs:' or 'profiles:'), no longer read. "
            f"Migrate it to schema {SCHEMA_VERSION}: start from {TEMPLATE} and see docs/configuration.rst."
        )
    if "schema" not in raw:
        raise ConfigError(f"{file}: missing key 'schema' (expected 'schema: {SCHEMA_VERSION}', see {TEMPLATE})")
    if raw["schema"] != SCHEMA_VERSION:
        raise ConfigError(f"{file}: unsupported schema {raw['schema']!r}, this version reads schema {SCHEMA_VERSION}")

    sections = {"paths": Paths, "tools": Tools, "grids": Grids, "nemo_domain": NemoDomain, "eocene": Eocene}
    unknown = sorted(set(raw) - set(sections) - {"schema"})
    if unknown:
        raise ConfigError(f"{file}: unknown top-level key(s): {', '.join(unknown)}")
    if "paths" not in raw:
        raise ConfigError(f"{file}: missing section 'paths'")

    values = {name: _build(cls, raw[name], name, file) for name, cls in sections.items() if name in raw}
    config = Config(file=file, **values)
    _validate(config)
    return config
