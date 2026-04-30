#!/bin/bash

# Resolve directory of this script so helper scripts in utils/ and domain-tools/ are found
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# folders for altai
if [ "$HOSTNAME" = "altai" ]; then
    BASEDIR=/Users/paolo/Desktop/PALEORCA
    COORDSDIR=$BASEDIR/coordinates
    DOMAINDIR=/Users/paolo/Desktop/PALEORCA/ECE4/nemo/domain
    HEROLDDIR=/Users/paolo/Desktop/PALEORCA/herold
    #ETOPODIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL #not used
    BATHYDIR=$BASEDIR/bathymetry
else
    # folders: DEFAULT: on Atos
    BASEDIR=/home/ccpd/hpcperm/PALEORCA
    COORDSDIR=$BASEDIR/coordinates
    DOMAINDIR=/lus/h2resw01/hpcperm/ccpd/ECE4-DATA/nemo/domain
    HEROLDDIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL/Herold_etal_2014
    #ETOPODIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL #not used
    BATHYDIR=$BASEDIR/bathymetry
    OUTPUTDIR=$BASEDIR/domain
    ECEDIR=/home/ccpd/hpcperm/ecearth4/revisions/main/sources/nemo-4.2/tools
fi


# options
TGTGRID=PALEORCA2
SRCGRID=eORCA1
staggering_source=T # assuming eORCA is on T grid
staggering_target=T # assuming PALEORCA is on T grid
minimum_depth=30 # minimum depth in meters, i.e. all values between 0 and 30 will be set to 30 meters

# flags
do_coordinates=false
do_present_day=false
do_eocene=false
do_fix_present_day=true
do_configure_domain=false
do_domain_cfg=false

if [ "$do_coordinates" = true ]; then
    echo "Generating coordinates and bounds for grid $TGTGRID"

    # Remove halo for coordinates from original Sepulchre coordinate, because coming from NEMO3.6 while we have NEMO4.2
    rm -f $COORDSDIR/$TGTGRID/coords_halo.nc
    cdo sethalo,-1,-1 $COORDSDIR/$TGTGRID/coords_ori.nc $COORDSDIR/$TGTGRID/coords_halo.nc

    # run the script to create the bounds from coordinates: grid staggering is controversial, producing F and T
    # run a script obtained from ECMWF, used in ClimateDT. It works with coordinates and mesh mask files.
    for staggering in T F ; do
        rm -f $COORDSDIR/$TGTGRID/coords_bounds_$staggering.nc
        echo "Generating bounds for staggering $staggering"
        python3 "$SCRIPT_DIR/utils/generate-orca-bounds.py" --stagg $staggering --no-level \
        $COORDSDIR/$TGTGRID/coords_halo.nc $COORDSDIR/$TGTGRID/coords_bounds_$staggering.nc
    done

    # run the script to create the bounds from meshmask for eORCA1 and ORCA2 (no need halo since NEMO 4.2)
    for grid in eORCA1 ; do
    for staggering in T F ; do
        rm -f $COORDSDIR/$grid/coords_bounds_$staggering.nc
        echo "Generating bounds for grid $grid and staggering $staggering"
        python3 generate-orca-bounds.py --stagg $staggering --no-level \
        $COORDSDIR/$grid/mesh_mask.nc $COORDSDIR/$grid/coords_bounds_$staggering.nc
    done
    done

    # from manual inspection the right staggering seems to be the T one, since it is the more aligned to what 
    # we can get as a comparison with the domain file for eocene obtained from Sepulchre.
fi


