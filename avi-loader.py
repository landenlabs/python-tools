#!/usr/bin/env python3
"""Get SUN/SSDS Aviation data product loader at Flight Levels"""
import os
import sys
import argparse
import json
import re
import traceback
import requests
from datetime import datetime, timezone

VERSION = "v1.2 (Apr-2026)"

MS_TO_KNOTS = 1.94384
MS_TO_MPH = 2.23694
MS_TO_KPH = 3.6

SUN_DOMAIN = "api.weather.com"
FLEVEL_MIN = 1000
FLEVEL_STEP = 1000
FLEVEL_TO_FL = 100

STR_STD_TM_FMT = "%a %d-%b-%Y  %I:%M %p %Z"

API_KEY = None
OUT_TIME_UTC = False
data_urls = []
args = None


def get_value(geocode, products, rt, t):
    lat, lng = geocode.split(',', 1)
    url = f"https://{SUN_DOMAIN}/v2/tiler/point"
    params = {
        'lat': lat,
        'lon': lng,
        'products': products,
        'format': 'geojson',
        'method': 'nearest',
        'apiKey': API_KEY,
        'rt': rt,
        't': t
    }
    if args.verbose:
        print(f"Request URL: {url}", file=sys.stderr)
        print(f"  products={products} rt={rt} t={t}", file=sys.stderr)
    response = requests.get(url, params=params)
    response.raise_for_status()
    data_urls.append(response.url)
    data = response.json()
    if args.verbose:
        print(json.dumps(data, indent=2), file=sys.stderr)
    features = data.get('features', [])
    if not features:
        return None
    return features[0]['properties']


def format_datetime(dt: datetime):
    if dt.tzinfo is None:
        assert "Missing Time Zone"
    target_dt = dt.astimezone(timezone.utc if OUT_TIME_UTC else None)
    return target_dt.strftime(STR_STD_TM_FMT)


def fmt_epoch_ms(ms_str):
    dt_utc = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
    dt_local = dt_utc.astimezone()
    return f"{ms_str} {dt_utc.strftime('%a %Y-%m-%d %H:%M UTC')}  /  {dt_local.strftime('%a %Y-%m-%d %H:%M %Z')}"


def print_time_dimensions(info_json):
    print("\n--- Time Dimensions ---", file=sys.stderr)
    for layer_code, products in info_json.get('layers', {}).items():
        for prod_name, prod_data in products.items():
            dims = prod_data.get('dimensions', [{}])[0]
            print(f"  {layer_code}:{prod_name}", file=sys.stderr)
            for rt_val in dims.get('rt', []):
                print(f"    rt : {fmt_epoch_ms(rt_val)}", file=sys.stderr)
            for t_val in sorted(dims.get('t', []), key=int):
                print(f"    t  : {fmt_epoch_ms(t_val)}", file=sys.stderr)
    print("--- End Time Dimensions ---\n", file=sys.stderr)


def load_aviation(geocode, hours, hour_start, flevel_start, flevel_end, base_code, prod_name, unit):
    """Fetch and display aviation wind speed data for the given parameters."""
    time_uri = f"https://{SUN_DOMAIN}/v2/tiler/info?products={base_code}&apiKey={API_KEY}"
    if args.verbose:
        print(f"Request URL: {time_uri}", file=sys.stderr)
    resp = requests.get(time_uri)
    resp.raise_for_status()
    decoded_json = resp.json()
    if args.verbose:
        print(json.dumps(decoded_json, indent=2), file=sys.stderr)
        print_time_dimensions(decoded_json)

    json_series = decoded_json.get('layers', {}).get(base_code, {})

    unit_header = {
        'speed':       'm/s, Kts, mph, kph',
        'temperature': 'kel, far, cel',
        'percent':     ' % ',
        'none':        'value',
    }
    print(f"Now,   Feet, Code,        Parameter_______,             RunTime(RT)_______,              Forecast(T)______, Hr, {unit_header[unit]}")

    now = datetime.now(timezone.utc)

    for row_name in sorted(json_series.keys()):
        if row_name.startswith(prod_name):
            dimensions = json_series[row_name].get('dimensions', [{}])[0]
            if 'rt' in dimensions and 't' in dimensions:
                rt = dimensions['rt'][0]
                t_sorted = sorted(dimensions['t'])

                for hr_idx in range(hour_start, hour_start + hours):
                    if hr_idx >= len(t_sorted):
                        break
                    t_val = t_sorted[hr_idx]

                    for flevel in range(flevel_start, flevel_end + 1, FLEVEL_STEP):
                        at_fl = f"AtFL{int(flevel / FLEVEL_TO_FL):03d}"
                        # Ensure base_code is treated as an integer for the calculation
                        prod_code = int(int(base_code) + (flevel - FLEVEL_MIN) / FLEVEL_STEP)
                        product_query = f"{prod_code}:{re.sub(r'AtFL.{3}', at_fl, row_name)}"

                        try:
                            props = get_value(geocode, product_query, rt, t_val)

                            if props is None:
                                print(f"---, {str(flevel).rjust(6)}, {product_query.ljust(20)}, NaN")
                                continue

                            dt_rt = datetime.fromtimestamp(props['rt'] / 1000, tz=timezone.utc)
                            dt_t = datetime.fromtimestamp(props['t'] / 1000, tz=timezone.utc)
                            val = props['value']

                            is_now = "NOW" if (now.day == dt_t.day and now.hour == dt_t.hour) else "---"

                            output = [
                                is_now,
                                str(flevel).rjust(6),
                                str(props['product']),
                                str(props['variable']).ljust(23),
                                format_datetime(dt_rt).ljust(30),
                                format_datetime(dt_t).ljust(30),
                                str(hr_idx),
                            ]
                            if unit == 'speed':
                                output += [f"{val:.2f}", f"{val * MS_TO_KNOTS:.2f}", f"{val * MS_TO_MPH:.2f}", f"{val * MS_TO_KPH:.2f}"]
                            elif unit == 'temperature':
                                cel = val - 273.15
                                output += [f"{val:.2f}", f"{cel * 9/5 + 32:.2f}", f"{cel:.2f}"]
                            else:  # percent / none
                                output += [f"{val:.2f}"]
                            print(", ".join(output))

                        except Exception as e:
                            print(f"Error fetching {product_query}: {e}\n{traceback.format_exc()}")


    if args.verbose:
        print("\nTimeUrl")
        print(f"curl -sS '{time_uri}'")
        print("DataUrls:")
        for url in data_urls:
            print(url)


