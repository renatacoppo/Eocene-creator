"""Read and validate the ``ecefast`` configuration file (schema 2).

One YAML file per machine holds everything. Sections follow the components and the commands:
``ecefast <component> <command>`` reads section ``<component>.<command>`` (``ecefast nemo domain`` reads
``nemo.domain``), ``ecefast eocene run`` reads ``eocene``. Every command writes only to its own ``output_dir``.

Any string value may refer to another value of the file with a ``{section.key}`` placeholder, e.g.
``"{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"``; defaults count as values. The steps' ``reads``
and ``writes`` use the same placeholders (:meth:`Config.expand`).

Each section is a small dataclass; :func:`load_config` checks the keys, resolves the placeholders and returns a
:class:`Config`. See ``docs/configuration.rst`` and the templates in ``configs/``.
"""

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 2
TEMPLATE = "configs/laptop.tmpl"


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or does not match the schema."""


@dataclass
class Inputs:
    """Read-only input directories, shared by every command."""

    ece4_data: str
    herold: str


@dataclass
class Atos:
    """Options of the ``atos`` machine (DOMAINcfg on ECMWF Atos)."""

    profile: str = "atos"
    oasis_lib_dir: str | None = None


@dataclass
class Machine:
    """Where the EC-Earth tools (DOMAINcfg) run: ``local``, ``atos`` or ``fake`` (tests)."""

    name: str = "local"
    atos: Atos = field(default_factory=Atos)


@dataclass
class OIFS:
    """OIFS settings."""

    grid: str = "TL63L31"


@dataclass
class Staggering:
    """Staggering of the coordinate bounds of the source and target grids (``T`` or ``F``)."""

    source: str = "T"
    target: str = "T"


@dataclass
class NemoDomain:
    """NEMO domain pipeline (``ecefast nemo domain``)."""

    output_dir: str
    coords_ori: str
    source_grid: str
    minimum_depth: float
    steps: dict[str, bool]
    bathymetries: list[dict[str, Any]]
    tools_dir: str | None = None
    staggering: Staggering = field(default_factory=Staggering)


@dataclass
class Nemo:
    """NEMO settings and commands."""

    grid: str = "PALEORCA2"
    domain: NemoDomain | None = None


@dataclass
class EoceneDomain:
    """The Eocene NEMO domain installed by the ``domain`` step of ``ecefast eocene run``."""

    from_: str = field(metadata={"key": "from"})
    build: bool = False


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
    """Eocene (DeepMIP) workflow (``ecefast eocene run``)."""

    output_dir: str
    domain: EoceneDomain
    oifs: EoceneOIFS = field(default_factory=EoceneOIFS)
    oasis: EoceneOASIS = field(default_factory=EoceneOASIS)


@dataclass
class Config:
    """A validated configuration file, with every placeholder resolved."""

    file: str
    inputs: Inputs
    tmpdir: str | None = None
    machine: Machine = field(default_factory=Machine)
    oifs: OIFS = field(default_factory=OIFS)
    nemo: Nemo = field(default_factory=Nemo)
    eocene: Eocene | None = None

    def lookup(self, name: str) -> Any:
        """Value of the dotted key ``name`` (e.g. ``nemo.domain.output_dir``).

        Raises
        ------
        ConfigError
            If the key does not exist, is not set (``null``) or is a section.
        """
        return _lookup(_to_dict(self), name, self.file)

    def expand(self, template: str) -> str:
        """Replace the ``{section.key}`` placeholders of ``template`` with their values.

        Parameters
        ----------
        template : str
            Text with placeholders, e.g. ``"{inputs.ece4_data}/oasis/{nemo.grid}/rstos.nc"``.

        Returns
        -------
        str
            The text with every placeholder replaced.

        Raises
        ------
        ConfigError
            If a placeholder names a key that does not exist or is not set.
        """
        return PLACEHOLDER.sub(lambda m: str(self.lookup(m.group(1))), template)


BACKENDS = ("atos", "local", "fake")
NEMO_DOMAIN_STEPS = (
    "coordinates",
    "bathymetry",
    "configure_domain",
    "domain_cfg",
    "generate_mask",
    "generate_subbasins",
)
STAGGERING_OPTIONS = ("T", "F")
# the top-level sections, and the sections whose values are themselves sections
SECTIONS = {"inputs": Inputs, "machine": Machine, "oifs": OIFS, "nemo": Nemo, "eocene": Eocene}
NESTED = {
    "machine": {"atos": Atos},
    "nemo": {"domain": NemoDomain},
    "nemo.domain": {"staggering": Staggering},
    "eocene": {"domain": EoceneDomain, "oifs": EoceneOIFS, "oasis": EoceneOASIS},
}
# a placeholder: {name} or {section.key}, names are Python identifiers
PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}")

# Schema 1 keys and their schema 2 names, shown when a schema 1 file is read.
SCHEMA_1_KEYS = {
    "paths.input": "inputs.ece4_data",
    "paths.herold": "inputs.herold",
    "paths.output": "eocene.output_dir",
    "paths.tmpdir": "tmpdir",
    "tools.backend": "machine.name",
    "tools.atos": "machine.atos",
    "tools.precomputed.domain": "eocene.domain.from (and eocene.domain.build: false)",
    "grids.oifs": "oifs.grid",
    "grids.nemo": "nemo.grid",
    "nemo_domain": "nemo.domain",
    "nemo_domain.domaincfg_dir": "nemo.domain.tools_dir",
    "nemo_domain.grids.target": "nemo.grid",
    "nemo_domain.grids.source": "nemo.domain.source_grid",
    "nemo_domain.grids.staggering_source": "nemo.domain.staggering.source",
    "nemo_domain.grids.staggering_target": "nemo.domain.staggering.target",
    "nemo_domain.parameters.minimum_depth": "nemo.domain.minimum_depth",
    "nemo_domain.aliases": "removed: use {section.key} placeholders",
    "{input}, {herold}, {output} placeholders": "{inputs.ece4_data}, {inputs.herold}, {eocene.output_dir}",
}


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


def _key(f: dataclasses.Field) -> str:
    """Name of a dataclass field in the YAML file (``from_`` is ``from``)."""
    return f.metadata.get("key", f.name)


def _build(cls: type, raw: Any, where: str, file: str) -> Any:
    """Build the dataclass ``cls`` from the mapping ``raw``, rejecting unknown and missing keys."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: '{where}' must be a mapping, got {type(raw).__name__}")
    fields = {_key(f): f for f in dataclasses.fields(cls)}
    unknown = sorted(set(raw) - set(fields))
    if unknown:
        raise ConfigError(f"{file}: unknown key(s) in '{where}': {', '.join(unknown)}")
    missing = [
        key
        for key, f in fields.items()
        if key not in raw and f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    ]
    if missing:
        raise ConfigError(f"{file}: missing key(s) in '{where}': {', '.join(f'{where}.{m}' for m in missing)}")
    nested = NESTED.get(where, {})
    values = {
        fields[k].name: _build(nested[k], v, f"{where}.{k}", file) if k in nested and v is not None else v
        for k, v in raw.items()
    }
    return cls(**values)


