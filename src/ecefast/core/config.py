"""Read and validate the ``ecefast`` configuration file (schema 2).

One YAML file per machine holds everything. Sections follow the **time periods**: ``machine`` (where the tools
run and where intermediate files go), ``grids`` (the model resolution, shared by every period), then one section
per period, ``present`` and ``eocene``. Each period has ``input`` (the EC-Earth tree it starts from, read-only),
``output`` (the tree it makes) and one subsection per component (``oifs``, ``nemo``, ...); datasets of a period
have their own key (``eocene.herold``).

Any string value may refer to another value of the file with a ``{section.key}`` placeholder, e.g.
``"{present.input}"``; defaults count as values. The steps' ``reads`` and ``writes`` use the same placeholders,
plus the keys of the running period without the period name (``{input}``, ``{output}``, ``{herold}``,
``{nemo.source_grid}``), see :meth:`ecefast.core.workspace.Context.expand`.

Each section is a small dataclass; :func:`load_config` checks the keys, resolves the placeholders and returns a
:class:`Config`. See ``docs/configuration.rst`` and the templates in ``configs/``.
"""

import dataclasses
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 2
TEMPLATE = "configs/laptop.tmpl"


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or does not match the schema."""


# --- machine --------------------------------------------------------------------------------------------------------


@dataclass
class Atos:
    """Options of the ``atos`` machine (DOMAINcfg on ECMWF Atos)."""

    profile: str = "atos"
    # EC-Earth4 source tree: the atos backend finds the OASIS libraries and NEMO DOMAINcfg in it
    ecearth4_sources: str | None = None


@dataclass
class Machine:
    """Where the EC-Earth tools (DOMAINcfg) run (``local``, ``atos`` or ``fake``), and the scratch directory."""

    tmpdir: str
    name: str = "local"
    atos: Atos = field(default_factory=Atos)


# --- grids ----------------------------------------------------------------------------------------------------------


@dataclass
class OIFSGrid:
    """The OIFS resolution and the dated folders of its files, as in ECE4-DATA (``oifs/<name>/<startdate>/``)."""

    name: str = "TL63L31"
    startdate: str = "19900101"  # initial-state date of the ECE4-DATA tree (folder name)
    climate_version: str = "climate.v020"  # climate files version: climate.v020 for cy48, v015 for cy43


@dataclass
class NemoGrid:
    """The NEMO grid, and what the domain pipeline needs to build a domain on it."""

    name: str = "PALEORCA2"
    coords_ori: str | None = None  # coordinates with halo (NEMO 3.6); read when a domain is built
    staggering: str = "T"  # staggering of the target-grid coordinate bounds used in remapping


@dataclass
class Grids:
    """The model resolution, the same for every period."""

    oifs: OIFSGrid = field(default_factory=OIFSGrid)
    nemo: NemoGrid = field(default_factory=NemoGrid)


# --- steps ----------------------------------------------------------------------------------------------------------


@dataclass
class OIFSDataSteps:
    """Steps of the OIFS generator: today's defaults of the original script."""

    spectral: bool = True
    gridpoint: bool = True
    boundary: bool = False


@dataclass
class DomainSteps:
    """Steps of the NEMO domain pipeline, in run order. DOMAINcfg and the steps after it need ``atos`` or ``fake``."""

    coordinates: bool = True
    bathymetry: bool = True
    configure_domain: bool = True
    domain_cfg: bool = True
    generate_mask: bool = True
    generate_subbasins: bool = True


# --- present --------------------------------------------------------------------------------------------------------


@dataclass
class PresentOIFS:
    """The OIFS generator: the present-day base data of ``grids.oifs`` made from ``source_grid``."""

    # Defaults: the values of the original generator script (Atos, cy48). A finer source is better in
    # principle; TL255L91 because of the remapcon issue noted there.
    source_grid: str = "TL255L91"
    climate_dir: str | None = None
    precomputed_climate_dir: str | None = None
    vertical_grids_dir: str | None = None
    steps: OIFSDataSteps = field(default_factory=OIFSDataSteps)


@dataclass
class PresentNEMO:
    """The present-day NEMO domain: bathymetry of ``{input}/nemo/domain/<source_grid>/domain_cfg.nc``."""

    minimum_depth: float
    source_grid: str = "eORCA1"
    source_staggering: str = "T"  # staggering of the source-grid coordinate bounds (used in setgrid)
    steps: DomainSteps = field(default_factory=DomainSteps)


@dataclass
class Present:
    """The present-day period: what is built on the present-day EC-Earth tree."""

    input: str
    output: str
    oifs: PresentOIFS | None = None
    nemo: PresentNEMO | None = None


