"""
Functions to compute Eocene-specific field:
- vegetation mapping


Authors
Renata Coppo (CNR-ISAC, Mar 2026)

"""

import re
import os
import tempfile
import shutil
import numpy as np
import xarray as xr
import subprocess
import xesmf as xe
import shutil
import tempfile
from cdo import Cdo
cdo = Cdo()

def _to_tll(field):
    """Force (time, lat, lon) ordering"""
    if set(field.dims) == {"time", "lat", "lon"}:
        return field.transpose("time", "lat", "lon")
    return field

def vegetation_zhang(field, var=None, herold_path=None, gaussian=None, **kwargs):
        """"
        Alternative method to create the ICMGG vegetation data for the Eocene OIFS.
        Replace the vegetation data with the one from the Herold data.
        Set the vegetation content to 1 for the dominant vegetation type and 0 to the others.
        Perform a mapping using the Zhang et al., 2021 criteria. 
        Always returns a Dataset with tvh, tvl, cvh, cvl.
        """
        # --- Load Herold biome data and remap ---
        herold_file = os.path.join(herold_path, "herold_etal_eocene_biome_1x1.nc")
        herold_remap = cdo.remapnn(
            f"N{gaussian}", input=herold_file
            #output=os.path.join(herold_path, "herold_etal_eocene_biome_1x1_N32.nc")
            )

        herold = xr.open_dataset(herold_remap)

        tvh = _to_tll(xr.full_like(field["tvh"], 0))
        tvl = _to_tll(xr.full_like(field["tvl"], 0))

        cvh = xr.zeros_like(tvh)
        cvl = xr.zeros_like(tvl)

        print("Initial shapes:")
        print(f"tvh: {tvh.shape}, tvl: {tvl.shape}, cvh: {cvh.shape}, cvl: {cvl.shape}")

        # === Biome to vegetation ID mappings ===
        biome_to_tvh = {
            1: 1, # Tropical forest → Evergreen broadleaf trees
            2: 2, # Warm-temperate forest → Evergreen needleleaf trees
            6: 3, # Temperate forest → Deciduous broadleaf
            7: 4, # Boreal forest → Deciduous needleleaf
        }

        biome_to_tvl = {
            3: 5, # Savanna → Tall grass
            4: 6, # Grassland → Short grass
            5: 7, # Desert → Semidesert
            8: 8, # Tundra → Tundra
            9: 8, # Dry Tundra → Tundra
        }

        for biome_id in range(1, 10): # assuming biome IDs go from 1 to 9
            mask = herold['eocene_biome_hp'] == biome_id
            # Expand mask to time dimension if present
            if 'time' in tvh.dims:
                mask = mask.expand_dims(time=tvh['time'])
            # Sanity check
            print(f"Biome {biome_id}: mask shape {mask.shape}")
            for arr_name, arr in zip(['tvh','tvl'], [tvh, tvl]):
                print(f"Array {arr_name} shape: {arr.shape}")
                if mask.shape != arr.shape:
                    print(f"WARNING: mask shape {mask.shape} != {arr_name} shape {arr.shape}")
    

            if biome_id in biome_to_tvh:
                tvh = xr.where(mask, biome_to_tvh[biome_id], tvh)
                cvh = xr.where(mask, 1.0, cvh)
            elif biome_id in biome_to_tvl:
                tvl = xr.where(mask, biome_to_tvl[biome_id], tvl)
                cvl= xr.where(mask, 1.0, cvl)
            else:
                print(f"Warning: biome {biome_id} not in mapping.")

        field = xr.Dataset({
            "tvh": tvh,
            "tvl": tvl,
            "cvh": cvh,
            "cvl": cvl,
        }, coords=field.coords, attrs=field.attrs)
        
        print(field)
        return field