# PRESENT-DAY BATHYMETRY
# Final bathymetry is generated combining landsea mask and bathymetry from eORCA1 grid to the target grid, for both T staggering. 
# The landsea mask is obatined from eORCA1 (converting bathymetry to 0 and 1) by remapping the landsea mask with conservative remapping 
# (cannot use bilinear due to NaN generation), 
# setting then all values between 0 and 0.5 to 0 (land) and all values between 0.5 and 1 to 1 (sea). 
# Then we remap the bathymetry with nearest neighbor remappin (since all land value are zero and more correct interpolation will lead to coastal erosion), 
# and then we apply the land-sea mask, so that we mask the land points keep the sea points with their original value. 
# We also set all values between 0 and 30 to 30 meters, i.e. minimum depth, since this is what is seen in other NEMO files.
if [ "$do_present_day" = true ]; then
    mkdir -p $BATHYDIR/$TGTGRID

    for source_grid in $SRCGRID ; do
        for staggering in $staggering_source ; do
        echo "Extracting bathymetry from ${source_grid} grid and setting staggering $staggering"
        mkdir -p $BATHYDIR/${source_grid}
        cdo -setgrid,$COORDSDIR/${source_grid}/coords_bounds_${staggering}.nc \
            -selname,bathy_metry,nav_lon,nav_lat ${DOMAINDIR}/${source_grid}/domain_cfg.nc \
            $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering}.nc
        done
    done

    echo "Remapping bathymetry from eORCA1 grids to $TGTGRID grid making use of landsea mask as limit"
    for source_grid in $SRCGRID ; do
        for staggering_tgt in $staggering_target ; do
            staggering_src=$staggering_source

            # we generate a landsea mask with conservative remapping, continuosly made by 0 and 1 and the set what 
            # less than 0.5 to (land) and more than 0.5 to (sea)
            landseamask=$BATHYDIR/$TGTGRID/${source_grid}_${staggering_src}_land_sea_mask_remapcon_to_${TGTGRID}_${staggering_tgt}.nc
            rm -f $landseamask
            echo "Generating land-sea mask for $source_grid grid and staggering $staggering_tgt to $TGTGRID grid with $remap method"
            cdo setrtoc,0,0.5,0 -setrtoc,0.5,1,1 -remapcon,$COORDSDIR/$TGTGRID/coords_bounds_${staggering_src}.nc \
                -setrtoc,0.0001,10000,1 $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering_tgt}.nc \
                $landseamask

            # then we remap the bathymetry using nearest neighbor, but we mask the land points to 0 and keep the sea points with their original value
            # we also all values between 0 and 30 to 30 meters, i.e. minimum depth
            filename=$BATHYDIR/$TGTGRID/${source_grid}_${staggering_src}_bathy_metry_remapnn_to_${TGTGRID}_${staggering_tgt}.nc
            rm -f $filename
            echo "Remapping bathymetry from $source_grid grid and staggering $staggering_tgt to $TGTGRID grid with remapnn method"
            cdo setrtoc,0.00001,${minimum_depth},${minimum_depth} -mul $landseamask -remapnn,$COORDSDIR/$TGTGRID/coords_bounds_${staggering_src}.nc \
            $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering_tgt}.nc \
            $filename

            
        done
    done


fi

# same procedure as for present-day, but we use the Herold bathymetry as source, which is a paleobathymetry for the Eocene. 
# We only use bilinear remapping for the bathymetry, since it is more accurate (and we have orography here so no coastal erosion), 
# but we still use conservative remapping for the landsea mask to have a clear separation between land and sea. 
# As above, we also set all values between 0 and 30 to 30 meters, i.e. minimum depth.
if [ "$do_eocene" = true ]; then
    mkdir -p $BATHYDIR/$TGTGRID

    # generate herold bathymetry on the target grid, using different remapping methods
    mkdir -p $BATHYDIR/Herold
    #cdo chname,topo,bathy_metry -selname,topo,lon,lat ${HEROLDDIR}/herold_etal_eocene_topo_1x1.nc $BATHYDIR/Herold/bathy_metry_fromHerold.nc
    cdo chname,paleotopo,bathy_metry -selname,paleotopo ${HEROLDDIR}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc $BATHYDIR/Herold/bathy_metry_fromHerold.nc
    
    for staggering in $staggering_target ; do
        # we generate a landsea mask with conservative remapping, continuosly made by 0 and 1 and the set what 
        # less than 0.5 to (land) and more than 0.5 to (sea)
        landseamask=$BATHYDIR/$TGTGRID/HEROLD_land_sea_mask_remapcon_to_${TGTGRID}_${staggering}.nc
        rm -f $landseamask
        echo "Generating land-sea mask for HEROLD grid to $TGTGRID grid with remapcon method"
        cdo setrtoc,0,0.5,0 -setrtoc,0.5,1,1 -remapcon,$COORDSDIR/$TGTGRID/coords_bounds_${staggering}.nc \
        -setrtoc,-10000,-0.0001,1  -setrtoc,0,10000,0  $BATHYDIR/Herold/bathy_metry_fromHerold.nc \
        $landseamask

        filename=$BATHYDIR/${TGTGRID}/HEROLD_bathy_metry_remapbil_to_${TGTGRID}_${staggering}.nc
        rm -f $filename
        echo "Remapping bathymetry from HEROLD grid and staggering $staggering to $TGTGRID grid with rempabil method"
        # Herold bathymetry is positive, but NEMO bathymetry is negative, so we need to multiply by -1 and remove land points (set to 0)
        cdo setrtoc,0.00001,${minimum_depth},${minimum_depth} -mul $landseamask -mulc,-1 -setrtoc,0,10000,0 -remapbil,$COORDSDIR/$TGTGRID/coords_bounds_${staggering}.nc \
        $BATHYDIR/Herold/bathy_metry_fromHerold.nc \
        $filename
        #cdo setrtoc,0.00001,${minimum_depth},${minimum_depth} -mulc,-1 -setrtoc,0,10000,0 -remapbil,$COORDSDIR/$TGTGRID/coords_bounds_${staggering}.nc \
        #$BATHYDIR/Herold/bathy_metry_fromHerold.nc \
        
    done

    # # generate herold bathymetry on the target grid by remapping from HEROLD bathymetry, using different remapping methods (nearest neighbor, bilinear, conservative)
    # mkdir -p $BATHYDIR/ETOPO
    # cdo chname,z,bathy_metry -selname,z,lon,lat -remapbil,r360x180 ${ETOPODIR}/ETOPO_2022_v1_60s_N90W180_surface.nc $BATHYDIR/ETOPO/bathy_metry_fromETOPO.nc
    
    # for staggering in $staggering_target ; do
    #     for remap in $remap_methods ; do
    #         filename=$BATHYDIR/${TGTGRID}/ETOPO_bathy_metry_${remap}_to_${TGTGRID}_${staggering}.nc
    #         landseamask=$BATHYDIR/$TGTGRID/${source_grid}_${staggering_src}_land_sea_mask_${remap}_to_${TGTGRID}_${staggering_tgt}.nc
    #         rm -f $filename
    #         echo "Remapping bathymetry from ETOPO grid and staggering $staggering to $TGTGRID grid with $remap method"
    #         # ETOPO bathymetry is positive, but NEMO bathymetry is negative, so we need to multiply by -1 and remove land points (set to 0)
    #         cdo mul $landseamask -mulc,-1 -setrtoc,0,10000,0 -${remap},$COORDSDIR/$TGTGRID/coords_bounds_${staggering}.nc \
    #         $BATHYDIR/ETOPO/bathy_metry_fromETOPO.nc \
    #         $filename

        
    #     done
    # done