def main():
    global API_KEY, OUT_TIME_UTC, args

    parser = argparse.ArgumentParser(
        description=f"{VERSION}\nGet SUN/SSDS Aviation product loader at Flight Levels FL010 to FL100",
        epilog="""Example usage:
  avi-loader.py --location 24.5 -81.7
  avi-loader.py --location "24.5,-81.7" --hours 5 --startHour 2
  avi-loader.py -l 24.5,-81.7 --startElev 2000 --endElev 8000
  avi-loader.py -l 24.5 -81.7 --product 8270:WindSpeed

Environment:
  SUN_API_KEY   SUN / SSDS API key (required)
  
Products:
        8170:Temperature
        8170:RelativeHumidity
        8270:WindSpeed
        1900:FIPaltitudeabovemsl  Ice
        1950:GTGaltitudeabovemsl  Turbulence
        
SUN API:
  Domain: api.weather.com
  Endpoint: /v2/tiler/point
  Endpoint: /v2/tiler/info

""",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument('--location', '-l', nargs='+', metavar='LAT_LON',
                        default=['24.5', '-81.7'],
                        help='Latitude and longitude (e.g., 24.5 -81.7  or  "24.5,-81.7")')
    parser.add_argument('--startHour', type=int, default=0, metavar='nn',
                        help='Starting forecast hour index (default: 0)')
    parser.add_argument('--hours', type=int, default=10, metavar='nn',
                        help='Number of forecast hours to display (default: 10)')
    parser.add_argument('--startElev', type=int, default=1000, metavar='nnnn',
                        help='Starting elevation in feet (default: 1000)')
    parser.add_argument('--endElev', type=int, default=10000, metavar='nnnn',
                        help='Ending elevation in feet (default: 10000)')
    parser.add_argument('--product', default='8270:WindSpeed', metavar='"code:name"',
                        help='Product code:name (default: 8270:WindSpeed)')
    parser.add_argument('--unit',    default='none',
                        choices=['temperature', 'speed', 'percent', 'none'],
                        help='Unit type for display (default: none)')
    parser.add_argument('--utc', '-u', action='store_true',
                        help='Display times in UTC (default: local time)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print each network request URL to stderr.')

    args = parser.parse_args()

    # Parse location: accept "lat,lng" or "lat lng" forms
    raw = ' '.join(args.location).replace(',', ' ')
    parts = raw.split()
    try:
        if len(parts) != 2:
            raise ValueError(f"expected 2 values, got {len(parts)}")
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError as e:
        parser.error(f"--location: {e}")
    geocode = f"{lat},{lon}"

    # Parse product code:name
    if ':' not in args.product:
        parser.error("--product must be in 'code:name' format (e.g., '8270:WindSpeed')")
    base_code, prod_name = args.product.split(':', 1)

    OUT_TIME_UTC = args.utc
    API_KEY = os.getenv('SUN_API_KEY')
    if not API_KEY:
        print("Error: SUN_API_KEY environment variable must be set.", file=sys.stderr)
        sys.exit(1)

    print(f"Location: {geocode}, Hours: {args.hours}, StartHour: {args.startHour}, "
          f"Elev: {args.startElev}-{args.endElev}ft, Product: {args.product}")

    load_aviation(geocode, args.hours, args.startHour, args.startElev, args.endElev, base_code, prod_name, args.unit)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