# --- eocene ---------------------------------------------------------------------------------------------------------


@dataclass
class EoceneNEMO:
    """Eocene NEMO options: where the Eocene domain comes from, and how it is built."""

    domain: str  # "build", or a directory holding domain_cfg.nc and maskutil.nc
    minimum_depth: float
    steps: DomainSteps = field(default_factory=DomainSteps)


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
    """The Eocene (DeepMIP) period: the present-day tree modified with the Herold et al. (2014) data."""

    input: str
    herold: str
    output: str
    nemo: EoceneNEMO
    oifs: EoceneOIFS = field(default_factory=EoceneOIFS)
    oasis: EoceneOASIS = field(default_factory=EoceneOASIS)


# --- the file -------------------------------------------------------------------------------------------------------


@dataclass
class Config:
    """A validated configuration file, with every placeholder resolved."""

    file: str
    machine: Machine
    grids: Grids = field(default_factory=Grids)
    present: Present | None = None
    eocene: Eocene | None = None

    def lookup(self, name: str) -> Any:
        """Value of the dotted key ``name`` (e.g. ``present.output``).

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
            Text with placeholders, e.g. ``"{present.input}/oasis/{grids.nemo.name}/rstos.nc"``.

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

    def period(self, name: str) -> Present | Eocene:
        """The section of period ``name``.

        Raises
        ------
        ConfigError
            If ``name`` is not a period or the file has no section for it.
        """
        if name not in PERIODS:
            raise ConfigError(f"Unknown period {name!r} (known: {', '.join(PERIODS)})")
        section = getattr(self, name)
        if section is None:
            raise ConfigError(f"{self.file}: this command needs a '{name}' section")
        return section

    def read_only_roots(self) -> dict[str, str]:
        """The read-only directories of every period in the file, by key (``present.input``, ``eocene.herold``)."""
        roots = {}
        for period in PERIODS:
            section = getattr(self, period)
            for key in READ_ONLY_KEYS.get(period, ()):
                if section is not None:
                    roots[f"{period}.{key}"] = getattr(section, key)
        return roots

    def check_inputs(self, period: str) -> None:
        """Check that the read-only directories of ``period`` exist.

        Raises
        ------
        ConfigError
            Naming the first key whose directory does not exist.
        """
        section = self.period(period)
        for key in READ_ONLY_KEYS[period]:
            path = getattr(section, key)
            if not Path(path).is_dir():
                raise ConfigError(f"{self.file}: '{period}.{key}' is not a directory: {path}")


PERIODS = ("present", "eocene")
# the read-only directories of each period
READ_ONLY_KEYS = {"present": ("input",), "eocene": ("input", "herold")}
# the components of each period that have configurable steps (``--oifs a,b`` and ``--nemo c,d``)
STEP_SECTIONS = {("present", "oifs"), ("present", "nemo"), ("eocene", "nemo")}
BACKENDS = ("atos", "local", "fake")
NEMO_DOMAIN_STEPS = tuple(f.name for f in dataclasses.fields(DomainSteps))
OIFS_DATA_STEPS = tuple(f.name for f in dataclasses.fields(OIFSDataSteps))
STAGGERING_OPTIONS = ("T", "F")
# the value of eocene.nemo.domain that builds the domain
BUILD = "build"
# the top-level sections, and the sections whose values are themselves sections
SECTIONS = {"machine": Machine, "grids": Grids, "present": Present, "eocene": Eocene}
NESTED = {
    "machine": {"atos": Atos},
    "grids": {"oifs": OIFSGrid, "nemo": NemoGrid},
    "present": {"oifs": PresentOIFS, "nemo": PresentNEMO},
    "present.oifs": {"steps": OIFSDataSteps},
    "present.nemo": {"steps": DomainSteps},
    "eocene": {"nemo": EoceneNEMO, "oifs": EoceneOIFS, "oasis": EoceneOASIS},
    "eocene.nemo": {"steps": DomainSteps},
}
# a placeholder: {name} or {section.key}, names are Python identifiers
PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}")

# Keys of earlier layouts and their names now, shown when an old file is read.
SCHEMA_1_KEYS = {
    "paths.input": 'present.input (and eocene.input: "{present.input}")',
    "paths.herold": "eocene.herold",
    "paths.output": "eocene.output",
    "paths.tmpdir": "machine.tmpdir",
    "tools.backend": "machine.name",
    "tools.atos": "machine.atos",
    "tools.precomputed.domain": "eocene.nemo.domain",
    "grids.oifs": "grids.oifs.name",
    "grids.nemo": "grids.nemo.name",
    "nemo_domain": "present.nemo (present-day domain), eocene.nemo (Eocene domain), grids.nemo",
    "{input}, {herold}, {output} placeholders": "{present.input}, {eocene.herold}, {eocene.output}",
}
COMPONENT_LAYOUT_KEYS = {
    "inputs.ece4_data": 'present.input (and eocene.input: "{present.input}")',
    "inputs.herold": "eocene.herold",
    "tmpdir": "machine.tmpdir (required)",
    "machine.atos.oasis_lib_dir": "machine.atos.ecearth4_sources",
    "oifs.grid": "grids.oifs.name",
    "oifs.data": "present.oifs (output: present.output, startdate and climate_version: grids.oifs)",
    "nemo.grid": "grids.nemo.name",
    "nemo.domain": "present.nemo and eocene.nemo (coords_ori and staggering.target: grids.nemo)",
    "nemo.domain.tools_dir": "machine.atos.ecearth4_sources",
    "nemo.domain.bathymetries": "removed: each period uses its own bathymetry",
    "eocene.output_dir": "eocene.output",
    "eocene.domain": "eocene.nemo.domain: build, or the directory of the domain",
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


def _build(cls: type, raw: Any, where: str, file: str) -> Any:
    """Build the dataclass ``cls`` from the mapping ``raw``, rejecting unknown and missing keys."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: '{where}' must be a mapping, got {type(raw).__name__}")
    fields = {f.name: f for f in dataclasses.fields(cls)}
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
        k: _build(nested[k], v, f"{where}.{k}", file) if k in nested and v is not None else v for k, v in raw.items()
    }
    return cls(**values)


