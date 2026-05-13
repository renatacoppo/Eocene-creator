#!/usr/bin/env python3
"""
Process NEMO PALEORCA2 bathymetry data by opening and closing specific regions.

This script takes an input directory containing bathymetry NetCDF files,
applies regional modifications, and saves the processed output.

IMPORTANT: if you change the way to interpolate, you will likely need to change the way to open and close regions,
as the indices of the grid points will change.
"""

import argparse
import os
import sys
import xarray as xr
import matplotlib.pyplot as plt


def set_minimum_bathymetry(xfield, min_land=30, min_depth=30):
    """Set all bathymetry values less than min_depth to min_depth."""
    xfield['bathy_metry'] = xfield['bathy_metry'].where(xfield['bathy_metry'] > min_land, 0)
    xfield['bathy_metry'] = xfield['bathy_metry'].where(
        ~((xfield['bathy_metry'] <= min_depth) & (xfield['bathy_metry'] > 0)), min_depth)
    return xfield

def close_region(xfield, region):
    """
    Close specific regions by setting bathymetry to 0.
    Order y, x. Slicing to be applied is the same as can be seen in ncview + 1 in the lat dimension
    Keep in mind that python slicing has to add one number to the end.  
    """
    if region == 'Caspian':
        xfield['bathy_metry'][:,  131:140,  156:159] = 0
    elif region == 'BlackSea':
        xfield['bathy_metry'][:,  133:138,  146:153] = 0
    elif region == 'Victoria':
        xfield['bathy_metry'][:,  98:101,  149] = 0
    elif region == "GreatLakes":
        xfield['bathy_metry'][:,  132:141,  86:94] = 0
    elif region == "Arctic":
        xfield['bathy_metry'][:,  165,  151:153] = 0
        xfield['bathy_metry'][:,  162:174,  64:78] = 0
    elif region == "Britain":
        xfield['bathy_metry'][:,  139,  131] = 0
        xfield['bathy_metry'][:,  141:143,  128:131] = 0
    elif region == "Cuba":
        xfield['bathy_metry'][:,  121,  92:96] = 0
    elif region == "Thailand":
        xfield['bathy_metry'][:,  104:116, 2] = 0
        xfield['bathy_metry'][:,  104:112, 3] = 0
        xfield['bathy_metry'][:,  88:90, 5] = 0
    elif region == "Italy":
        xfield['bathy_metry'][:,  134:136,  139] = 0
    elif region == "Barents":
        xfield['bathy_metry'][:,  153:155, 145:147] = 0
    elif region == "Indonesia":
        xfield['bathy_metry'][:,  123,  12] = 0
        xfield['bathy_metry'][:,  94,  18] = 0
        xfield['bathy_metry'][:,  89,  26] = 0
        xfield['bathy_metry'][:,  86,  10:13] = 0
    else:
        raise ValueError(f"Region '{region}' not recognized for closing.")
    return xfield

def average_depth(field, y_slice, x_slice, region_name):
    """Calculate the average depth in a given slice."""
    data = field['bathy_metry'][:, (y_slice-1):(y_slice+2), (x_slice-1):(x_slice+2)].values
    #print(f"Data for {region_name} at ({y_slice}, {x_slice}): {data}")
    value = data[data != 0].mean()
    print(f"Average depth for {region_name} at ({y_slice}, {x_slice}): {value}")
    field['bathy_metry'][:, y_slice, x_slice] = value
    return field