def prepare_vegetation_zhang(self):
        """"
        Alternative method to create the ICMGG vegetation data for the Eocene OIFS.
        Replace the vegetation data with the one from the Herold data.
        Set the vegetation content to 1 for the dominant vegetation type and 0 to the others.
        Perform a mapping using the Zhang et al., 2021 criteria. 
        """


        herold_file = os.path.join(self.herold, "herold_etal_eocene_biome_1x1.nc")
        herold_remap = cdo.remapnn(
            f"N{self.gaussian}", 
            input=herold_file, 
            output=os.path.join(self.herold, "herold_etal_eocene_biome_1x1_N32.nc")
        )

        herold = xr.open_dataset(herold_remap)

        # Initialize arrays with the correct shape and coordinates
        tvh = _to_tll(xr.DataArray(np.zeros_like(field['tvh'].values), dims=field['tvh'].dims, coords=coords))
        tvl = _to_tll(xr.DataArray(np.zeros_like(field['tvl'].values), dims=field['tvl'].dims, coords=coords))
        cvh = xr.DataArray(np.zeros_like(tvh.values), dims=tvh.dims, coords=coords)
        cvl = xr.DataArray(np.zeros_like(tvl.values), dims=tvl.dims, coords=coords)

        # === Biome to vegetation ID mappings ===
        biome_to_tvh = {
            1: 1, # Tropical forest → Evergreen broadleaf trees
            2: 2, # Warm-temperate forest → Evergreen needleleaf trees
            6: 3, # Temperate forest → Deciduous broadleaf
            7: 4, # Boreal forest → Deciduous needleleaf
        }

        biome_to_tvl = {
            3: 5, # Savanna → Tall grass
            4: 6, # Grassland → Short grass
            5: 7, # Desert → Semidesert
            8: 8, # Tundra → Tundra
            9: 8, # Dry Tundra → Tundra
        }

        # === Create blank data arrays ===
        shape = herold['eocene_biome_hp'].shape
        coords = herold.coords

        tvh = xr.full_like(herold['eocene_biome_hp'], fill_value=0)
        tvl = xr.full_like(herold['eocene_biome_hp'], fill_value=0)
        cvh = xr.zeros_like(tvh)
        cvl = xr.zeros_like(tvl)

        for biome_id in range(1, 10): # assuming biome IDs go from 1 to 9
            mask = herold['eocene_biome_hp'] == biome_id

            if biome_id in biome_to_tvh:
                tvh = xr.where(mask, biome_to_tvh[biome_id], tvh)
                cvh = xr.where(mask, 1.0, cvh)
            elif biome_id in biome_to_tvl:
                tvl = xr.where(mask, biome_to_tvl[biome_id], tvl)
                cvl = xr.where(mask, 1.0, cvl)
            else:
                print(f"Warning: biome {biome_id} not in mapping.")

        # === Assemble final dataset ===
        vegetation_ds = xr.Dataset(
        {
            "tvh": tvh,
            "tvl": tvl,
            "cvh": cvh,
            "cvl": cvl
        },

        )

        # === Save ===
        output_path = os.path.join(self.odir_init, "ICMGG_vegetation.nc")
        if os.path.exists(output_path):
            os.remove(output_path)
        vegetation_ds.to_netcdf(output_path)

        return output_path

def prepare_vegetation(self):
    """"
    Create the ICMGG vegetation data for the Eocene OIFS.
    Replace the vegetation data with the one from the Herold data.
    Set the vegetation type to 0 for all types.
    Perform a mapping from present-day initial conditions
    """


    herold_file = os.path.join(self.herold, "herold_etal_eocene_biome_1x1.nc")
    herold_remap = cdo.remapnn(
        f"N{self.gaussian}", 
        input=herold_file, 
        output=os.path.join(self.herold, "herold_etal_eocene_biome_1x1_N32.nc")
    )
            
    icmgg_file = os.path.join(self.idir_init, "ICMGGECE4INIT")
    if os.path.exists(os.path.join(self.herold, "ICMGG.nc")):
        os.remove(os.path.join(self.herold, "ICMGG.nc"))
    icmgg_remap = cdo.setgridtype(
        "regularnn", 
        input=icmgg_file, 
        output=os.path.join(self.herold ,"ICMGG.nc"),
        options=NC4
    )

    herold = xr.open_dataset(herold_remap)
    icmgg = xr.open_dataset(icmgg_remap)

    biome_dict = {'tvh': {}, 'tvl': {}}
    for vegtype in ["tvh", "tvl"]:
        for i in range(1, 11):
            vegid = icmgg[vegtype].where(herold["prei_biome_hp"] == i).values
            vegid = vegid[~np.isnan(vegid)]
            unique, counts = np.unique(vegid, return_counts=True)
            if unique.size>0:
                biome_dict[vegtype][i] = int(unique[np.argmax(counts)])
            else:
                biome_dict[vegtype][i] = None

    eocene_icmgg = icmgg[['tvh', 'tvl', 'cvh', 'cvl']]
    for vegtype in ["tvh", "tvl"]:
        eocene_icmgg[vegtype] = eocene_icmgg[vegtype]*0
        for i in range(1, 11):
            eocene_icmgg[vegtype] = xr.where(
                herold['eocene_biome_hp'] == i,
                biome_dict[vegtype][i],
                eocene_icmgg[vegtype])
        
    for vegtype in ["cvh", "cvl"]:
        eocene_icmgg[vegtype] = eocene_icmgg[vegtype]*0

    if os.path.exists(os.path.join(self.odir_init, "ICMGG_vegetation.nc")):
        os.remove(os.path.join(self.odir_init, "ICMGG_vegetation.nc"))
    eocene_icmgg.to_netcdf(
        os.path.join(self.odir_init, "ICMGG_vegetation.nc")
    )

    return os.path.join(self.odir_init, "ICMGG_vegetation.nc")