def _to_dict(obj: Any) -> Any:
    """A dataclass tree as nested dicts with the YAML key names."""
    if dataclasses.is_dataclass(obj):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj) if f.name != "file"}
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


def has_key(values: dict, name: str) -> bool:
    """Whether the dotted key ``name`` exists in the nested dicts ``values`` (set or not)."""
    value: Any = values
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


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


def _check_steps(steps: Any, key: str, file: str) -> None:
    for f in dataclasses.fields(steps):
        _check_type(getattr(steps, f.name), bool, f"{key}.{f.name}", file)


def _inside(path: str, root: str) -> bool:
    """``path`` is ``root`` or lies inside it (paths need not exist)."""
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _validate(config: Config) -> None:
    """Check values: types, allowed choices, where ``tmpdir`` may be. Directories are checked per period."""
    file = config.file
    machine = config.machine
    _check_type(machine.tmpdir, str, "machine.tmpdir", file)
    if machine.name not in BACKENDS:
        raise ConfigError(f"{file}: 'machine.name' must be one of {', '.join(BACKENDS)}, got {machine.name!r}")
    _check_type(machine.atos.profile, str, "machine.atos.profile", file)
    _check_type(machine.atos.ecearth4_sources, (str, type(None)), "machine.atos.ecearth4_sources", file)

    for name in ("name", "startdate", "climate_version"):
        _check_type(getattr(config.grids.oifs, name), str, f"grids.oifs.{name}", file)
    _check_type(config.grids.nemo.name, str, "grids.nemo.name", file)
    _check_type(config.grids.nemo.coords_ori, (str, type(None)), "grids.nemo.coords_ori", file)

    staggering = {"grids.nemo.staggering": config.grids.nemo.staggering}
    present = config.present
    if present is not None:
        for name in ("input", "output"):
            _check_type(getattr(present, name), str, f"present.{name}", file)
        if present.oifs is not None:
            _check_type(present.oifs.source_grid, str, "present.oifs.source_grid", file)
            for name in ("climate_dir", "precomputed_climate_dir", "vertical_grids_dir"):
                _check_type(getattr(present.oifs, name), (str, type(None)), f"present.oifs.{name}", file)
            _check_steps(present.oifs.steps, "present.oifs.steps", file)
        if present.nemo is not None:
            _check_type(present.nemo.source_grid, str, "present.nemo.source_grid", file)
            _check_type(present.nemo.minimum_depth, (int, float), "present.nemo.minimum_depth", file)
            _check_steps(present.nemo.steps, "present.nemo.steps", file)
            staggering["present.nemo.source_staggering"] = present.nemo.source_staggering

    eocene = config.eocene
    if eocene is not None:
        for name in ("input", "herold", "output"):
            _check_type(getattr(eocene, name), str, f"eocene.{name}", file)
        _check_type(eocene.nemo.domain, str, "eocene.nemo.domain", file)
        _check_type(eocene.nemo.minimum_depth, (int, float), "eocene.nemo.minimum_depth", file)
        _check_steps(eocene.nemo.steps, "eocene.nemo.steps", file)
        _check_type(eocene.oifs.aerosols, bool, "eocene.oifs.aerosols", file)
        _check_type(eocene.oasis.constant_sst, (int, float), "eocene.oasis.constant_sst", file)
        if eocene.nemo.domain == BUILD and machine.name == "local":
            raise ConfigError(
                f"{file}: 'eocene.nemo.domain: build' runs DOMAINcfg, which is not available with "
                "'machine.name: local'. Point 'eocene.nemo.domain' at the directory of a domain built on Atos "
                "(its domain_cfg.nc and maskutil.nc), or run on Atos (machine.name: atos)."
            )

    for key, value in staggering.items():
        if value not in STAGGERING_OPTIONS:
            raise ConfigError(f"{file}: '{key}' must be T or F, got {value!r}")

    for key, root in config.read_only_roots().items():
        if _inside(machine.tmpdir, root):
            raise ConfigError(f"{file}: 'machine.tmpdir' {machine.tmpdir} lies inside the read-only '{key}' {root}")
    for period in PERIODS:
        section = getattr(config, period)
        if section is not None and _inside(machine.tmpdir, section.output):
            raise ConfigError(
                f"{file}: 'machine.tmpdir' {machine.tmpdir} lies inside '{period}.output' {section.output}: "
                "keep intermediate files out of the output trees"
            )


