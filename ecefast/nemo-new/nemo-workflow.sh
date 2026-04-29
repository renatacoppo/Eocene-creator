#!/bin/bash
module load cdo

# folders
BASEDIR=/home/ccpd/hpcperm/PALEORCA
COORDSDIR=$BASEDIR/coordinates
DOMAINDIR=/lus/h2resw01/hpcperm/ccpd/ECE4-DATA/nemo/domain
HEROLDDIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL/Herold_etal_2014
ETOPODIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL
BATHYDIR=$BASEDIR/bathymetry

# options
TGTGRID=PALEORCA2
staggering_source=T # assuming eORCA is on T grid
staggering_target=T # assuming PALEORCA is on T grid
#remap_methods="remapnn remapbil remapcon"
remap_methods="remapbil" #assuming remapbil is the best method

# flags
do_coordinates=false
do_interpolation=true
do_fix_present_bathy=false

if [ "$do_coordinates" = true ]; then
    echo "Generating coordinates and bounds for grid $TGTGRID"

    # Remove halo for coordinates from original Sepulchre coordinate, because coming from NEMO3.6 
    rm -f $COORDSDIR/$TGTGRID/coords_halo.nc
    cdo sethalo,-1,-1 $COORDSDIR/$TGTGRID/coords_ori.nc $COORDSDIR/$TGTGRID/coords_halo.nc

    # run the script to create the bounds from coordinates: grid staggering is controversial, using T grid here
    for staggering in T F ; do
        rm -f $COORDSDIR/$TGTGRID/coords_bounds_$staggering.nc
        echo "Generating bounds for staggering $staggering"
        python3 generate-orca-bounds.py --stagg $staggering --no-level \
        $COORDSDIR/$TGTGRID/coords_halo.nc $COORDSDIR/$TGTGRID/coords_bounds_$staggering.nc
    done

    # run the script to create the bounds from meshmask for eORCA1 and ORCA2 (no need halo since NEMO 4.2)
    for grid in eORCA1 ORCA2 ; do
    for staggering in T F ; do
        rm -f $COORDSDIR/$grid/coords_bounds_$staggering.nc
        echo "Generating bounds for grid $grid and staggering $staggering"
        python3 generate-orca-bounds.py --stagg $staggering --no-level \
        $COORDSDIR/$grid/mesh_mask.nc $COORDSDIR/$grid/coords_bounds_$staggering.nc
    done
    done

fi

# generate bathymetry on the target grid by remapping from eORCA1 and ORCA2 bathymetry, using different remapping methods (nearest neighbor, bilinear, conservative)
if [ "$do_interpolation" = true ]; then
    for source_grid in eORCA1 ; do
        for staggering in $staggering_source ; do
        echo "Extracting bathymetry from ${source_grid} grid and setting staggering $staggering"
        mkdir -p $BATHYDIR/${source_grid}
        cdo -setgrid,$COORDSDIR/${source_grid}/coords_bounds_${staggering}.nc \
            -selname,bathy_metry,nav_lon,nav_lat ${DOMAINDIR}/${source_grid}/domain_cfg.nc \
            $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering}.nc
        done
    done

    echo "Remapping bathymetry from eORCA1 grids to $TGTGRID grid"
    for source_grid in eORCA1 ; do
        for staggering_tgt in $staggering_target ; do
            staggering_src=$staggering_source
            #for remap in $remap_methods ; do
            # Remap bathymetry with different methods
            mkdir -p $BATHYDIR/$TGTGRID
            landseamask=$BATHYDIR/$TGTGRID/${source_grid}_${staggering_src}_land_sea_mask_remapcon_to_${TGTGRID}_${staggering_tgt}.nc
            rm -f $landseamask
            echo "Generating land-sea mask for $source_grid grid and staggering $staggering_tgt to $TGTGRID grid with $remap method"
            cdo setrtoc,0,0.5,0 -setrtoc,0.5,1,1 -remapcon,$COORDSDIR/$TGTGRID/coords_bounds_${staggering_src}.nc \
                -setrtoc,0.0001,10000,1 $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering_tgt}.nc \
                $landseamask

            filename=$BATHYDIR/$TGTGRID/${source_grid}_${staggering_src}_bathy_metry_remapnn_to_${TGTGRID}_${staggering_tgt}.nc
            rm -f $filename
            echo "Remapping bathymetry from $source_grid grid and staggering $staggering_tgt to $TGTGRID grid with remapnn method"
            cdo mul $landseamask -remapnn,$COORDSDIR/$TGTGRID/coords_bounds_${staggering_src}.nc \
            $BATHYDIR/${source_grid}/${source_grid}_bathy_metry_${staggering_tgt}.nc \
            $filename

            #done
            
        done
    done

    # generate herold bathymetry on the target grid by remapping from HEROLD bathymetry, using different remapping methods (nearest neighbor, bilinear, conservative)
    mkdir -p $BATHYDIR/Herold
    cdo chname,topo,bathy_metry -selname,topo,lon,lat ${HEROLDDIR}/herold_etal_eocene_topo_1x1.nc $BATHYDIR/Herold/bathy_metry_fromHerold.nc
    
    for staggering in $staggering_target ; do
        for remap in $remap_methods ; do
            filename=$BATHYDIR/${TGTGRID}/HEROLD_bathy_metry_${remap}_to_${TGTGRID}_${staggering}.nc
            rm -f $filename
            echo "Remapping bathymetry from HEROLD grid and staggering $staggering to $TGTGRID grid with $remap method"
            # Herold bathymetry is positive, but NEMO bathymetry is negative, so we need to multiply by -1 and remove land points (set to 0)
            cdo mulc,-1 -setrtoc,0,10000,0 -${remap},$COORDSDIR/$TGTGRID/coords_bounds_${staggering}.nc \
            $BATHYDIR/Herold/bathy_metry_fromHerold.nc \
            $filename
        done
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

if [ "$do_fix_present_bathy" = true ]; then
    echo "Fixing present-day bathymetry on $TGTGRID using a custom script to set verify land points"
    python3 process-paleorca-bathymetry.py $BATHYDIR/$TGTGRID --infile eORCA1_T_bathy_metry_remapbil_to_PALEORCA2_T.nc \
    --outfile eORCA1_T_bathy_metry_remapbil_to_PALEORCA2_T_corrected.nc --plot
fi

#
# remap bathymetry from eORCA1 to PALEORCA grid using nearest neighbor
#source_grid=eORCA1
#DOMAINDIR=/lus/h2resw01/hpcperm/ccpd/ECE4-DATA/nemo/domain
#GRIDDIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL/ORCA
#OUTPUTDIR=/lus/h2resw01/hpcperm/ccpd/EPOCHAL/PALEORCA-output
