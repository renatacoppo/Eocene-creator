"""Unit tests for the configuration loader (schema 2, sections by time period) and its placeholders."""

from pathlib import Path

import pytest
import yaml

from ecefast.core.config import ConfigError, load_config, override_steps, resolve_placeholders

pytestmark = pytest.mark.unit

REPO = Path(__file__).parents[2]


def minimal(tmp_path: Path) -> dict:
    """Smallest valid configuration: the machine and its scratch directory."""
    return {"schema": 2, "machine": {"tmpdir": str(tmp_path / "tmp")}}


def present(tmp_path: Path) -> dict:
    (tmp_path / "input").mkdir(exist_ok=True)
    return {"input": str(tmp_path / "input"), "output": str(tmp_path / "out" / "present")}


def eocene(tmp_path: Path) -> dict:
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "herold").mkdir(exist_ok=True)
    return {
        "input": str(tmp_path / "input"),
        "herold": str(tmp_path / "herold"),
        "output": str(tmp_path / "out" / "eocene"),
        "nemo": {"domain": "/data/domain/PALEORCA2/eocene", "minimum_depth": 30},
    }


def write(tmp_path: Path, config: dict) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_minimal_config_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path)))
    assert config.machine.tmpdir == str(tmp_path / "tmp")
    assert config.machine.name == "local"
    assert (config.machine.atos.profile, config.machine.atos.ecearth4_sources) == ("atos", None)
    oifs, nemo = config.grids.oifs, config.grids.nemo
    assert (oifs.name, oifs.startdate, oifs.climate_version) == ("TL63L31", "19900101", "climate.v020")
    assert (nemo.name, nemo.coords_ori, nemo.staggering) == ("PALEORCA2", None, "T")
    assert config.present is None and config.eocene is None


def test_present_section_loads_with_defaults(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path) | {"oifs": {}, "nemo": {"minimum_depth": 30}}}
    section = load_config(write(tmp_path, raw)).present
    assert section.oifs.source_grid == "TL255L91"
    assert (section.oifs.climate_dir, section.oifs.precomputed_climate_dir) == (None, None)
    assert vars(section.oifs.steps) == {"spectral": True, "gridpoint": True, "boundary": False}
    assert (section.nemo.source_grid, section.nemo.source_staggering, section.nemo.minimum_depth) == ("eORCA1", "T", 30)
    assert all(vars(section.nemo.steps).values())


def test_eocene_section_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path) | {"eocene": eocene(tmp_path)}))
    assert config.eocene.output == str(tmp_path / "out" / "eocene")
    assert config.eocene.nemo.domain == "/data/domain/PALEORCA2/eocene"
    assert config.eocene.oifs.aerosols is False
    assert config.eocene.oasis.constant_sst == 290.0


@pytest.mark.parametrize(
    "section, value, read, expected",
    [
        ("machine", {"name": "fake"}, lambda c: c.machine.name, "fake"),
        ("machine", {"atos": {"ecearth4_sources": "/src"}}, lambda c: c.machine.atos.ecearth4_sources, "/src"),
        ("grids", {"oifs": {"name": "TL159L91"}}, lambda c: c.grids.oifs.name, "TL159L91"),
        ("grids", {"oifs": {"startdate": "20000101"}}, lambda c: c.grids.oifs.startdate, "20000101"),
        ("grids", {"nemo": {"name": "ORCA2", "staggering": "F"}}, lambda c: c.grids.nemo.staggering, "F"),
    ],
)
def test_override_default(tmp_path: Path, section, value, read, expected) -> None:
    raw = minimal(tmp_path)
    raw[section] = raw.get(section, {}) | value
    assert read(load_config(write(tmp_path, raw))) == expected


@pytest.mark.parametrize(
    "value, read, expected",
    [
        ({"oifs": {"aerosols": True}}, lambda c: c.eocene.oifs.aerosols, True),
        ({"oasis": {"constant_sst": 285.5}}, lambda c: c.eocene.oasis.constant_sst, 285.5),
    ],
)
def test_override_eocene_option(tmp_path: Path, value, read, expected) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene(tmp_path) | value}
    assert read(load_config(write(tmp_path, raw))) == expected


# --- placeholders ---------------------------------------------------------------------------------------------------


