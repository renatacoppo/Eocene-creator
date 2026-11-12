"""Unit tests for the configuration loader (schema 1)."""

from pathlib import Path

import pytest
import yaml

from ecefast.core.config import ConfigError, load_config

pytestmark = pytest.mark.unit

REPO = Path(__file__).parents[2]


def minimal(tmp_path: Path) -> dict:
    """Smallest valid configuration, with existing input and herold directories."""
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "herold").mkdir(exist_ok=True)
    return {
        "schema": 1,
        "paths": {
            "input": str(tmp_path / "input"),
            "output": str(tmp_path / "out"),
            "herold": str(tmp_path / "herold"),
        },
    }


def nemo_domain() -> dict:
    return {
        "output_dir": "/out/domain",
        "coords_ori": "/data/coords_ori.nc",
        "mesh_mask": "/data/mesh_mask.nc",
        "grids": {"target": "PALEORCA2", "source": "eORCA1", "staggering_source": "T", "staggering_target": "T"},
        "parameters": {"minimum_depth": 30},
        "steps": {"coordinates": True, "bathymetry": True},
        "bathymetries": [{"name": "eocene", "enabled": True, "processor": "EoceneBathymetry", "source_file": "x.nc"}],
    }


def write(tmp_path: Path, config: dict) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_minimal_config_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, minimal(tmp_path)))
    assert config.paths.input == str(tmp_path / "input")
    assert config.paths.tmpdir is None
    assert config.tools.backend == "local"
    assert config.tools.precomputed.domain is None
    assert config.grids.oifs == "TL63L31"
    assert config.grids.nemo == "PALEORCA2"
    assert config.nemo_domain is None
    assert config.eocene.oifs.aerosols is False
    assert config.eocene.oasis.constant_sst == 290.0


def test_nemo_domain_section_loads_with_defaults(tmp_path: Path) -> None:
    raw = minimal(tmp_path) | {"nemo_domain": nemo_domain()}
    domain = load_config(write(tmp_path, raw)).nemo_domain
    assert domain.output_dir == "/out/domain"
    assert domain.domaincfg_dir is None
    assert domain.aliases == {}
    assert domain.bathymetries[0]["processor"] == "EoceneBathymetry"


@pytest.mark.parametrize(
    "section, key, value, read",
    [
        ("paths", "tmpdir", "/tmp/x", lambda c: c.paths.tmpdir),
        ("tools", "backend", "local", lambda c: c.tools.backend),
        ("tools", "precomputed", {"domain": "/d"}, lambda c: c.tools.precomputed.domain),
        ("grids", "oifs", "TL159L91", lambda c: c.grids.oifs),
        ("grids", "nemo", "ORCA2", lambda c: c.grids.nemo),
        ("eocene", "oifs", {"aerosols": True}, lambda c: c.eocene.oifs.aerosols),
        ("eocene", "oasis", {"constant_sst": 285.5}, lambda c: c.eocene.oasis.constant_sst),
    ],
)
def test_override_default(tmp_path: Path, section, key, value, read) -> None:
    raw = minimal(tmp_path)
    raw.setdefault(section, {})[key] = value
    expected = next(iter(value.values())) if isinstance(value, dict) else value
    assert read(load_config(write(tmp_path, raw))) == expected


def test_nemo_domain_overrides(tmp_path: Path) -> None:
    domain = nemo_domain() | {"domaincfg_dir": "/tools", "aliases": {"my_dir": "/x"}}
    loaded = load_config(write(tmp_path, minimal(tmp_path) | {"nemo_domain": domain})).nemo_domain
    assert loaded.domaincfg_dir == "/tools"
    assert loaded.aliases == {"my_dir": "/x"}


@pytest.mark.parametrize("key", ["input", "output", "herold"])
def test_missing_path_key(tmp_path: Path, key: str) -> None:
    raw = minimal(tmp_path)
    del raw["paths"][key]
    with pytest.raises(ConfigError, match=rf"paths\.{key}") as err:
        load_config(write(tmp_path, raw))
    assert "config.yml" in str(err.value)


@pytest.mark.parametrize(
    "key", ["output_dir", "coords_ori", "mesh_mask", "grids", "parameters", "steps", "bathymetries"]
)
def test_missing_nemo_domain_key(tmp_path: Path, key: str) -> None:
    domain = nemo_domain()
    del domain[key]
    with pytest.raises(ConfigError, match=rf"nemo_domain\.{key}"):
        load_config(write(tmp_path, minimal(tmp_path) | {"nemo_domain": domain}))


def test_missing_schema(tmp_path: Path) -> None:
    raw = minimal(tmp_path)
    del raw["schema"]
    with pytest.raises(ConfigError, match="schema"):
        load_config(write(tmp_path, raw))


def test_missing_paths_section(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="paths"):
        load_config(write(tmp_path, {"schema": 1}))


def test_wrong_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported schema 2"):
        load_config(write(tmp_path, minimal(tmp_path) | {"schema": 2}))


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
        ("paths", {"inptu": "/x"}, "paths"),
        ("grids", {"atmosphere": "TL63L31"}, "grids"),
        ("tools", {"precomputed": {"domian": "/d"}}, "tools.precomputed"),
        ("eocene", {"oasis": {"sst": 1.0}}, "eocene.oasis"),
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
        load_config(write(tmp_path, minimal(tmp_path) | {"nemo_domain": domain}))


@pytest.mark.parametrize("key", ["input", "herold"])
def test_read_only_directory_must_exist(tmp_path: Path, key: str) -> None:
    raw = minimal(tmp_path)
    raw["paths"][key] = str(tmp_path / "missing")
    with pytest.raises(ConfigError, match=rf"paths\.{key}.*not a directory"):
        load_config(write(tmp_path, raw))


@pytest.mark.parametrize(
    "section, value, key",
    [
        ("tools", {"backend": "hpc"}, "tools.backend"),
        ("eocene", {"oifs": {"aerosols": "no"}}, "eocene.oifs.aerosols"),
        ("eocene", {"oasis": {"constant_sst": "warm"}}, "eocene.oasis.constant_sst"),
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
    raw["paths"] |= minimal(tmp_path)["paths"]
    config = load_config(write(tmp_path, raw))
    assert [b["name"] for b in config.nemo_domain.bathymetries] == ["present_day", "eocene"]