fi

# this is ad-hoc script to manipulate present-day bathymetry and ensure that the right straits are open/closed.
# IMPORTANT: any change in procedure to obtain the present-day bathymetry will imply manipulation here
if [ "$do_fix_present_day" = true ]; then
    echo "Fixing present-day bathymetry on $TGTGRID using a custom script to set verify land points"
    python3 process-paleorca-bathymetry.py $BATHYDIR/$TGTGRID --infile eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc \
    --outfile eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc --plot \
    --orca2 $DOMAINDIR/ORCA2/domain_cfg.nc #--orca1 $DOMAINDIR/eORCA1/domain_cfg.nc
fi

# configure the namelist for domainCFG for the target grid, using the bathymetry obtained from the previous steps, and the coordinates and bounds generated in the first step.
if [ "$do_configure_domain" = true ]; then
    echo "Configuring domain file for $TGTGRID grid and staggering $staggering_target for present-day bathymetry"
    python3 "$SCRIPT_DIR/domain-tools/config-namelist-domain.py" --bathymetry $BATHYDIR/$TGTGRID/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc \
    --coordinates $COORDSDIR/$TGTGRID/coords_bounds_${staggering_target}.nc \
    --output $ECEDIR/DOMAINcfg/namelist_cfg_present 

    echo "Configuring domain file for $TGTGRID grid and staggering $staggering_target for Eocene bathymetry"
    python3 "$SCRIPT_DIR/domain-tools/config-namelist-domain.py" --bathymetry $BATHYDIR/$TGTGRID/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc \
    --coordinates $COORDSDIR/$TGTGRID/coords_bounds_${staggering_target}.nc \
    --output $ECEDIR/DOMAINcfg/namelist_cfg_eocene 
fi

# run the domain cfg NEMO tool 
if [ "$do_domain_cfg" = true ]; then

    module reset
    module load prgenv/intel intel/2021.4.0 intel-mkl/19.0.5 hpcx-openmpi/2.9.0
    module load hdf5-parallel/1.12.2 netcdf4-parallel/4.9.1 ecmwf-toolbox/2023.04.1.0

    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$NETCDF4_PARALLEL_DIR/lib:$ECCODES_DIR/lib:$HDF5_DIR/lib:$HPCPERM/ecearth4/revisions/main/sources/oasis3-mct-5.2/arch_ecearth/lib

    cd $ECEDIR
    ./maketools -m ecearth -n DOMAINcfg clean
    cd $ECEDIR/DOMAINcfg

    cp namelist_cfg_present namelist_cfg
    ./make_domain_cfg.exe
    rm namelist_cfg

    echo "Generating maskutil file for $TGTGRID grid and staggering $staggering_target for present-day bathymetry"
    mkdir -p $OUTPUTDIR/$TGTGRID/present_day
    python3 "$SCRIPT_DIR/domain-tools/generate-mask-util.py" --src_dir $ECEDIR/DOMAINcfg --tgt_dir $OUTPUTDIR/$TGTGRID

    cp namelist_cfg_eocene namelist_cfg
    ./make_domain_cfg.exe
    rm namelist_cfg

    echo "Generating maskutil file for $TGTGRID grid and staggering $staggering_target for present-day bathymetry"
    mkdir -p $OUTPUTDIR/$TGTGRID/eocene
    python3 "$SCRIPT_DIR/domain-tools/generate-mask-util.py" --src_dir $ECEDIR/DOMAINcfg --tgt_dir $OUTPUTDIR/$TGTGRID

fi
