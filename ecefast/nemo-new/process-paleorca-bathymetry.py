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
    Order y, x. Slicing to be applied is the same as can be seen in ncview
    Keep in mind that python slicing has to add one number to the end.  
    """
    if region == 'Caspian':
        xfield['bathy_metry'][:,  131:140,  156:159] = 0
    if region == 'BlackSea':
        xfield['bathy_metry'][:,  133:138,  146:153] = 0
    if region == 'Victoria':
        xfield['bathy_metry'][:,  98:101,  149] = 0
    if region == "GreatLakes":
        xfield['bathy_metry'][:,  132:141,  86:94] = 0
    if region == "Arctic":
        xfield['bathy_metry'][:,  165,  151:153] = 0
        xfield['bathy_metry'][:,  162:174,  61:78] = 0
    if region == "Britain":
        xfield['bathy_metry'][:,  139,  131] = 0
        xfield['bathy_metry'][:,  141:143,  128:131] = 0
    if region == "Cuba":
        xfield['bathy_metry'][:,  121,  92:96] = 0
    if region == "Thailand":
        xfield['bathy_metry'][:,  104:116, 2] = 0
        xfield['bathy_metry'][:,  104:112, 3] = 0
        xfield['bathy_metry'][:,  88:90, 5] = 0

    if region == "Italy":
        xfield['bathy_metry'][:,  134:136,  139] = 0
    if region == "Barents":
        xfield['bathy_metry'][:,  153:155, 145:147] = 0
    if region == "Indonesia":
        xfield['bathy_metry'][:,  123,  12] = 0
        xfield['bathy_metry'][:,  94,  18] = 0
        xfield['bathy_metry'][:,  89,  26] = 0
        xfield['bathy_metry'][:,  86,  10:13] = 0
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
    Order y, x. Slicing to be applied is the same as can be seen in ncview
    Keep in mind that python slicing has to add one number to the end.
    """

    if region == "Gibraltair":
        xfield = average_depth(xfield, 129, 132, region)
    if region == "RedSea":
        xfield = average_depth(xfield, 117, 154, region)
        xfield = average_depth(xfield, 117, 153, region)
    if region == "Italy":
        xfield = average_depth(xfield, 133, 140, region)
        xfield = average_depth(xfield, 130, 139, region)
    if region == "Bering":
        xfield = average_depth(xfield, 151, 47, region)
    if region == "Baltic":
        xfield = average_depth(xfield, 143, 138, region)
        xfield = average_depth(xfield, 144, 139, region)
    if region == "Arctic":
        xfield = average_depth(xfield, 173, 143, region)
        xfield = average_depth(xfield, 173, 144, region)
    if region == "Japan":
        xfield = average_depth(xfield, 129, 16, region)
    if region == "Indonesia":
        xfield = average_depth(xfield, 115, 12, region)
        xfield = average_depth(xfield, 101, 11, region)
        xfield = average_depth(xfield, 102, 11, region)
        xfield = average_depth(xfield, 105, 15, region)
        xfield = average_depth(xfield, 106, 15, region)
        xfield = average_depth(xfield, 94, 16, region)
        xfield = average_depth(xfield, 86, 15, region)
        xfield = average_depth(xfield, 81, 41, region)
        xfield = average_depth(xfield, 96, 7, region)

    # if region == "Kara":
    #     xfield['bathy_metry'][:,  165,  149] = 25.
    #     xfield['bathy_metry'][:,  165,  152] = 25.
    # if region == "Australia":
    #     xfield['bathy_metry'][:,  83:84,  23] = 100.
    # if region == "Greenland":
    #     xfield['bathy_metry'][:,  168,  121] = 300.
    # if region == "Black":
    #     xfield['bathy_metry'][:,  133,  145] = 200.
    # if region == "Indonesia":
    #     xfield['bathy_metry'][:,  102,  11] = 200.
    
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
        oregions = ['Arctic','Baltic', 'Gibraltair', 'RedSea', 'Italy', 'Japan', 'Bering', 'Indonesia']
        for region in oregions:
            print(f"Opening region: {region}")
            xfield = open_region(xfield, region)

        #cregions = ['Gibraltair', 'Hormuz', 'Adriatic', 'Baltic', 'Kara', 'Australia', 'Greenland', 'Black', 'Indonesia']
        cregions = ['Arctic', 'Caspian', 'Cuba', 'Britain', 'BlackSea', 'Victoria', 'GreatLakes', 'Thailand', 'Barents', 'Italy', 'Indonesia']
        for region in cregions:
            print(f"Closing region: {region}")
            xfield = close_region(xfield, region)

        # Re-open Red Sea as done in the notebook
        #xfield = open_region(xfield, 'RedSea')
        
        # Generate plot if requested
        if args.plot:
            print("Generating plot...")
            plt.figure(figsize=(12, 8))
            xfield['bathy_metry'].plot(vmax=1)
            plt.title("Processed Bathymetry Data")
            plot_file = os.path.join(args.input_dir, "bathymetry_plot.png")
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