def test_eocene_input_from_present(tmp_path: Path) -> None:
    """``eocene.input`` written as ``"{present.input}"``, as in the templates; defaults count as values."""
    raw = minimal(tmp_path) | {
        "present": present(tmp_path),
        "eocene": eocene(tmp_path) | {"input": "{present.input}", "output": "{present.output}/../eocene"},
    }
    config = load_config(write(tmp_path, raw))
    assert config.eocene.input == config.present.input
    assert config.expand("{eocene.input}/oifs/{grids.oifs.name}") == f"{tmp_path / 'input'}/oifs/TL63L31"


def test_placeholder_with_number_value() -> None:
    values = {"eocene": {"nemo": {"minimum_depth": 30, "note": "min {eocene.nemo.minimum_depth} m"}}}
    assert resolve_placeholders(values)["eocene"]["nemo"]["note"] == "min 30 m"


@pytest.mark.parametrize(
    "value, match",
    [
        ("{present.outptu}/x", r"unknown key 'present.outptu' in placeholder"),
        ("{input}/x", r"unknown key 'input'"),
        ("{grids.nemo.coords_ori}/x", r"'grids.nemo.coords_ori', which is not set"),
        ("{grids}/x", r"refers to a section"),
    ],
)
def test_bad_placeholder(tmp_path: Path, value: str, match: str) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path) | {"output": value}}
    with pytest.raises(ConfigError, match=match) as err:
        load_config(write(tmp_path, raw))
    assert "config.yml" in str(err.value)


def test_placeholder_cycle(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {
        "present": present(tmp_path) | {"input": "{present.output}", "output": "{present.input}"}
    }
    with pytest.raises(ConfigError, match=r"cycle: present\.(input|output) -> present\.(output|input)"):
        load_config(write(tmp_path, raw))


# --- tmpdir -----------------------------------------------------------------------------------------------------------


def test_missing_machine_section(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing section 'machine'.*tmpdir"):
        load_config(write(tmp_path, {"schema": 2}))


def test_missing_tmpdir(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"machine\.tmpdir"):
        load_config(write(tmp_path, {"schema": 2, "machine": {"name": "local"}}))


@pytest.mark.parametrize("key", ["input", "output", "herold"])
def test_tmpdir_outside_inputs_and_outputs(tmp_path: Path, key: str) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene(tmp_path)}
    raw["machine"]["tmpdir"] = raw["eocene"][key] + "/tmp"
    with pytest.raises(ConfigError, match=rf"machine\.tmpdir.*'eocene\.{key}'"):
        load_config(write(tmp_path, raw))


# --- periods ----------------------------------------------------------------------------------------------------------


def test_period_section_missing(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path)))
    with pytest.raises(ConfigError, match="needs a 'present' section"):
        config.period("present")
    with pytest.raises(ConfigError, match="Unknown period 'miocene'"):
        config.period("miocene")


@pytest.mark.parametrize("key", ["input", "herold"])
def test_check_inputs(tmp_path: Path, key: str) -> None:
    """Read-only directories are checked for the running period only: a missing Herold folder does not stop the
    present-day commands."""
    raw = minimal(tmp_path) | {"present": present(tmp_path), "eocene": eocene(tmp_path) | {key: str(tmp_path / "no")}}
    config = load_config(write(tmp_path, raw))
    config.check_inputs("present")
    with pytest.raises(ConfigError, match=rf"'eocene\.{key}' is not a directory"):
        config.check_inputs("eocene")


def test_read_only_roots(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path), "eocene": eocene(tmp_path)}
    roots = load_config(write(tmp_path, raw)).read_only_roots()
    assert set(roots) == {"present.input", "eocene.input", "eocene.herold"}


def test_build_needs_a_machine_that_runs_domaincfg(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene(tmp_path)}
    raw["eocene"]["nemo"]["domain"] = "build"
    with pytest.raises(ConfigError, match="'eocene.nemo.domain: build' runs DOMAINcfg"):
        load_config(write(tmp_path, raw))
    raw["machine"]["name"] = "fake"
    assert load_config(write(tmp_path, raw)).eocene.nemo.domain == "build"


# --- step overrides (--oifs, --nemo) -----------------------------------------------------------------------------------


