#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Draw wind u,v grid from Current Lab"""


import json
import numpy as np
import matplotlib.pyplot as plt
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Generate wind visualizations from UV grid data.")
    parser.add_argument("-o", "--output", choices=['streamline', 'barbs', 'combined', 'all'], 
                        default='all', help="Selection of output image(s)")
    parser.add_argument("--scale", type=float, default=20.0, 
                        help="Scaling factor for wind barbs to make small values visible")
    parser.add_argument("--skip", type=int, default=30, 
                        help="Grid downsampling factor for wind barbs")
    parser.add_argument("--density", type=float, default=1.5, 
                        help="Density of streamlines")
    args = parser.parse_args()

    # 1. Load the JSON data
    try:
        with open('uv.json', 'r') as f:
            json_data = json.load(f)
    except FileNotFoundError:
        print("Error: 'uv.json' not found.")
        sys.exit(1)

    # 2. Extract Metadata and Data
    meta = json_data['meta']['grid']
    nx, ny = meta['nx'], meta['ny']
    u_raw = np.array(json_data['data']['u'], dtype=float).reshape((ny, nx))
    v_raw = np.array(json_data['data']['v'], dtype=float).reshape((ny, nx))
    
    # 3. Handle Grid Coordinates
    x = np.linspace(meta['lon_min'], meta['lon_max'], nx)
    y = np.linspace(meta['lat_min'], meta['lat_max'], ny)
    lon_grid, lat_grid = np.meshgrid(x, y)

    # Prepare common plot elements
    units = json_data['meta'].get('units', 'm/s')
    time_str = json_data['meta'].get('time', 'N/A')
    
    # Define plotting modes
    modes = [args.output] if args.output != 'all' else ['streamline', 'barbs', 'combined']

    for mode in modes:
        plt.figure(figsize=(12, 10))
        magnitude = np.sqrt(u_raw**2 + v_raw**2)
        
        # --- Mode 1: Streamlines ---
        if mode in ['streamline', 'combined']:

            if mode == 'streamline':
                strm = plt.streamplot(x, y, u_raw, v_raw, color=magnitude,
                                      linewidth=1, cmap='viridis', density=args.density)
                plt.colorbar(strm.lines, label=f"Velocity ({units})")
                plt.title(f"Streamline Map\nTime: {time_str}")
            else:
                strm = plt.streamplot(x, y, u_raw, v_raw, color='red',
                                      linewidth=2, cmap='viridis', density=args.density)

        # --- Mode 2: Wind Barbs ---
        if mode in ['barbs', 'combined']:
            # Apply scaling for barbs
            u_scaled = u_raw * args.scale
            v_scaled = v_raw * args.scale
            s = args.skip
            skip_slice = (slice(None, None, s), slice(None, None, s))
            
            # Use custom increments so barbs show up for small scaled values
            plt.barbs(lon_grid[skip_slice], lat_grid[skip_slice], 
                      u_scaled[skip_slice], v_scaled[skip_slice], 
                      length=7, pivot='middle', color='black' if mode == 'combined' else 'darkblue',
                      barb_increments=dict(half=1, full=2, flag=10))
            
            if mode == 'barbs':
                plt.title(f"Wind Barb Map (Scale: {args.scale}x)\nTime: {time_str}")
        
        if mode == 'combined':
            plt.title(f"Combined Streamline & Wind Barb Map\nScale: {args.scale}x | Time: {time_str}")

        # Final touches
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.grid(alpha=0.3)
        
        filename = f"wind_{mode}.png"
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Saved: {filename}")
        plt.close()

if __name__ == "__main__":
    main()
