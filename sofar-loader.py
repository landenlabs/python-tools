#!/usr/bin/env python3
"""Load Sofar data with wildcard and multi-ID support"""

import re
import urllib.request
import urllib.parse
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
import os
import sys
import argparse

VERSION = "v1.30 (Mar-2026)"
START_TIME = time.time()
SPOTTER_IDS = {}
BASE_URL = 'https://api.sofarocean.com/api/'
WAVE_DATA_URL = BASE_URL + 'wave-data'
DEVICES_URL = BASE_URL + 'devices'
ARGS = None
TIMEOUT_SECONDS = 15
OUT_TIME_UTC = False

# -------------------------------------------------------
def to_datetime(ts):
    """Converts ISO format timestamp from Sofar JSON to datetime object."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None

# -------------------------------------------------------
def format_datetime(dt: datetime):
    if dt.tzinfo is None:
        assert "Missing Time Zone"
    target_dt = dt.astimezone(timezone.utc if OUT_TIME_UTC else None)
    return target_dt.strftime('%Y-%m-%d %H:%M %Z')

# -------------------------------------------------------
def make_request(url, verbose=False):
    api_key = os.getenv('SOFAR_API_KEY')
    request = urllib.request.Request(url, headers={'token': api_key})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if verbose:
                print(f"Request: {request.full_url}", file=sys.stderr)
            if response.status != 200:
                print(f" Error: {response.status}", file=sys.stderr)
                return None
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None

# -------------------------------------------------------
def get_buoy_list():
    """Returns a list of all available Spotter IDs for the account."""
    data = make_request(DEVICES_URL, verbose=ARGS.verbose)
    if not data:
        return []
    devices = data.get('data', {}).get('devices', [])
    return [d.get('spotterId') for d in devices if d.get('spotterId')]

# -------------------------------------------------------
def fetch_sofar_data(target_spotter_id=None):
    """Fetches and merges wave, wind, temp, and pressure data by timestamp."""
    verbose = ARGS.verbose
    csv = ARGS.csv

    now_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- Data Load Started: {now_ts} ({target_spotter_id}) ---", file=sys.stderr)

    # parser.add_argument('--filter', '-f', type=str, help='Filters, wind, temp, press (default is all)')

    f = (ARGS.filter or '').lower()
    include_all = not f or f.strip() in ('*', 'all')
    include_wave = include_all or 'wave' in f
    include_wind = include_all or 'wind' in f
    include_temp = include_all or 'temp' in f
    include_press = include_all or 'press' in f

    params = {'spotterId': target_spotter_id, 'limit': str(ARGS.limit)}
    params['includeWaves'] = 'true' if include_wave else 'false'
    params['includeWindData'] = 'true' if include_wind else 'false'
    if include_temp:
        params['includeSurfaceTempData'] = 'true'
    if include_press:
        params['includeBarometerData'] = 'true'

    url = f"{WAVE_DATA_URL}?{urllib.parse.urlencode(params)}"

    try:
        raw_data = make_request(url, verbose=verbose)
        if not raw_data:
            return

        if ARGS.verbose:
            print("--- API Response JSON ---")
            print(json.dumps(raw_data, indent=4))

        data = raw_data.get('data', {})
        merged_obs = {}

        def update_obs(data_list, fields_map):
            for item in data_list:
                ts = item.get('timestamp')
                if not ts: continue
                if ts not in merged_obs:
                    merged_obs[ts] = {'lat': item.get('latitude'), 'lon': item.get('longitude')}
                for json_key, internal_key in fields_map.items():
                    val = item.get(json_key)
                    if val is not None:
                        merged_obs[ts][internal_key] = val

        update_obs(data.get('waves', []), {
            'significantWaveHeight': 'wave_height',
            'meanPeriod': 'wave_period_mean',
            'meanDirection': 'wave_dir_mean',
            'meanDirectionalSpread': 'wave_spread'
        })
        update_obs(data.get('wind', []), {
            'speed': 'wind_speed',
            'direction': 'wind_dir'
        })
        update_obs(data.get('surfaceTemp', []), {
            'degrees': 'temp'
        })
        update_obs(data.get('barometerData', []), {
            'value': 'pressure'
        })

        if csv and merged_obs:
            print("SpotterId,    Timestamp,           Lat,      Lon,      WaveHt,   Period,  WvDir,  WvSprd,  WndSpd, WndDir, Temp,   Press")

        for ts in sorted(merged_obs.keys()):
            obs = merged_obs[ts]
            dt = to_datetime(ts)
            ts_fmt = format_datetime(dt) if dt else ts
            lat, lon = obs.get('lat', 0.0) or 0.0, obs.get('lon', 0.0) or 0.0

            if csv:
                # Helper to format floats with padding or return empty padding if None/Empty
                def fmt(val, spec):
                    try:
                        return f"{float(val):{spec}}"
                    except (TypeError, ValueError):
                        # Returns spaces matching the width in the format spec (e.g., '7.2f' -> 7 spaces)
                        width = re.search(r'\d+', spec)
                        return " " * int(width.group()) if width else " "

                print(f"{target_spotter_id}, {ts_fmt}, "
                      f"{fmt(obs.get('lat'), '8.3f')}, "
                      f"{fmt(obs.get('lon'), '8.3f')}, "
                      f"{fmt(obs.get('wave_height'), '7.2f')}, "
                      f"{fmt(obs.get('wave_period_mean'), '7.2f')}, "
                      f"{fmt(obs.get('wave_dir_mean'), '7.1f')}, "
                      f"{fmt(obs.get('wave_spread'), '7.1f')}, "
                      f"{fmt(obs.get('wind_speed'), '7.1f')}, "
                      f"{fmt(obs.get('wind_dir'), '6.0f')}, "
                      f"{fmt(obs.get('temp'), '6.1f')}, "
                      f"{fmt(obs.get('pressure'), '8.1f')}")
            else:
                # Non-CSV output remains dynamic and will show all keys automatically
                print(f"\n--- Observation: {ts_fmt} ---")
                print(f"spotter_id: {target_spotter_id}")
                for key in sorted(obs.keys()):
                    print(f"{key}: {obs[key]}")

        SPOTTER_IDS[target_spotter_id] = len(merged_obs)
        print("[Done]", file=sys.stderr)

    except Exception:
        print(f"Error processing data for {target_spotter_id}:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

# -------------------------------------------------------
def main():
    global ARGS, OUT_TIME_UTC
    api_key = os.getenv('SOFAR_API_KEY')

    parser = argparse.ArgumentParser(
        description=f"\n{VERSION}\nRead Sofar Ocean observations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example usage:\n"
               " Get List of Buoy Ids\n"
               "   python sofar-loader.py --list  \n"
               "   python sofar-loader.py --list --out ids.txt\n"
               "\n Load historical data for id(s):\n"
               "   python sofar-loader.py --id=all [--verbose]\n"
               "   python sofar-loader.py --id=all --csv \n"
               "   python sofar-loader.py --id=SPOT-32049C --csv \n"
               "   python sofar-loader.py --id=SPOT-32049C --limit=48 --csv --out save.csv\n"
               "   python sofar-loader.py --file ids.txt t\n"
               "\n Remember to set environment variables \n"
               "   SOFAR_API_KEY \n"
        ,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    # Changed to nargs='+' to support multiple IDs
    group.add_argument('--id', '-i', type=str, nargs='+', help='Spotter ID(s) or "*" / "all"')
    group.add_argument('--file', type=str, help='File containing Spotter IDs')
    group.add_argument('--list-buoys', action='store_true', help='List all buoys')

    parser.add_argument('--limit', '-l', type=int, default=24, help='Max data rows')
    parser.add_argument('--csv', '-c', action='store_true', help='Output in CSV')
    parser.add_argument('--out', type=str, help='Save Spotter IDs to file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    #   includeWindData: 'true',
    #   includeSurfaceTempData: 'true',
    #   includeBarometerData: 'true',
    parser.add_argument('--filter', type=str, help='Filters, wave, wind, temp, press (default is all)')
    parser.add_argument('--utc', '-u', action='store_true', help='Output times in UTC')

    ARGS = parser.parse_args()
    OUT_TIME_UTC = ARGS.utc

    if not api_key:
        print("Error: SOFAR_API_KEY environment variable must be set.", file=sys.stderr)
        sys.exit(1)

    try:
        target_ids = []

        if ARGS.list_buoys:
            ids = get_buoy_list()
            print("Available Spotter IDs:", file=sys.stderr)
            for s_id in ids:
                print(f"  {s_id}", file=sys.stderr)
                if ARGS.out: SPOTTER_IDS[s_id] = 0
            return

        elif ARGS.id:
            # Check for wildcard in the first provided ID
            if len(ARGS.id) == 1 and ARGS.id[0].lower() in ('*', 'all'):
                print("Wildcard detected, fetching all buoys...", file=sys.stderr)
                target_ids = get_buoy_list()
            else:
                target_ids = ARGS.id

        elif ARGS.file:
            with open(ARGS.file, 'r') as f:
                target_ids = [line.strip().replace('"', '') for line in f if line.strip()]

        # Process the final list of IDs
        for s_id in target_ids:
            fetch_sofar_data(s_id)

    except Exception:
        print("\n--- CRITICAL APPLICATION ERROR ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    if ARGS.out and SPOTTER_IDS:
        with open(ARGS.out, 'w') as f:
            for s_id in sorted(SPOTTER_IDS.keys()):
                f.write(f"{s_id}\n")

if __name__ == "__main__":
    main()