"""Unit tests for the configuration loader (schema 2) and its ``{section.key}`` placeholders."""

from pathlib import Path

import pytest
import yaml

from ecefast.core.config import ConfigError, load_config, resolve_placeholders

pytestmark = pytest.mark.unit

REPO = Path(__file__).parents[2]


def minimal(tmp_path: Path) -> dict:
    """Smallest valid configuration, with existing input directories."""
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "herold").mkdir(exist_ok=True)
    return {"schema": 2, "inputs": {"ece4_data": str(tmp_path / "input"), "herold": str(tmp_path / "herold")}}


def nemo_domain() -> dict:
    return {
        "output_dir": "/out/nemo-domain",
        "coords_ori": "/data/coords_ori.nc",
        "source_grid": "eORCA1",
        "minimum_depth": 30,
        "steps": {"coordinates": True, "bathymetry": True},
        "bathymetries": [
            {"name": "eocene", "enabled": True, "processor": "EoceneBathymetry", "source_file": "{inputs.herold}/x.nc"}
        ],
    }


def eocene() -> dict:
    return {"output_dir": "/out/eocene", "domain": {"from": "/data/domain/PALEORCA2/eocene"}}


def write(tmp_path: Path, config: dict) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_minimal_config_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path)))
    assert config.inputs.ece4_data == str(tmp_path / "input")
    assert config.tmpdir is None
    assert config.machine.name == "local"
    assert (config.machine.atos.profile, config.machine.atos.oasis_lib_dir) == ("atos", None)
    assert config.oifs.grid == "TL63L31"
    assert config.nemo.grid == "PALEORCA2"
    assert config.nemo.domain is None
    assert config.eocene is None


def test_nemo_domain_section_loads_with_defaults(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"nemo": {"domain": nemo_domain()}}
    domain = load_config(write(tmp_path, raw)).nemo.domain
    assert domain.output_dir == "/out/nemo-domain"
    assert domain.tools_dir is None
    assert (domain.staggering.source, domain.staggering.target) == ("T", "T")
    assert domain.minimum_depth == 30
    assert domain.bathymetries[0]["source_file"] == f"{tmp_path / 'herold'}/x.nc"


def test_eocene_section_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path) | {"eocene": eocene()}))
    assert config.eocene.output_dir == "/out/eocene"
    assert config.eocene.domain.from_ == "/data/domain/PALEORCA2/eocene"
    assert config.eocene.domain.build is False
    assert config.eocene.oifs.aerosols is False
    assert config.eocene.oasis.constant_sst == 290.0


@pytest.mark.parametrize(
    "section, value, read, expected",
    [
        ("tmpdir", "/tmp/x", lambda c: c.tmpdir, "/tmp/x"),
        ("machine", {"name": "fake"}, lambda c: c.machine.name, "fake"),
        ("machine", {"atos": {"oasis_lib_dir": "/lib"}}, lambda c: c.machine.atos.oasis_lib_dir, "/lib"),
        ("oifs", {"grid": "TL159L91"}, lambda c: c.oifs.grid, "TL159L91"),
        ("nemo", {"grid": "ORCA2"}, lambda c: c.nemo.grid, "ORCA2"),
        ("eocene", eocene() | {"oifs": {"aerosols": True}}, lambda c: c.eocene.oifs.aerosols, True),
        ("eocene", eocene() | {"oasis": {"constant_sst": 285.5}}, lambda c: c.eocene.oasis.constant_sst, 285.5),
    ],
)
def test_override_default(tmp_path: Path, section, value, read, expected) -> None:
    assert read(load_config(write(tmp_path, minimal(tmp_path) | {section: value}))) == expected


def test_nemo_domain_overrides(tmp_path: Path) -> None:
    domain = nemo_domain() | {"tools_dir": "/tools", "staggering": {"source": "F"}}
    loaded = load_config(write(tmp_path, minimal(tmp_path) | {"nemo": {"domain": domain}})).nemo.domain
    assert loaded.tools_dir == "/tools"
    assert (loaded.staggering.source, loaded.staggering.target) == ("F", "T")


# --- placeholders ---------------------------------------------------------------------------------------------------


