#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Draw wind barb plot from u,v grid from Current Lab"""

import json
import numpy as np
import matplotlib.pyplot as plt
import argparse


def histogram_speed(json_data, output_path):
    """Walk U,V grid, compute speed (m/s), bucket by truncated single decimal, save PNG."""
    meta = json_data['meta']['grid']
    nx, ny = meta['nx'], meta['ny']

    u_raw = json_data['data']['u']
    v_raw = json_data['data']['v']

    # Build float arrays — None entries mark missing/land cells
    u_flat = np.array([x if x is not None else np.nan for x in u_raw], dtype=float)
    v_flat = np.array([x if x is not None else np.nan for x in v_raw], dtype=float)

    # Compute speed at every valid grid point
    speed_flat = np.sqrt(u_flat**2 + v_flat**2)
    valid = speed_flat[np.isfinite(speed_flat)]

    # Truncate to one decimal place (floor toward zero, not round)
    truncated = np.trunc(valid * 10.0) / 10.0

    # Count occurrences of each truncated value
    values, counts = np.unique(truncated, return_counts=True)

    # Plot histogram as a bar chart
    fig, ax = plt.subplots(figsize=(14, 6))
    bar_width = 0.09  # slightly narrower than 0.1 bucket to leave visible gaps
    ax.bar(values, counts, width=bar_width, align='edge', color='steelblue', edgecolor='none')

    ax.set_xlabel("Speed (m/s, truncated to 0.1)")
    ax.set_ylabel("Count")
    ax.set_title(
        f"Wind Speed Histogram\n"
        f"{json_data['meta'].get('time', '')}  |  "
        f"valid points: {len(valid):,}  |  "
        f"max speed: {valid.max():.2f} m/s"
    )
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Histogram saved to {output_path}  ({len(values)} unique buckets, {len(valid):,} valid points)")


def main():
    parser = argparse.ArgumentParser(description="Generate wind barb plots from UV grid data.")
    parser.add_argument("--scale", type=float, default=20.0, help="Scaling factor to make small values visible")
    parser.add_argument("--skip", type=int, default=30, help="Downsampling factor")
    parser.add_argument("--input", '-i', type=str, default="uv.json", help="Input U,V JSON grid values in meters per second")
    parser.add_argument("--output", '-o', type=str, default="wind_barb.png", help="Output png image of grid rendered to wind barbs")
    parser.add_argument("--histogram-speed", action='store_true', help="Output a histogram image of wind speed in meters/second")
    args = parser.parse_args()

    # 1. Load the JSON data
    with open(args.input, 'r') as f:
        json_data = json.load(f)

    meta = json_data['meta']['grid']
    nx, ny = meta['nx'], meta['ny']

    if args.histogram_speed:
        histogram_speed(json_data, args.output)
    else:
        # 2. Reshape and Scale
        # Small values like 0.04 m/s need significant scaling to trigger flags
        u = np.array(json_data['data']['u'], dtype=float).reshape((ny, nx)) * args.scale
        v = np.array(json_data['data']['v'], dtype=float).reshape((ny, nx)) * args.scale

        # 3. Handle Grid Coordinates
        x = np.linspace(meta['lon_min'], meta['lon_max'], nx)
        y = np.linspace(meta['lat_min'], meta['lat_max'], ny)
        lon_grid, lat_grid = np.meshgrid(x, y)

        # 4. Downsampling
        s = args.skip
        skip_slice = (slice(None, None, s), slice(None, None, s))

        # 5. Plotting with Barb Adjustments
        plt.figure(figsize=(12, 10))

        # Use barb_increments to ensure flags show up even for smaller scaled values
        # Standard is 5, 10, 50. Here we lower them if the scale is low.
        plt.barbs(lon_grid[skip_slice], lat_grid[skip_slice],
                  u[skip_slice], v[skip_slice],
                  length=7,
                  pivot='middle',
                  color='darkblue',
                  barb_increments=dict(half=1, full=2, flag=10))  # Custom thresholds

        plt.title(f"Wind Barb Map (Scale: {args.scale}x)\nValues: {json_data['meta'].get('units', 'm/s')}")
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.grid(alpha=0.3)

        plt.savefig(args.output, dpi=300)
        print(f"Plot saved to {args.output}. Consider using --scale or --skip")


if __name__ == "__main__":
    main()