def test_override_steps(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path) | {"nemo": {"minimum_depth": 30}}}
    config = load_config(write(tmp_path, raw))
    override_steps(config, "present", "nemo", ["coordinates", "bathymetry"])
    steps = vars(config.present.nemo.steps)
    assert [name for name, on in steps.items() if on] == ["coordinates", "bathymetry"]


@pytest.mark.parametrize(
    "period, component, names, match",
    [
        ("present", "nemo", ["bathymetri"], r"Unknown present\.nemo step\(s\): bathymetri \(known: coordinates"),
        ("eocene", "oifs", ["spectral"], r"'eocene\.oifs' has no steps"),
        ("present", "oifs", ["spectral"], r"'present\.oifs', which is missing"),
    ],
)
def test_override_steps_errors(tmp_path: Path, period, component, names, match) -> None:
    raw = minimal(tmp_path) | {
        "present": present(tmp_path) | {"nemo": {"minimum_depth": 30}},
        "eocene": eocene(tmp_path),
    }
    config = load_config(write(tmp_path, raw))
    with pytest.raises(ConfigError, match=match):
        override_steps(config, period, component, names)


# --- errors -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["input", "output"])
def test_missing_present_key(tmp_path: Path, key: str) -> None:
    section = present(tmp_path)
    del section[key]
    with pytest.raises(ConfigError, match=rf"missing key.*present\.{key}") as err:
        load_config(write(tmp_path, minimal(tmp_path) | {"present": section}))
    assert "config.yml" in str(err.value)


@pytest.mark.parametrize(
    "drop", [("input",), ("herold",), ("output",), ("nemo",), ("nemo", "domain"), ("nemo", "minimum_depth")]
)
def test_missing_eocene_key(tmp_path: Path, drop: tuple) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene(tmp_path)}
    section = raw["eocene"]
    for name in drop[:-1]:
        section = section[name]
    del section[drop[-1]]
    with pytest.raises(ConfigError, match=rf"missing key.*eocene\.{'.'.join(drop)}"):
        load_config(write(tmp_path, raw))


def test_missing_present_nemo_minimum_depth(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path) | {"nemo": {"source_grid": "eORCA1"}}}
    with pytest.raises(ConfigError, match=r"present\.nemo\.minimum_depth"):
        load_config(write(tmp_path, raw))


def test_missing_schema(tmp_path: Path) -> None:
    raw = minimal(tmp_path)
    del raw["schema"]
    with pytest.raises(ConfigError, match="schema"):
        load_config(write(tmp_path, raw))


def test_wrong_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported schema 3"):
        load_config(write(tmp_path, minimal(tmp_path) | {"schema": 3}))


def test_schema_1_lists_the_new_keys(tmp_path: Path) -> None:
    """A schema 1 file fails with one error naming each of its old keys and the new one."""
    raw = {
        "schema": 1,
        "paths": {"input": "/i", "output": "/o", "herold": "/h"},
        "tools": {"backend": "atos", "precomputed": {"domain": "/d"}},
        "nemo_domain": {"output_dir": "/x"},
    }
    with pytest.raises(ConfigError) as err:
        load_config(write(tmp_path, raw))
    message = str(err.value)
    assert "schema 1 configuration, no longer read" in message
    for old, new in [
        ("paths.input", "present.input"),
        ("paths.output", "eocene.output"),
        ("paths.herold", "eocene.herold"),
        ("tools.backend", "machine.name"),
        ("tools.precomputed.domain", "eocene.nemo.domain"),
        ("nemo_domain", "present.nemo"),
    ]:
        assert any(old in line and new in line for line in message.splitlines()), (old, new)
    assert "grids.oifs " not in message  # only the keys of this file