def test_placeholders_across_sections_and_defaults(tmp_path: Path) -> None:
    """A path may refer to another section's value, to a default and to a value that has placeholders itself."""
    raw = minimal(tmp_path) | {
        "nemo": {"domain": nemo_domain() | {"output_dir": "{tmpdir}/nemo-domain"}},
        "tmpdir": str(tmp_path / "work"),
        "eocene": {
            "output_dir": "{tmpdir}/eocene",
            "domain": {"from": "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"},
        },
    }
    config = load_config(write(tmp_path, raw))
    assert config.nemo.domain.output_dir == f"{tmp_path}/work/nemo-domain"
    assert config.eocene.domain.from_ == f"{tmp_path}/work/nemo-domain/nemo/domain/PALEORCA2/eocene"
    assert config.eocene.output_dir == f"{tmp_path}/work/eocene"
    assert config.expand("{eocene.domain.from}/domain_cfg.nc") == f"{config.eocene.domain.from_}/domain_cfg.nc"


def test_placeholder_with_number_value() -> None:
    values = {"nemo": {"domain": {"minimum_depth": 30, "note": "min {nemo.domain.minimum_depth} m"}}}
    assert resolve_placeholders(values)["nemo"]["domain"]["note"] == "min 30 m"


@pytest.mark.parametrize(
    "value, match",
    [
        ("{nemo.domain.outptu_dir}/x", r"unknown key 'nemo.domain.outptu_dir' in placeholder"),
        ("{input}/x", r"unknown key 'input'"),
        ("{tmpdir}/x", r"'tmpdir', which is not set"),
        ("{inputs}/x", r"refers to a section"),
    ],
)
def test_bad_placeholder(tmp_path: Path, value: str, match: str) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene() | {"output_dir": value}}
    with pytest.raises(ConfigError, match=match) as err:
        load_config(write(tmp_path, raw))
    assert "config.yml" in str(err.value)


def test_placeholder_cycle(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {
        "tmpdir": "{eocene.output_dir}/tmp",
        "eocene": {"output_dir": "{tmpdir}/out", "domain": {"from": "/d"}},
    }
    with pytest.raises(
        ConfigError,
        match=r"cycle: (tmpdir -> eocene\.output_dir -> tmpdir|eocene\.output_dir -> tmpdir -> eocene\.output_dir)",
    ):
        load_config(write(tmp_path, raw))


# --- errors -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["ece4_data", "herold"])
def test_missing_inputs_key(tmp_path: Path, key: str) -> None:
    raw = minimal(tmp_path)
    del raw["inputs"][key]
    with pytest.raises(ConfigError, match=rf"inputs\.{key}") as err:
        load_config(write(tmp_path, raw))
    assert "config.yml" in str(err.value)


@pytest.mark.parametrize("key", ["output_dir", "coords_ori", "source_grid", "minimum_depth", "steps", "bathymetries"])
def test_missing_nemo_domain_key(tmp_path: Path, key: str) -> None:
    domain = nemo_domain()
    del domain[key]
    with pytest.raises(ConfigError, match=rf"nemo\.domain\.{key}"):
        load_config(write(tmp_path, minimal(tmp_path) | {"nemo": {"domain": domain}}))


@pytest.mark.parametrize(
    "drop, key", [(("output_dir",), "eocene.output_dir"), (("domain",), "eocene.domain"), (("domain", "from"), "from")]
)
def test_missing_eocene_key(tmp_path: Path, drop: tuple, key: str) -> None:
    raw = minimal(tmp_path) | {"eocene": eocene()}
    section = raw["eocene"]
    for name in drop[:-1]:
        section = section[name]
    del section[drop[-1]]
    with pytest.raises(ConfigError, match=rf"missing key.*{key}"):
        load_config(write(tmp_path, raw))


def test_missing_schema(tmp_path: Path) -> None:
    raw = minimal(tmp_path)
    del raw["schema"]
    with pytest.raises(ConfigError, match="schema"):
        load_config(write(tmp_path, raw))


def test_missing_inputs_section(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="inputs"):
        load_config(write(tmp_path, {"schema": 2}))


def test_wrong_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported schema 3"):
        load_config(write(tmp_path, minimal(tmp_path) | {"schema": 3}))


def test_schema_1_lists_the_new_keys(tmp_path: Path) -> None:
    """A schema 1 file fails with one error naming each of its old keys and the new one."""
    raw = {
        "schema": 1,
        "paths": {"input": "/i", "output": "/o", "herold": "/h"},
        "tools": {"backend": "atos", "precomputed": {"domain": "/d"}},
        "nemo_domain": {"output_dir": "/x", "domaincfg_dir": "/t", "grids": {"target": "PALEORCA2"}},
    }
    with pytest.raises(ConfigError) as err:
        load_config(write(tmp_path, raw))
    message = str(err.value)
    assert "schema 1 configuration, no longer read" in message
    for old, new in [
        ("paths.input", "inputs.ece4_data"),
        ("paths.output", "eocene.output_dir"),
        ("tools.backend", "machine.name"),
        ("tools.precomputed.domain", "eocene.domain.from"),
        ("nemo_domain.domaincfg_dir", "nemo.domain.tools_dir"),
        ("nemo_domain.grids.target", "nemo.grid"),
    ]:
        assert any(old in line and new in line for line in message.splitlines()), (old, new)
    assert "grids.oifs " not in message  # only the keys of this file


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
        ("inputs", {"inptu": "/x"}, "inputs"),
        ("nemo", {"atmosphere": "TL63L31"}, "nemo"),
        ("machine", {"atos": {"modules": []}}, "machine.atos"),
        ("eocene", eocene() | {"oasis": {"sst": 1.0}}, "eocene.oasis"),
        ("eocene", eocene() | {"domain": {"from": "/d", "biuld": True}}, "eocene.domain"),
    ],
)
def test_unknown_key_in_section(tmp_path: Path, section: str, value: dict, where: str) -> None:
    raw = minimal(tmp_path)
    raw[section] = raw.get(section, {}) | value
    with pytest.raises(ConfigError, match=rf"unknown key\(s\) in '{where}'"):
        load_config(write(tmp_path, raw))


