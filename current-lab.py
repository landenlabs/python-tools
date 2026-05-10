#!/usr/bin/env python3
"""Load Current Lab data"""
import os
import gzip
import shutil
import requests
import json
import argparse
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

#  Current Lab
#   Doc:
#     https://api.current-lab.com/
#     https://api.current-lab.com/#description/introduction
#
#   Website
#     https://current-lab.com/
#
#  API end points
#       https://api.current-lab.com/v1/auth/permissions
#       https://api.current-lab.com/v1/drift/forward
#       https://api.current-lab.com/v1/drift/reverse
#       https://api.current-lab.com/v1/gridded_files
#  Curl:
#    curl -sS "https://api.current-lab.com/v1/auth/permissions"  --header "X-API-Key: ${key}"
#


# Import plotting libraries if available
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# --- Constants ---
VERSION = "v2.32 (Feb-2026)"
BASE_URL = "https://api.current-lab.com/v1"
AUTH_CHECK_URL = f"{BASE_URL}/auth/permissions"
DRIFT_FORWARD_URL = f"{BASE_URL}/drift/forward"
DRIFT_REVERSE_URL = f"{BASE_URL}/drift/reverse"
GRID_URL = f"{BASE_URL}/gridded_files"

# Coarse World Map GeoJSON for offline/reliable borders
# Source: Natural Earth 1:110m resolution
GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-boundaries-world-110m/master/countries.geojson"
GEOJSON_FILE = "world_borders.json"

# Global variable to hold parsed arguments
args = None

def _api_request(api_key, url, method='POST', payload=None, stream=False):
    """A centralized function to handle API requests."""
    if args.verbose:
        print(f"Request URL: {url}", file=sys.stderr)
        if payload is not None:
            print(f"Post: {payload}", file=sys.stderr)

    headers = {'Content-Type': 'application/json'}
    if api_key != "NO_KEY_REQUIRED":
        headers['X-API-Key'] = api_key

    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, stream=stream)
        else:
            response = requests.post(url, headers=headers, json=payload, stream=stream)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as errh:
        print(f"HTTP Error: {errh}", file=sys.stderr)
    except requests.exceptions.ConnectionError as errc:
        print(f"Error Connecting: {errc}", file=sys.stderr)
    except requests.exceptions.Timeout as errt:
        print(f"Timeout Error: {errt}", file=sys.stderr)
    except requests.exceptions.RequestException as err:
        print(f"An Error Occurred: {err}", file=sys.stderr)
    sys.exit(1)

def parse_duration(duration_str):
    """Parses duration strings (e.g., '13H', '2D') into total hours."""
    try:
        unit = duration_str[-1].upper()
        value = int(duration_str[:-1])
        if unit == 'H':
            return value
        elif unit == 'D':
            return value * 24
        raise ValueError("Duration must end in 'H' (hours) or 'D' (days).")
    except (ValueError, IndexError):
        print(f"Error: Invalid duration format '{duration_str}'. Use format like '13H' or '2D'.", file=sys.stderr)
        sys.exit(1)

def get_api_key():
    """Retrieves API key from environment or command-line arguments."""
    if getattr(args, 'draw_bounding_box', False):
        api_key = os.getenv('CLAB_API_KEY') or args.api_key
        return api_key if api_key else "NO_KEY_REQUIRED"
        
    api_key = os.getenv('CLAB_API_KEY') or args.api_key
    if not api_key:
        print(f"Error: CLAB_API_KEY environment not set or --api_key not provided.", file=sys.stderr)
        sys.exit(1)
    return api_key

def download_map_asset():
    """Ensures the world border GeoJSON exists."""
    if not os.path.exists(GEOJSON_FILE):
        print(f"Downloading map asset (world borders)...")
        try:
            response = requests.get(GEOJSON_URL, timeout=10)
            response.raise_for_status()
            with open(GEOJSON_FILE, 'w') as f:
                f.write(response.text)
            print(f"Saved to {GEOJSON_FILE}")
        except Exception as e:
            print(f"Warning: Could not download map asset: {e}", file=sys.stderr)
            return False
    return True