def open_region(xfield, region):
    """
    Open specific regions by setting bathymetry to specific depths.
    Order y, x. Slicing to be applied is the same as can be seen in ncview + 1 in the lat dimension
    Keep in mind that python slicing has to add one number to the end.
    """

    if region == "Gibraltair":
        xfield = average_depth(xfield, 129, 132, region)
    elif region == "RedSea":
        xfield = average_depth(xfield, 117, 154, region)
        xfield = average_depth(xfield, 117, 153, region)
    elif region == "Italy":
        xfield = average_depth(xfield, 133, 140, region)
        xfield = average_depth(xfield, 130, 139, region)
    elif region == "Bering":
        xfield = average_depth(xfield, 151, 47, region)
    elif region == "Arctic":
        xfield = average_depth(xfield, 166, 60, region)
    elif region == "Baltic":
        xfield = average_depth(xfield, 143, 138, region)
        xfield = average_depth(xfield, 144, 139, region)
    elif region == "Arctic":
        xfield = average_depth(xfield, 173, 143, region)
        xfield = average_depth(xfield, 173, 144, region)
    elif region == "Japan":
        xfield = average_depth(xfield, 129, 16, region)
    elif region == "Indonesia":
        xfield = average_depth(xfield, 115, 12, region)
        xfield = average_depth(xfield, 101, 11, region)
        xfield = average_depth(xfield, 102, 11, region)
        xfield = average_depth(xfield, 105, 15, region)
        xfield = average_depth(xfield, 106, 15, region)
        xfield = average_depth(xfield, 94, 16, region)
        xfield = average_depth(xfield, 86, 15, region)
        xfield = average_depth(xfield, 81, 41, region)
        xfield = average_depth(xfield, 96, 7, region)
    elif region == "Spain":
        xfield = average_depth(xfield, 134, 128, region)
    elif region == "Madagascar":
        xfield = average_depth(xfield, 81, 154, region)
    else:
        raise ValueError(f"Region '{region}' not recognized for opening.")
    return xfield


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Process NEMO bathymetry data by opening and closing specific regions"
    )
    parser.add_argument(
        "input_dir",
        type=str,
        help="Input directory containing bathymetry NetCDF files"
    )
    parser.add_argument(
        "--infile",
        type=str,
        default="PALEORCA_bathy_metry_from_eORCA1_nn.nc",
        help="Input bathymetry file name (default: PALEORCA_bathy_metry_from_eORCA1_nn.nc)"
    )
    parser.add_argument(
        "--outfile",
        type=str,
        default="PALEORCA_bathy_metry_from_eORCA1_nn_closed.nc",
        help="Output bathymetry file name (default: PALEORCA_bathy_metry_from_eORCA1_nn_closed.nc)"
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate a plot of the processed bathymetry"
    )
    parser.add_argument(
        '--orca2',
        type=str,
        help="optional path to the original ORCA2 bathymetry file, used to set the minimum bathymetry and for plotting"
    )
    parser.add_argument(
        '--orca1',
        type=str,
        help="optional path to the original eORCA1 bathymetry file, used for plotting"
    )
    return parser.parse_args()