def override_steps(config: Config, period: str, component: str, names: list[str]) -> None:
    """Run only the steps ``names`` of a component of a period (the ``--oifs`` and ``--nemo`` options).

    Parameters
    ----------
    config : Config
        The configuration; its ``<period>.<component>.steps`` is replaced.
    period, component : str
        E.g. ``present`` and ``nemo``.
    names : list of str
        The steps to switch on; every other step of the component is switched off.

    Raises
    ------
    ConfigError
        If the component of the period has no steps, its section is missing, or a name is not one of its steps.
    """
    if (period, component) not in STEP_SECTIONS:
        with_steps = ", ".join(f"{p}.{c}" for p, c in sorted(STEP_SECTIONS))
        raise ConfigError(f"'{period}.{component}' has no steps to select (only {with_steps} have)")
    section = getattr(config.period(period), component)
    if section is None:
        raise ConfigError(f"{config.file}: --{component} selects steps of '{period}.{component}', which is missing")
    known = [f.name for f in dataclasses.fields(section.steps)]
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ConfigError(f"Unknown {period}.{component} step(s): {', '.join(unknown)} (known: {', '.join(known)})")
    section.steps = type(section.steps)(**{n: n in names for n in known})


def _old_layout_error(raw: dict, file: str, keys: dict[str, str], what: str) -> ConfigError:
    """The error for a file in an old layout: each old key found in it, with its name now."""
    found = {old: new for old, new in keys.items() if old.startswith("{") or has_key(raw, old)}
    width = max(len(old) for old in found)
    lines = [
        f"{file}: {what}, no longer read. Migrate it to the current schema {SCHEMA_VERSION} "
        f"(start from {TEMPLATE}, see docs/configuration.rst). Old key -> new key:",
        *(f"  {old:<{width}}  ->  {new}" for old, new in found.items()),
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
        If the file is missing or unreadable, uses an old layout (``dirs:``, schema 1, or the component sections
        of the first schema 2; the error lists the new key names), has a wrong ``schema``, unknown or missing keys,
        values of the wrong type, a placeholder that names an unknown key or a cycle, or ``machine.tmpdir`` lies
        inside a read-only directory or an output tree.
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
        raise _old_layout_error(raw, file, SCHEMA_1_KEYS, "schema 1 configuration")
    if raw["schema"] != SCHEMA_VERSION:
        raise ConfigError(f"{file}: unsupported schema {raw['schema']!r}, this version reads schema {SCHEMA_VERSION}")
    if any(key in raw for key in ("inputs", "oifs", "nemo", "tmpdir")):
        raise _old_layout_error(raw, file, COMPONENT_LAYOUT_KEYS, "configuration with component sections")

    unknown = sorted(set(raw) - set(SECTIONS) - {"schema"})
    if unknown:
        raise ConfigError(f"{file}: unknown top-level key(s): {', '.join(unknown)}")
    if not raw.get("machine"):
        raise ConfigError(f"{file}: missing section 'machine' (it holds the required 'machine.tmpdir')")

    def build(raw: dict) -> Config:
        values = {name: _build(cls, raw[name], name, file) for name, cls in SECTIONS.items() if raw.get(name)}
        return Config(file=file, **values)

    # build once to fill in the defaults, so placeholders can refer to them; then build from the resolved values
    config = build(resolve_placeholders(_to_dict(build(raw)), file))
    _validate(config)
    return config