def draw_bounding_box(api_key):
    """Generates a PNG image with country borders and a specified bounding box."""
    if not HAS_MATPLOTLIB:
        print("Error: matplotlib is required. Install with 'pip install matplotlib'.", file=sys.stderr)
        sys.exit(1)

    # Geographic bounding area (Map extent)
    map_lon_min, map_lon_max = -135.0, -70.0
    map_lat_min, map_lat_max = 21.0, 53.0

    print(f"Generating bounding box map (1024x512)...")

    try:
        # Create figure with 2:1 aspect ratio
        fig, ax = plt.subplots(figsize=(8, 4), dpi=128)
        
        # Load and Draw Borders from GeoJSON
        if download_map_asset():
            with open(GEOJSON_FILE, 'r') as f:
                gj = json.load(f)
            
            for feature in gj['features']:
                geom = feature['geometry']
                polygons = []
                if geom['type'] == 'Polygon':
                    polygons = [geom['coordinates']]
                elif geom['type'] == 'MultiPolygon':
                    polygons = geom['coordinates']
                
                for polygon in polygons:
                    for ring in polygon:
                        lons, lats = zip(*ring)
                        ax.plot(lons, lats, color='black', linewidth=0.5, alpha=0.7)

        # If we have an API key, fetch regions from the API
        if api_key != "NO_KEY_REQUIRED":
            check_data = fetch_check(api_key, verbose=False)
            if check_data and 'regions' in check_data:
                for region_item in check_data['regions']:
                    bbox = region_item.get('bounding_box')
                    if bbox and len(bbox) == 4:
                        # bbox format from JSON: [min_lon, min_lat, max_lon, max_lat]
                        min_lon, min_lat, max_lon, max_lat = bbox
                        rect = patches.Rectangle((min_lon, min_lat), 
                                                 max_lon - min_lon, 
                                                 max_lat - min_lat,
                                                 linewidth=1.5, edgecolor='red', facecolor='none', 
                                                 alpha=0.8, zorder=10)
                        ax.add_patch(rect)
                        # Optional: label the region
                        ax.text(min_lon, max_lat + 0.5, region_item.get('region', ''), 
                                color='red', fontsize=6, fontweight='bold')
        else:
            # Fallback/Default box if no API key provided
            rect_lon_min, rect_lon_max = -77.34, -74.5
            rect_lat_min, rect_lat_max = 36.4, 40.0
            rect = patches.Rectangle((rect_lon_min, rect_lat_min), 
                                     rect_lon_max - rect_lon_min, 
                                     rect_lat_max - rect_lat_min,
                                     linewidth=2, edgecolor='red', facecolor='none', zorder=10)
            ax.add_patch(rect)
        
        # Set limits and styling
        ax.set_xlim(map_lon_min, map_lon_max)
        ax.set_ylim(map_lat_min, map_lat_max)
        ax.set_aspect('equal')
        ax.set_title("Current Lab Data Area")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(True, linestyle='--', alpha=0.3)

        output_file = "bounding_box.png"
        plt.savefig(output_file, bbox_inches='tight', pad_inches=0.1)
        print(f"Successfully exported map to {output_file}")
        plt.close()

    except Exception as e:
        print(f"Failed to generate map: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()

def fetch_check(api_key, verbose=True):
    """Checks API credentials and returns the JSON response."""
    if verbose:
        print("Checking credentials...")
    response = _api_request(api_key, AUTH_CHECK_URL, method='GET')
    data = response.json()
    if verbose:
        print("--- API Response JSON ---")
        print(json.dumps(data, indent=4))
    return data

def fetch_drift_forward(api_key):
    """Fetches drift prediction data."""
    #
    #  Doc:  https://api.current-lab.com/#tag/drift/POST/v1/drift/forward
    #
    #   "start_time": "2026-02-17T04:00",
    #   "start_lon": -121.60,
    #   "start_lat": 34.90,
    #   "region": "west_coast_usa",
    #   "duration_hours": 48.0,
    #   "wind_drift_factor": 0.0   optional


    print("Loading drift data...")
    start_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    duration_hours = parse_duration(args.duration)
    payload = {
        "start_time": start_time,
        "start_lat": args.location[0],
        "start_lon": args.location[1],
        "duration_hours": duration_hours,
        "region": args.wind_region,
        "wind_drift_factor": 0,
        "source_currents": "auto",
        "source_wind": "auto"
    }

    START_TIME = time.time()
    response = _api_request(api_key, DRIFT_FORWARD_URL, payload=payload)
    print("--- API Response JSON ---")
    print(json.dumps(response.json(), indent=4))
    elapsed_time = time.time() - START_TIME
    print(f"Elapsed: {elapsed_time:5.0f}s", file=sys.stderr)

def fetch_grid(api_key):
    """Fetches gridded data, downloads, and decompresses if needed."""
    #
    #  Doc: https://api.current-lab.com/#tag/gridded-files/POST/v1/gridded_files
    #
    print("Loading grid data...")
    # start_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {
        "file_format": args.format,
        "region": args.wind_region,
        "product": "currents_surface"

        # Use the best available model if times are not provided:
        # "start_time": "2026-04-08T00:00:00Z",
        # "end_time": "2026-04-09T00:00:00Z",   single response if no end_time
        # "run_date": "latest"
    }
    response = _api_request(api_key, GRID_URL, payload=payload)
    response_data = response.json()
    
    if args.verbose:
        print("--- API Response JSON ---")
        print(json.dumps(response_data, indent=4))

    if 'files' in response_data and response_data['files']:
        for file_item in response_data['files']:
            download_url = file_item.get('url')
            file_name = file_item.get('file_name')

            if download_url and file_name:
                print(f"File: {file_name}")
                print(f"Downloading {file_name}...")
                download_response = _api_request(api_key, download_url, method='GET', stream=True)
                
                output_filename = file_name
                if file_name.endswith('.gz'):
                    output_filename = file_name.rsplit('.gz', 1)[0]
                    with gzip.open(download_response.raw, 'rb') as f_in, open(output_filename, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    print(f"Successfully downloaded and unzipped to {output_filename}")
                else:
                    with open(output_filename, 'wb') as f_out:
                        shutil.copyfileobj(download_response.raw, f_out)
                    print(f"Successfully downloaded to {output_filename}")
            else:
                print("Could not find 'url' or 'file_name' in the response.", file=sys.stderr)
    else:
        print("No 'files' found in the response.", file=sys.stderr)

def main():
    """Main function to parse arguments and execute commands."""
    global args
    parser = argparse.ArgumentParser(
        description=f"{VERSION}\nCurrent Lab data",
        epilog="""Example usage:
  current-lab.py --check
  
  current-lab.py --drift --location 34.90 -121.60 -D 2D -wr west_coast_usa
  
  current-lab.py --grid -wr west_coast_usa -f json
  current-lab.py --grid -wr west_coast_usa -f netcdf

  current-lab.py --draw-bounding-box

Wind Regions (wr):
  - northeast_us
  - west_coast_usa
  
Current Lab Information
  API Docs:
    https://api.current-lab.com
    https://api.current-lab.com/#description/introduction

  Website
    https://current-lab.com

  API end points:
    https://api.current-lab.com/v1/auth/permissions
    https://api.current-lab.com/v1/drift/forward
    https://api.current-lab.com/v1/drift/reverse
    https://api.current-lab.com/v1/gridded_files

""",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--drift', '-d', action='store_true', help='Fetch drift path, requires --location.')
    group.add_argument('--grid', '-g', action='store_true', help='Fetch world u,v grid.')
    group.add_argument('--check', '-c', action='store_true', help='Check API credentials.')
    group.add_argument('--draw-bounding-box', action='store_true', help='Export PNG image with country borders.')

    parser.add_argument("--verbose", "-v", action='store_true', help="Enable verbose output.")
    parser.add_argument("--api_key", help="API Key (or set CLAB_API_KEY environment variable).")
    parser.add_argument("--location", "-l", nargs=2, type=float, metavar=('LAT', 'LON'), help="Latitude and Longitude (e.g., 40.422 -73.719).")
    parser.add_argument("--wind_region", "-wr", help="Wind region name (e.g., west_coast_usa).")
    parser.add_argument("--duration", "-D", default="12H", help="Duration for drift prediction (e.g., 13H, 2D).")
    parser.add_argument("--format", "-f", default="json", choices=['json', 'netcdf', 'grib'], help="Grid format.")

    # Parse known args to flag unknown arguments first
    args, unknown = parser.parse_known_args()
    
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    # Manually check that at least one action is provided since group is now optional to catch typos first
    if not any([args.drift, args.grid, args.check, args.draw_bounding_box]):
        parser.error("one of the following arguments is required: --drift/-d, --grid/-g, --check/-c, --draw-bounding-box")

    api_key = get_api_key()

    try:
        if args.check:
            fetch_check(api_key, verbose=True)
        elif args.drift:
            if not args.location or not args.wind_region:
                parser.error("--drift requires --location and --wind_region.")
            fetch_drift_forward(api_key)
        elif args.grid:
            if not args.wind_region:
                parser.error("--grid requires --wind_region.")
            fetch_grid(api_key)
        elif args.draw_bounding_box:
            draw_bounding_box(api_key)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        sys.exit(0)