def main():
    """Main processing function."""
    args = parse_arguments()
    
    # Validate input directory
    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory '{args.input_dir}' does not exist.")
        sys.exit(1)
    
    # Construct file paths
    input_file = os.path.join(args.input_dir, args.infile)
    output_file = os.path.join(args.input_dir, args.outfile)
    
    # Validate input file
    if not os.path.isfile(input_file):
        print(f"Error: Input file '{input_file}' does not exist.")
        sys.exit(1)
    
    print(f"Processing bathymetry data from: {input_file}")
    print(f"Output will be saved to: {output_file}")
    
    try:
        # Load the dataset
        print("Loading bathymetry data...")
        xfield = xr.open_dataset(input_file)

        #xfield = set_minimum_bathymetry(xfield, min_land=15, min_depth=30)
        
        # Apply regional closures (from the notebook workflow)
        print("Applying regional opening...")
        oregions = ['Arctic','Baltic', 'Gibraltair', 'RedSea',
                    'Madagascar', 'Italy', 'Japan', 'Bering', 'Indonesia', 'Spain']
        for region in oregions:
            print(f"Opening region: {region}")
            xfield = open_region(xfield, region)

        #cregions = ['Gibraltair', 'Hormuz', 'Adriatic', 'Baltic', 'Kara', 'Australia', 'Greenland', 'Black', 'Indonesia']
        cregions = ['Arctic', 'Caspian', 'Cuba', 'Britain', 'BlackSea',
                    'Victoria', 'GreatLakes', 'Thailand', 'Barents',
                     'Italy', 'Indonesia']
        for region in cregions:
            print(f"Closing region: {region}")
            xfield = close_region(xfield, region)

        # Re-open Red Sea as done in the notebook
        #xfield = open_region(xfield, 'RedSea')
        
        # Generate plot if requested
        if args.plot:
            print("Generating plot...")
            
            # Create land-sea mask from bathymetry
            mask = xr.where(xfield['bathy_metry'] > 0, 1, 0)
            
            # Load optional source files
            orca1_mask = None
            orca2_mask = None
            
            if args.orca1:
                print("Loading original eORCA1 bathymetry for comparison...")
                orca1 = xr.open_dataset(args.orca1)
                orca1_mask = xr.where(orca1['bathy_metry'] > 0, 1, 0)
            
            if args.orca2:
                print("Loading original ORCA2 bathymetry for comparison...")
                orca2 = xr.open_dataset(args.orca2)
                orca2_mask = xr.where(orca2['bathy_metry'] > 0, 1, 0)
            
            # Determine number of subplots
            num_plots = 1
            if orca1_mask is not None:
                num_plots += 1
            if orca2_mask is not None:
                num_plots += 1
            
            # Create comparison plot
            fig, axes = plt.subplots(1, num_plots, figsize=(10 * num_plots, 6))
            
            # Handle single vs multiple subplots
            if num_plots == 1:
                axes = [axes]
            
            plot_idx = 0
            
            # Plot eORCA1 if available
            if orca1_mask is not None:
                orca1_mask.plot(ax=axes[plot_idx], cmap='YlGnBu', add_colorbar=True, 
                               cbar_kwargs={'label': 'Land-Sea Mask', 'ticks': [0, 1]})
                axes[plot_idx].set_title('eORCA1 Land-Sea Mask (source)', fontsize=14, fontweight='bold')
                axes[plot_idx].set_xlabel('Longitude')
                axes[plot_idx].set_ylabel('Latitude')
                plot_idx += 1
            
            # Plot eORCA2 if available
            if orca2_mask is not None:
                orca2_mask.plot(ax=axes[plot_idx], cmap='YlGnBu', add_colorbar=True, 
                               cbar_kwargs={'label': 'Land-Sea Mask', 'ticks': [0, 1]})
                axes[plot_idx].set_title('ORCA2 Land-Sea Mask (reference)', fontsize=14, fontweight='bold')
                axes[plot_idx].set_xlabel('Longitude')
                axes[plot_idx].set_ylabel('Latitude')
                plot_idx += 1
            
            # Plot PALEORCA2 (always present)
            mask.plot(ax=axes[plot_idx], cmap='YlGnBu', add_colorbar=True, 
                     cbar_kwargs={'label': 'Land-Sea Mask', 'ticks': [0, 1]})
            axes[plot_idx].set_title('PALEORCA2 Land-Sea Mask (Processed)', fontsize=14, fontweight='bold')
            axes[plot_idx].set_xlabel('Longitude')
            axes[plot_idx].set_ylabel('Latitude')
            
            plt.tight_layout()
            
            # Determine output filename
            if orca1_mask is not None and orca2_mask is not None:
                plot_file = os.path.join(args.input_dir, "landsea_mask_comparison_orca1_orca2_paleorca2.png")
            elif orca2_mask is not None:
                plot_file = os.path.join(args.input_dir, "landsea_mask_comparison_orca2_paleorca2.png")
            elif orca1_mask is not None:
                plot_file = os.path.join(args.input_dir, "landsea_mask_comparison_orca1_paleorca2.png")
            else:
                plot_file = os.path.join(args.input_dir, "landsea_mask.png")
            
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            print(f"Plot saved to: {plot_file}")
            plt.close()
        
        # Save the processed dataset
        print("Saving processed data...")
        xfield.to_netcdf(output_file)
        
        print("Processing complete!")
        print(f"Processed bathymetry saved to: {output_file}")
        
    except Exception as e:
        print(f"Error during processing: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()