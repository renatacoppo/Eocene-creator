"""Unit tests for the ``domain`` and ``nemo`` steps of the Eocene pipeline."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.core.config import ConfigError, load_config
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context
from ecefast.paleo.eocene.nemo.domain import EoceneDomain, check_vertical_grid
from ecefast.paleo.eocene.nemo.eoceneNEMO import EoceneNEMO
from synthetic import make_config

pytestmark = pytest.mark.unit


def vertical_grid(nz: int, e3t: np.ndarray | None = None) -> xr.Dataset:
    """A minimal domain_cfg with the vertical grid variables."""
    e3t = np.linspace(10.0, 500.0, nz) if e3t is None else e3t
    return xr.Dataset(
        {
            "nav_lev": ("z", np.cumsum(e3t).astype("float32")),
            "e3t_1d": (("time_counter", "z"), e3t[np.newaxis]),
        }
    )


# --- vertical grid check -------------------------------------------------------------------------------------------


def test_vertical_grid_equal_passes() -> None:
    check_vertical_grid(vertical_grid(31), vertical_grid(31), "present.nc", "eocene.nc")


def test_vertical_grid_different_number_of_levels_fails() -> None:
    with pytest.raises(ValueError) as err:
        check_vertical_grid(vertical_grid(31), vertical_grid(75), "pd/domain_cfg.nc", "eo/domain_cfg.nc")
    message = str(err.value)
    assert "pd/domain_cfg.nc" in message and "eo/domain_cfg.nc" in message
    assert "31 levels" in message and "75 levels" in message
    assert "nav_lev" in message and "e3t_1d" in message


def test_vertical_grid_same_count_different_e3t_fails() -> None:
    e3t = np.linspace(10.0, 500.0, 31)
    present = vertical_grid(31, e3t)
    eocene = present.copy(deep=True)
    eocene["e3t_1d"][0, -1] += 1.0
    with pytest.raises(ValueError, match="e3t_1d") as err:
        check_vertical_grid(present, eocene, "present.nc", "eocene.nc")
    assert "present.nc" in str(err.value) and "eocene.nc" in str(err.value)
    assert "nav_lev" not in str(err.value).split("Different:")[1]


@pytest.mark.parametrize("variable", ["nav_lev", "e3t_1d"])
def test_vertical_grid_rounding_difference_passes(variable: str) -> None:
    present = vertical_grid(31)
    eocene = present.copy(deep=True)
    eocene[variable] = eocene[variable].astype("float64") + 1e-9
    check_vertical_grid(present, eocene, "present.nc", "eocene.nc")


@pytest.mark.parametrize("variable", ["nav_lev", "e3t_1d"])
def test_vertical_grid_millimetre_difference_fails(variable: str) -> None:
    present = vertical_grid(31)
    eocene = present.copy(deep=True)
    eocene[variable] = eocene[variable].astype("float64") + 1e-3
    with pytest.raises(ValueError, match=f"Different: {variable} \\(max absolute difference 0.001 m"):
        check_vertical_grid(present, eocene, "present.nc", "eocene.nc")


# --- step declarations ---------------------------------------------------------------------------------------------


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    return Context(make_config(tmp_path, tmpdir=str(tmp_path / "tmp")))


def test_nemo_does_not_need_domain() -> None:
    assert "domain" not in EoceneNEMO.needs
    assert EoceneNEMO.needs == ["stage"]


@pytest.mark.parametrize("step", [EoceneNEMO, EoceneDomain])
def test_writes_under_output(step, ctx: Context) -> None:
    output = ctx.config.eocene.output_dir + "/"
    assert step.writes
    for template in step.writes:
        assert template.startswith("{eocene.output_dir}/")
        assert ctx.expand(template).startswith(output)
        ctx.check_writable(ctx.expand(template), step.name)


def test_nemo_writes_both_ocean_initial_states() -> None:
    names = [Path(t).name for t in EoceneNEMO.writes]
    assert "woa13-levitus-L31_woa-pi.nc" in names
    assert "woa13-levitus-L31_deepmip-30.nc" in names


# --- domain step on synthetic files --------------------------------------------------------------------------------


def make_domain_tree(ctx: Context, eocene_levels: int) -> None:
    """Present-day domain in the input tree, precomputed Eocene domain with ``eocene_levels`` levels."""
    present_dir = Path(ctx.expand("{inputs.ece4_data}/nemo/domain/{nemo.grid}"))
    present_dir.mkdir(parents=True)
    vertical_grid(31).to_netcdf(present_dir / "domain_cfg.nc")
    precomputed = Path(ctx.config.eocene.domain.from_)
    precomputed.mkdir()
    vertical_grid(eocene_levels).to_netcdf(precomputed / "domain_cfg.nc")
    xr.Dataset({"tmask": ("z", np.ones(eocene_levels))}).to_netcdf(precomputed / "maskutil.nc")


def test_domain_step_installs_and_checks(ctx: Context) -> None:
    make_domain_tree(ctx, eocene_levels=31)
    EoceneDomain.from_context(ctx).run()
    for template in EoceneDomain.writes:
        installed = Path(ctx.expand(template))
        assert installed.read_bytes() == (Path(ctx.config.eocene.domain.from_) / installed.name).read_bytes()


def test_domain_step_fails_on_mismatch(ctx: Context) -> None:
    make_domain_tree(ctx, eocene_levels=75)
    with pytest.raises(ValueError, match="31 levels"):
        EoceneDomain.from_context(ctx).run()


def test_domain_step_needs_the_domain_files(ctx: Context) -> None:
    with pytest.raises(PipelineError, match=r"missing in eocene.domain.from .*domain_cfg.nc, maskutil.nc"):
        EoceneDomain.from_context(ctx)


def test_domain_build_needs_a_machine_with_domaincfg(tmp_path: Path) -> None:
    """``eocene.domain.build: true`` with ``machine.name: local`` is refused when the config is read."""
    for name in ("input", "herold"):
        (tmp_path / name).mkdir()
    raw = {
        "schema": 2,
        "inputs": {"ece4_data": str(tmp_path / "input"), "herold": str(tmp_path / "herold")},
        "eocene": {"output_dir": str(tmp_path / "out"), "domain": {"from": str(tmp_path / "d"), "build": True}},
    }
    (tmp_path / "config.yml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="'eocene.domain.build: true'.*'machine.name: local'"):
        load_config(tmp_path / "config.yml")