def test_unknown_nemo_domain_step(tmp_path: Path) -> None:
    domain = nemo_domain()
    domain["steps"]["bathymetri"] = True
    with pytest.raises(ConfigError, match="unknown step.*bathymetri"):
        load_config(write(tmp_path, minimal(tmp_path) | {"nemo": {"domain": domain}}))


@pytest.mark.parametrize("key", ["ece4_data", "herold"])
def test_read_only_directory_must_exist(tmp_path: Path, key: str) -> None:
    raw = minimal(tmp_path)
    raw["inputs"][key] = str(tmp_path / "missing")
    with pytest.raises(ConfigError, match=rf"inputs\.{key}.*not a directory"):
        load_config(write(tmp_path, raw))


@pytest.mark.parametrize(
    "section, value, key",
    [
        ("machine", {"name": "hpc"}, "machine.name"),
        ("machine", {"atos": {"profile": 1}}, "machine.atos.profile"),
        ("nemo", {"domain": nemo_domain() | {"staggering": {"source": "U"}}}, "nemo.domain.staggering.source"),
        ("nemo", {"domain": nemo_domain() | {"minimum_depth": "deep"}}, "nemo.domain.minimum_depth"),
        ("eocene", eocene() | {"domain": {"from": "/d", "build": "yes"}}, "eocene.domain.build"),
        ("eocene", eocene() | {"oifs": {"aerosols": "no"}}, "eocene.oifs.aerosols"),
        ("eocene", eocene() | {"oasis": {"constant_sst": "warm"}}, "eocene.oasis.constant_sst"),
    ],
)
def test_bad_value(tmp_path: Path, section: str, value: dict, key: str) -> None:
    raw = minimal(tmp_path) | {section: value}
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
    """The committed templates are valid once the read-only directories exist."""
    raw = yaml.safe_load((REPO / "configs" / template).read_text())
    raw["inputs"] = minimal(tmp_path)["inputs"]
    config = load_config(write(tmp_path, raw))
    assert [b["name"] for b in config.nemo.domain.bathymetries] == ["present_day", "eocene"]
    assert (config.oifs.data is not None) == (template == "atos.tmpl")  # the generator's inputs are on Atos
    assert config.eocene.domain.from_.endswith("/nemo/domain/PALEORCA2/eocene") or template == "laptop.tmpl"