def _to_dict(obj: Any) -> Any:
    """A dataclass tree as nested dicts with the YAML key names."""
    if dataclasses.is_dataclass(obj):
        return {_key(f): _to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj) if f.name != "file"}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def _lookup(values: dict, name: str, file: str) -> Any:
    """Value of the dotted key ``name`` in the nested dicts ``values``."""
    value: Any = values
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ConfigError(f"{file}: unknown key '{name}' in placeholder {{{name}}}")
        value = value[part]
    if value is None:
        raise ConfigError(f"{file}: placeholder {{{name}}} refers to '{name}', which is not set")
    if isinstance(value, (dict, list)):
        raise ConfigError(f"{file}: placeholder {{{name}}} refers to a section, not a value")
    return value


def resolve_placeholders(values: dict, file: str = "config") -> dict:
    """Resolve the ``{section.key}`` placeholders in every string of a configuration.

    A placeholder may refer to a value that has placeholders itself; those are resolved first.

    Parameters
    ----------
    values : dict
        The configuration as nested dicts and lists (YAML key names, defaults filled in).
    file : str
        File name, for the error messages.

    Returns
    -------
    dict
        A copy of ``values`` with every placeholder replaced.

    Raises
    ------
    ConfigError
        If a placeholder names an unknown key, a key that is not set or a section, or placeholders refer to each
        other in a cycle.
    """
    resolved: dict[str, str] = {}

    def resolve_key(name: str, chain: list[str]) -> str:
        if name in chain:
            cycle = " -> ".join([*chain[chain.index(name) :], name])
            raise ConfigError(f"{file}: placeholders refer to each other in a cycle: {cycle}")
        if name not in resolved:
            value = _lookup(values, name, file)
            resolved[name] = resolve_text(value, [*chain, name]) if isinstance(value, str) else str(value)
        return resolved[name]

    def resolve_text(text: str, chain: list[str]) -> str:
        return PLACEHOLDER.sub(lambda m: resolve_key(m.group(1), chain), text)

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return resolve_text(value, [])
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    return walk(values)


def _check_type(value: Any, expected: type | tuple[type, ...], key: str, file: str) -> None:
    if not isinstance(value, expected):
        names = " or ".join(t.__name__ for t in (expected if isinstance(expected, tuple) else (expected,)))
        raise ConfigError(f"{file}: '{key}' must be {names}, got {value!r}")


