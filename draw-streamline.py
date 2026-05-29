#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Draw streamline wind path of wind u,v grid from Current Lab"""

import json
import numpy as np
import matplotlib.pyplot as plt

def main():
    # 1. Load the JSON data
    try:
        with open('uv.json', 'r') as f:
            json_data = json.load(f)
    except FileNotFoundError:
        print("Error: 'uv.json' not found.")
        return

    # 2. Extract Grid Metadata
    meta = json_data['meta']['grid']
    nx = meta['nx']
    ny = meta['ny']
    lon_min, lon_max = meta['lon_min'], meta['lon_max']
    lat_min, lat_max = meta['lat_min'], meta['lat_max']
    
    # 3. Extract u and v components
    # Convert lists to numpy arrays and reshape to (rows, cols)
    # Using dtype=float automatically converts 'None' values to 'NaN'
    u = np.array(json_data['data']['u'], dtype=float).reshape((ny, nx))
    v = np.array(json_data['data']['v'], dtype=float).reshape((ny, nx))

    # 4. Create coordinate vectors for the grid
    x = np.linspace(lon_min, lon_max, nx)
    y = np.linspace(lat_min, lat_max, ny)

    # 5. Generate the Streamline Plot
    plt.figure(figsize=(12, 9))
    
    # Calculate magnitude for coloring (optional, enhances visualization)
    magnitude = np.sqrt(u**2 + v**2)
    
    # Create streamlines
    # density=2 increases the number of lines; color can be a constant or based on magnitude
    strm = plt.streamplot(x, y, u, v, color=magnitude, linewidth=1, cmap='viridis', density=1.5*2)
    
    # Add styling and labels
    plt.colorbar(strm.lines, label=f"Velocity ({json_data['meta'].get('units', 'm/s')})")
    plt.title(f"Streamline Map: {json_data['meta'].get('type', 'Vector Field')}\n"
              f"Time: {json_data['meta'].get('time', 'N/A')}")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.grid(alpha=0.3)

    # 6. Save the result
    output_filename = 'streamlines.png'
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    print(f"Successfully saved streamline plot to {output_filename}")

if __name__ == "__main__":
    main()
    