def test_component_layout_lists_the_new_keys(tmp_path: Path) -> None:
    """A file in the first schema 2 layout (sections by component) fails naming each old key and the new one."""
    raw = {
        "schema": 2,
        "inputs": {"ece4_data": "/i", "herold": "/h"},
        "machine": {"name": "atos", "atos": {"oasis_lib_dir": "/lib"}},
        "nemo": {"grid": "PALEORCA2", "domain": {"output_dir": "/x", "tools_dir": "/t", "bathymetries": []}},
        "eocene": {"output_dir": "/o", "domain": {"from": "/d"}},
    }
    with pytest.raises(ConfigError) as err:
        load_config(write(tmp_path, raw))
    message = str(err.value)
    assert "configuration with component sections, no longer read" in message
    for old, new in [
        ("inputs.ece4_data", "present.input"),
        ("inputs.herold", "eocene.herold"),
        ("machine.atos.oasis_lib_dir", "machine.atos.ecearth4_sources"),
        ("nemo.domain.tools_dir", "machine.atos.ecearth4_sources"),
        ("nemo.grid", "grids.nemo.name"),
        ("eocene.output_dir", "eocene.output"),
        ("eocene.domain", "eocene.nemo.domain"),
    ]:
        assert any(old in line and new in line for line in message.splitlines()), (old, new)


@pytest.mark.parametrize("old", [{"dirs": {"input": "/x"}}, {"profile": "local", "profiles": {"local": {}}}])
def test_old_format_asks_to_migrate(tmp_path: Path, old: dict) -> None:
    with pytest.raises(ConfigError, match=r"old configuration format.*configs/laptop\.tmpl"):
        load_config(write(tmp_path, old))


def test_unknown_top_level_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown top-level key.*dirz"):
        load_config(write(tmp_path, minimal(tmp_path) | {"dirz": {}}))


@pytest.mark.parametrize(
    "section, value, where",
    [
        ("machine", {"atos": {"modules": []}}, "machine.atos"),
        ("grids", {"nemo": {"atmosphere": "TL63L31"}}, "grids.nemo"),
        ("present", {"inptu": "/x"}, "present"),
        ("present", {"nemo": {"minimum_depth": 30, "steps": {"bathymetri": True}}}, "present.nemo.steps"),
        ("eocene", {"oasis": {"sst": 1.0}}, "eocene.oasis"),
    ],
)
def test_unknown_key_in_section(tmp_path: Path, section: str, value: dict, where: str) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path), "eocene": eocene(tmp_path)}
    raw[section] = raw.get(section, {}) | value
    with pytest.raises(ConfigError, match=rf"unknown key\(s\) in '{where}'"):
        load_config(write(tmp_path, raw))


@pytest.mark.parametrize(
    "section, value, key",
    [
        ("machine", {"name": "hpc"}, "machine.name"),
        ("machine", {"atos": {"profile": 1}}, "machine.atos.profile"),
        ("grids", {"nemo": {"staggering": "U"}}, "grids.nemo.staggering"),
        ("present", {"nemo": {"minimum_depth": 30, "source_staggering": "U"}}, "present.nemo.source_staggering"),
        ("present", {"nemo": {"minimum_depth": "deep"}}, "present.nemo.minimum_depth"),
        ("present", {"oifs": {"steps": {"boundary": "yes"}}}, "present.oifs.steps.boundary"),
        ("eocene", {"oifs": {"aerosols": "no"}}, "eocene.oifs.aerosols"),
        ("eocene", {"oasis": {"constant_sst": "warm"}}, "eocene.oasis.constant_sst"),
    ],
)
def test_bad_value(tmp_path: Path, section: str, value: dict, key: str) -> None:
    raw = minimal(tmp_path) | {"present": present(tmp_path), "eocene": eocene(tmp_path)}
    raw[section] = raw.get(section, {}) | value
    with pytest.raises(ConfigError, match=key):
        load_config(write(tmp_path, raw))


def test_missing_and_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yml")
    (tmp_path / "empty.yml").write_text("")
    with pytest.raises(ConfigError, match="empty"):
        load_config(tmp_path / "empty.yml")


@pytest.mark.parametrize("template", ["laptop.tmpl", "atos.tmpl"])
def test_templates_load(tmp_path: Path, template: str) -> None:
    """The committed templates are valid, both periods present."""
    config = load_config(REPO / "configs" / template)
    # on Atos the Eocene starts from the present-day tree of `ecefast present run`; on a laptop from ECE4-DATA
    start = config.present.output if template == "atos.tmpl" else config.present.input
    assert config.eocene.input == start
    assert config.present.nemo.source_grid == "eORCA1"
    assert (config.present.oifs is not None) == (template == "atos.tmpl")  # the generator's inputs are on Atos
    assert (config.eocene.nemo.domain == "build") == (template == "atos.tmpl")