def _validate(config: Config) -> None:
    """Check values: types, existing read-only directories, allowed choices."""
    file = config.file
    for name in ("ece4_data", "herold"):
        path = getattr(config.inputs, name)
        _check_type(path, str, f"inputs.{name}", file)
        if not Path(path).is_dir():
            raise ConfigError(f"{file}: 'inputs.{name}' is not a directory: {path}")
    _check_type(config.tmpdir, (str, type(None)), "tmpdir", file)
    if config.machine.name not in BACKENDS:
        raise ConfigError(f"{file}: 'machine.name' must be one of {', '.join(BACKENDS)}, got {config.machine.name!r}")
    _check_type(config.machine.atos.profile, str, "machine.atos.profile", file)
    _check_type(config.machine.atos.oasis_lib_dir, (str, type(None)), "machine.atos.oasis_lib_dir", file)
    _check_type(config.oifs.grid, str, "oifs.grid", file)
    _check_type(config.nemo.grid, str, "nemo.grid", file)

    domain = config.nemo.domain
    if domain is not None:
        for name in ("output_dir", "coords_ori", "source_grid"):
            _check_type(getattr(domain, name), str, f"nemo.domain.{name}", file)
        _check_type(domain.tools_dir, (str, type(None)), "nemo.domain.tools_dir", file)
        _check_type(domain.minimum_depth, (int, float), "nemo.domain.minimum_depth", file)
        _check_type(domain.steps, dict, "nemo.domain.steps", file)
        _check_type(domain.bathymetries, list, "nemo.domain.bathymetries", file)
        for name in ("source", "target"):
            value = getattr(domain.staggering, name)
            if value not in STAGGERING_OPTIONS:
                raise ConfigError(f"{file}: 'nemo.domain.staggering.{name}' must be T or F, got {value!r}")
        unknown = sorted(set(domain.steps) - set(NEMO_DOMAIN_STEPS))
        if unknown:
            raise ConfigError(
                f"{file}: unknown step(s) in 'nemo.domain.steps': {', '.join(unknown)} "
                f"(known: {', '.join(NEMO_DOMAIN_STEPS)})"
            )

    eocene = config.eocene
    if eocene is not None:
        _check_type(eocene.output_dir, str, "eocene.output_dir", file)
        _check_type(eocene.domain.from_, str, "eocene.domain.from", file)
        _check_type(eocene.domain.build, bool, "eocene.domain.build", file)
        _check_type(eocene.oifs.aerosols, bool, "eocene.oifs.aerosols", file)
        _check_type(eocene.oasis.constant_sst, (int, float), "eocene.oasis.constant_sst", file)
        if eocene.domain.build and config.machine.name == "local":
            raise ConfigError(
                f"{file}: 'eocene.domain.build: true' runs DOMAINcfg, which is not available with "
                "'machine.name: local'. Set 'build: false' and point 'eocene.domain.from' at a domain built on "
                "Atos, or run on Atos (machine.name: atos)."
            )


def _schema_1_error(raw: dict, file: str) -> ConfigError:
    """The error for a schema 1 file: each old key found in it, with its new name."""

    def present(key: str) -> bool:
        value: Any = raw
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        return True

    found = {old: new for old, new in SCHEMA_1_KEYS.items() if old.startswith("{") or present(old)}
    width = max(len(old) for old in found)
    lines = [
        f"{file}: schema 1 configuration, no longer read. Migrate it to schema {SCHEMA_VERSION} "
        f"(start from {TEMPLATE}, see docs/configuration.rst). Old key -> new key:",
        *(f"  {old:<{width}}  ->  {new}" for old, new in found.items()),
        "  the Eocene domain is now explicit: eocene.domain.from (where it is) and eocene.domain.build.",
    ]
    return ConfigError("\n".join(lines))


def load_config(path: str | Path) -> Config:
    """Read and validate a schema-2 configuration file and resolve its placeholders.

    Parameters
    ----------
    path : str or Path
        YAML configuration file.

    Returns
    -------
    Config
        The configuration, with defaults filled in and every ``{section.key}`` placeholder resolved.

    Raises
    ------
    ConfigError
        If the file is missing or unreadable, uses an old format (``dirs:`` or schema 1, the error lists the new
        key names), has a wrong ``schema``, unknown or missing keys, values of the wrong type, a placeholder that
        names an unknown key or a cycle, or ``inputs.ece4_data``/``inputs.herold`` do not exist.
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
    if raw["schema"] == 1:
        raise _schema_1_error(raw, file)
    if raw["schema"] != SCHEMA_VERSION:
        raise ConfigError(f"{file}: unsupported schema {raw['schema']!r}, this version reads schema {SCHEMA_VERSION}")

    unknown = sorted(set(raw) - set(SECTIONS) - {"schema", "tmpdir"})
    if unknown:
        raise ConfigError(f"{file}: unknown top-level key(s): {', '.join(unknown)}")
    if "inputs" not in raw:
        raise ConfigError(f"{file}: missing section 'inputs'")

    def build(raw: dict) -> Config:
        values = {name: _build(cls, raw[name], name, file) for name, cls in SECTIONS.items() if raw.get(name)}
        return Config(file=file, tmpdir=raw.get("tmpdir"), **values)

    # build once to fill in the defaults, so placeholders can refer to them; then build from the resolved values
    config = build(resolve_placeholders(_to_dict(build(raw)), file))
    _validate(config)
    return config
