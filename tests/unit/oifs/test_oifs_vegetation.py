"""Unit tests for ``vegetation.vegetation_zhang`` and the lookup tables in ``biomes``.

The Herold biome map is written directly on the target Gaussian grid (F4), so CDO's nearest-neighbour remapping is
the identity and every output point can be checked against the mapping table by hand.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from oifs_helpers import needs_cdo

from ecefast.paleo.eocene.oifs.biomes import hp_dict, land_cover_types
from ecefast.paleo.eocene.oifs.vegetation import prepare_vegetation, vegetation_zhang

pytestmark = pytest.mark.unit

GAUSSIAN = 4  # F4: 8 latitudes x 16 longitudes

# Herold biome name (biomes.hp_dict) -> (vegetation variable, IFS land cover name (biomes.land_cover_types), cover),
# as written in vegetation_zhang (Zhang et al. 2021 criteria). Ice (10) is outside the loop over biomes 1-9.
EXPECTED_MAPPING = {
    "tropical forest": ("tvh", "Evergreen broadleaf trees", 1.0),
    "warm temperate forest": ("tvh", "Evergreen needleleaf trees", 1.0),
    "temperate forest": ("tvh", "Deciduous broadleaf trees", 1.0),
    "boreal forest": ("tvh", "Deciduous needleleaf trees", 1.0),
    "savana": ("tvl", "Tall grass", 1.0),
    "grassland": ("tvl", "Grass", 1.0),
    "desert": ("tvl", "Semidesert", 0.3),
    "dry tundra": ("tvl", "Tundra", 1.0),
    "tundra": ("tvl", "Tundra", 1.0),
    "ice": (None, None, 0.0),
}


def test_biome_tables() -> None:
    assert sorted(int(k) for k in hp_dict) == list(range(1, 11))
    assert sorted(land_cover_types) == list(range(21))
    assert set(EXPECTED_MAPPING) == set(hp_dict.values())


def gaussian_grid(tmp_path: Path) -> xr.Dataset:
    """Coordinates of the regular Gaussian grid F<GAUSSIAN> as CDO writes them."""
    path = tmp_path / "grid.nc"
    subprocess.run(["cdo", "-s", "-f", "nc4", f"-const,0,F{GAUSSIAN}", str(path)], check=True)
    with xr.open_dataset(path) as ds:
        return ds.load()


@needs_cdo
def test_vegetation_zhang_mapping(tmp_path: Path) -> None:
    grid = gaussian_grid(tmp_path)
    nlat, nlon = grid.sizes["lat"], grid.sizes["lon"]
    # biome id per longitude column: 0 (NaN, ocean), 1..10, then 0..4 again
    biome_per_column = np.arange(nlon) % 11
    biome = np.repeat(biome_per_column[None, :].astype(float), nlat, axis=0)
    biome[biome == 0] = np.nan
    herold = tmp_path / "herold"
    herold.mkdir()
    xr.Dataset({"eocene_biome_hp": (("lat", "lon"), biome)}, coords={"lat": grid["lat"], "lon": grid["lon"]}).to_netcdf(
        herold / "herold_etal_eocene_biome_1x1.nc"
    )
    # input field as converted from GRIB: present-day values that must all be overwritten
    field = xr.Dataset(
        {
            v: (("time", "lat", "lon"), np.full((1, nlat, nlon), 99.0, dtype="float32"))
            for v in ("tvh", "tvl", "cvh", "cvl")
        },
        coords={"time": [0.0], "lat": grid["lat"], "lon": grid["lon"]},
        attrs={"source": "test"},
    )

    result = vegetation_zhang(field, var=["tvh", "tvl", "cvh", "cvl"], herold_path=str(herold), gaussian=GAUSSIAN)

    assert sorted(result.data_vars) == ["cvh", "cvl", "tvh", "tvl"]
    assert result.attrs == {"source": "test"}
    names_to_type = {name: number for number, name in land_cover_types.items()}
    for column, biome_id in enumerate(biome_per_column):
        values = {v: result[v].values[0, :, column] for v in ("tvh", "tvl", "cvh", "cvl")}
        expected = {"tvh": 0, "tvl": 0, "cvh": 0.0, "cvl": 0.0}
        if biome_id:
            variable, cover_name, cover = EXPECTED_MAPPING[hp_dict[str(biome_id)]]
            if variable is not None:
                expected[variable] = names_to_type[cover_name]
                expected["c" + variable[1:]] = cover
        for v, value in values.items():
            np.testing.assert_allclose(value, expected[v], err_msg=f"{v} for biome {biome_id}")
    # output vegetation types are IFS land cover types
    assert set(np.unique(result["tvh"].values)) | set(np.unique(result["tvl"].values)) <= set(land_cover_types)


@needs_cdo
@pytest.mark.xfail(
    strict=True, raises=NameError, reason="prepare_vegetation uses NC4, which vegetation.py never imports"
)
def test_prepare_vegetation_is_broken(tmp_path: Path) -> None:
    """``prepare_vegetation`` is unused: it fails on the undefined ``NC4`` (and would write into the Herold folder)."""
    grid = gaussian_grid(tmp_path)
    herold = tmp_path / "herold"
    herold.mkdir()
    shape = (grid.sizes["lat"], grid.sizes["lon"])
    xr.Dataset(
        {"eocene_biome_hp": (("lat", "lon"), np.ones(shape)), "prei_biome_hp": (("lat", "lon"), np.ones(shape))},
        coords={"lat": grid["lat"], "lon": grid["lon"]},
    ).to_netcdf(herold / "herold_etal_eocene_biome_1x1.nc")
    step = SimpleNamespace(herold=str(herold), idir_init=str(tmp_path), odir_init=str(tmp_path), gaussian=GAUSSIAN)
    prepare_vegetation(step)
