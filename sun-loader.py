#!/usr/bin/env python3
"""Load SUN/SSDS data"""

import argparse
import json
import math
import os
import re
import struct
import sys
from datetime import datetime, timedelta, timezone

import requests

VERSION = "v2.01 (Feb-2026)"
BASE_URL = "https://api.weather.com/"
SUN_SERIES_URL = BASE_URL + "v3/TileServer/series/productSet"
SUN_MULTIPOINT_URL = BASE_URL + "v2/tiler/multipoint"
SUN_POINT_URL = BASE_URL + "v2/tiler/point"
SUN_INFO_URL = BASE_URL + "v2/tiler/info"
SUN_DATA_URL = BASE_URL + "v2/tiler/data"
ALERT_INFO_URL = BASE_URL + "v2/vector-api/products/{prodcode}/info"
ALERT_FEATURES_URL = BASE_URL + "v2/vector-api/products/{prodcode}/features"

DEFAULT_ALERT_PRODCODE = "648"  # global alerts

STR_STD_TM_FMT = "%a %d-%b-%Y  %I:%M %p %Z"
STR_ISO_TM_FMT = "%Y-%m-%dT%H:%M:%SZ"
STR_HHMMZ_TM_FMT = "%H:%M:%SZ"
STR_DAY_HOUR_TM_FMT = "%a %Hz"

DEFAULT_PRODUCT = "temperature_FLPacked:packed"
DEFAULT_PRODSET = "atak"  # product set
DEFAULT_LOCATION = "38.83,-104.82"  # Denver CO, elev ~ 5000 ft
METERS_PER_100FT = 30.48
OUT_TIME_UTC = False

def parse_time_offset(offset_str):
    match = re.match(r"([+-]?)(\d+\.?\d*)([HD])", offset_str.upper().strip())
    if not match:
        raise ValueError(f"Invalid format: {offset_str}. H=hour, D=day ex: '+3H', '+3.5H' or '-2D'")
    
    sign_str, value, unit = match.groups()
    amount = float(value) * (-1 if sign_str == "-" else 1)

    if sign_str or unit == "D":
        return timedelta(hours=amount) if unit == "H" else timedelta(days=amount)

    # 2. HANDLE ABSOLUTE TIME SHIFTS (No sign)
    now = datetime.now().astimezone()
    target_hour = int(amount)

    # Calculate how many hours to add to reach that specific hour
    # If current hour is 14 and target is 11, it moves to 11 AM tomorrow
    hours_diff = (target_hour - now.hour) % 24

    # We also zero out the minutes/seconds to land exactly at the "start" of the hour
    return timedelta(hours=hours_diff) - timedelta(minutes=now.minute-1, seconds=now.second, microseconds=now.microsecond)


def _parse_single_unit(unit_str, now):
    """Helper to convert a single xxH or xxD string into a timedelta."""
    unit_str = unit_str.upper().strip()
    match = re.match(r"([+-]?)(\d+\.?\d*)([HD])", unit_str)

    if not match:
        raise ValueError(f"Invalid format: {unit_str}")

    sign_str, value_str, unit = match.groups()
    amount = float(value_str)

    # Handle Relative (+/-) or Days
    if sign_str or unit == "D" or now == None:
        multiplier = -1 if sign_str == "-" else 1
        return timedelta(hours=amount * multiplier) if unit == "H" else timedelta(days=amount * multiplier)

    # Handle Absolute Hour (e.g., 13H)
    target_hour = int(amount)
    hours_diff = (target_hour - now.hour) % 24

    # Calculate offset to land exactly on the hour :00:00
    return timedelta(hours=hours_diff) - timedelta(
        minutes=now.minute,
        seconds=now.second,
        microseconds=now.microsecond
    )

def parse_time_input(input_str):
    """
    Parses single offset or sequence (from, to, step).
    Returns: (start_datetime, end_datetime, step_timedelta)
    """
    now = datetime.now().astimezone()
    parts = [p.strip() for p in input_str.split(',')]

    if len(parts) == 1:
        # Single value case
        delta = _parse_single_unit(parts[0], now)
        start_time = now + delta
        return start_time, start_time, timedelta(0)

    elif len(parts) == 3:
        # Sequence case: from, to, step
        start_time = now + _parse_single_unit(parts[0], now)
        end_time = now + _parse_single_unit(parts[1], now)

        # Get the magnitude of the step (always positive initially)
        raw_step = _parse_single_unit(parts[2], None)
        step_magnitude = abs(raw_step.total_seconds())

        # Determine direction: 1 if forward, -1 if backward
        direction = 1 if end_time >= start_time else -1

        # Construct the final step_delta
        step_delta = timedelta(seconds=step_magnitude * direction)

        return start_time, end_time, step_delta

    else:
        raise ValueError("Input must be a single value or a sequence: 'from, to, step'")

def format_datetime(dt: datetime):
    # Ensure has a timezone,  prevents errors when shifting to UTC/Local
    if dt.tzinfo is None:
        assert "Missing Time Zone" # Assume input is UTC if missing

    target_dt = dt.astimezone(timezone.utc if OUT_TIME_UTC else None)
    return target_dt.strftime(STR_STD_TM_FMT)


def parse_location(location_str):
    try:
        lat, lon = map(float, location_str.split(','))
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Coordinates out of valid range")
        return lat, lon
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid location: {location_str}. Use 'latitude,longitude'") from e


def get_headers(accept="application/json"):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "accept": accept,
        "Content-Type": "application/json"
    }

def vector_magnitude(u, v):
    return math.sqrt(u * u + v * v)

def format_json_compact(data):
    standard = json.dumps(data, indent=2)
    compact = re.sub(r'\[\s+(-?\d+\.?\d*),\s+(-?\d+\.?\d*),\s+(-?\d+\.?\d*)\s+]',
                     r'[\1, \2, \3]', standard)
    return re.sub(r'\[\s+(-?\d+\.?\d*)\s+]', r'[\1]', compact)


def make_binary_request(url, params, verbose=False):
    try:
        response = requests.get(url, params=params, headers=get_headers(accept="*/*"))
        if verbose:
            print(f"Request: {response.request.url}", file=sys.stderr)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def make_request(url, params, method='GET', json_data=None, verbose=False):
    try:
        if method == 'POST':
            response = requests.post(url, params=params, headers=get_headers(), json=json_data)
        else:
            response = requests.get(url, params=params, headers=get_headers())
        
        if verbose:
            print(f"Request: {response.request.url}", file=sys.stderr)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


def fetch_time_series(args):
    api_key = os.getenv('SUN_API_KEY')
    params = {'productSet': args.prodset, 'apiKey': api_key}
    
    if args.product and len(args.product) > 3:
        params['filter'] = args.product
    
    data = make_request(SUN_SERIES_URL, params, verbose=args.verbose)
    if not data:
        return
    
    series_info = data.get("seriesInfo", {})
    max_ts = args.ts if not args.all else float('inf')

    for product_name, details in series_info.items():
        if args.verbose:
            print(f"\n--- Product: {product_name} ---")
        series_list = details.get("series", [])

        ts_cnt = 0
        for entry in series_list:
            time_slot = entry['ts']
            ts_readable = format_datetime(datetime.fromtimestamp(time_slot, tz=timezone.utc))
            ts_cnt += 1
            
            if args.verbose:
                print(f"\n{ts_cnt:3d}:  {product_name}  (ts): {time_slot}  {ts_readable}")
                print("Forecast (fts):")
                for fts_cnt, fts in enumerate(entry.get("fts", [])):
                    fts_readable = format_datetime(datetime.fromtimestamp(fts, tz=timezone.utc))
                    print(f"  {fts_cnt:3d}:  {product_name}  (fts) {fts}:  {fts_readable}")
            else:
                fts = entry.get("fts", [])
                if fts:
                    fts_cnt = len(fts)
                    fts0 = datetime.fromtimestamp(fts[0], tz=timezone.utc)
                    ftsn = datetime.fromtimestamp(fts[fts_cnt-1], tz=timezone.utc)
                    duration = fts0 - ftsn
                    total_hours = duration.total_seconds() / 3600
                    fts0_time = fts0.strftime(STR_DAY_HOUR_TM_FMT)
                    ftsn_time = ftsn.strftime(STR_DAY_HOUR_TM_FMT)
                    print(f" TS: {time_slot}  {ts_readable}  #Steps:{fts_cnt:3d}  #Hours:{total_hours:5.1f}  From:{fts0_time} To:{ftsn_time} {product_name} ")

            if ts_cnt >= max_ts:
                break
    
    print("[Done]")


def fetch_multipoint(args):
    api_key = os.getenv('SUN_API_KEY')
    start_time, end_time, step_time = parse_time_input(args.time)

    forecast_time = start_time
    while forecast_time <= end_time:
        std_future = format_datetime(forecast_time)
        utc_future = forecast_time.astimezone(timezone.utc).strftime(STR_ISO_TM_FMT)
        lat_val, lon_val = parse_location(args.location)

        # Longitude, Latitude, MetersMSL
        FLIGHT_LEVELS = range(10, 110, args.sfl)[:args.nfl]
        coordinates = [[lon_val, lat_val, flvl * METERS_PER_100FT] for flvl in FLIGHT_LEVELS]

        # MultiPoint or LineString
        post_data = {
            "geometry": {"type": "MultiPoint", "coordinates": coordinates},
            "times": [utc_future] * len(coordinates)
        }

        params = {"products": args.product, "apiKey": api_key}

        if args.verbose:
            print(f"Post: {format_json_compact(post_data)}", file=sys.stderr)

        data = make_request(SUN_MULTIPOINT_URL, params, method='POST', json_data=post_data, verbose=args.verbose)
        if not data:
            return

        utc_hhmm = forecast_time.astimezone(timezone.utc).strftime(STR_HHMMZ_TM_FMT)
        print(f"Multipoint for {args.product} at [{lat_val:.2f},{lon_val:.2f}] Forecast:{args.time} {std_future} / {utc_hhmm}", file=sys.stderr)
        print(f" json body time={utc_future}" )

        points = data.get("points", [])
        if not points:
            dtStr = format_datetime(forecast_time)
            print(f" {dtStr} {args.product}  --No data--")
            return

        for point in points:
            try:
                time_str = format_datetime(datetime.fromisoformat(point["time"].replace('Z', '+00:00')))
                coordinate = point["coordinate"]
                elev_ft = float(coordinate[2]) * 3.2808399
                data_dict = point["data"]
                prod = next(iter(data_dict.keys()))
                values = data_dict[prod]
                out_value = ""

                if values:
                    try:
                        keys = values.keys()
                        if len(keys) == 1:
                            vlist = next(iter(values.values()))
                            value = float(vlist[0])
                        else:
                            u = float(values["u"][0])
                            v = float(values["v"][0])
                            out_value += f"[{u},{v}]="
                            value = vector_magnitude(u, v)

                        out_value += f"{ value:.3f}"
                    except Exception as ex:
                        out_value = f"[{ex}]"

                fl_level = int(elev_ft / 100)  # FL010 = 1,000 ft, FL100 = 10,000
                print(f" {time_str} {prod} FL{fl_level:03d}  {out_value}")
            except Exception as e:
                print(f" Error processing point: {e}", file=sys.stderr)

        if args.verbose:
            print(format_json_compact(data))

        forecast_time += step_time
        if step_time.total_seconds() == 0:
            break


def fetch_elevation(args):
    api_key = os.getenv('SUN_API_KEY')
    start_time, end_time, step_time = parse_time_input(args.time)

    forecast_time = start_time.astimezone(timezone.utc)
    std_future = format_datetime(forecast_time)
    lat_val, lon_val = parse_location(args.location)
    prod_code, prod_name = args.product.split(':')
    
    params = {"products": prod_code, "apiKey": api_key}
    
    info_data = make_request(SUN_INFO_URL, params, verbose=args.verbose)
    if not info_data:
        return

    if args.verbose:
        print(f"Elevation for {args.product} at [{lat_val:.2f},{lon_val:.2f}] Forecast:{args.time} {std_future}",
              file=sys.stderr)
        print(json.dumps(info_data, indent=2))
    
    prod_code_times = info_data["layers"][prod_code]
    full_prod_name = next((k for k in prod_code_times if k.startswith(prod_name)), None)
    
    if not full_prod_name:
        print(f"Error: Product {prod_name} not found", file=sys.stderr)
        return
    
    prod_times = prod_code_times[full_prod_name]
    dimensions = prod_times.get("dimensions", [])
    
    rt = 0
    datetime_objects = []
    
    for dimension in dimensions:
        rt = max(rt, int(dimension["rt"][0]))
        epoch_mill_str = dimension["t"]
        datetime_objects = [
            datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
            for ms in epoch_mill_str
        ]
        if args.verbose and datetime_objects:
            for dt in datetime_objects[:3]:
                print(dt.isoformat())
    
    if not datetime_objects:
        print("Error: No time data available", file=sys.stderr)
        return

    rt_dt = datetime.fromtimestamp(int(rt) / 1000, tz=timezone.utc)
    rt_str = format_datetime(rt_dt)

    request_time = start_time
    while request_time <= end_time:
        forecast_time = request_time.astimezone(timezone.utc)
        forecast_time = min(datetime_objects, key=lambda x: abs(x - forecast_time))

        print(f"Elevation for {args.product} at [{lat_val:.2f},{lon_val:.2f}] Forecast:{args.time} {std_future}  RT:{rt_str}",
              file=sys.stderr)

        point_params = {
            "lat": lat_val,
            "lon": lon_val,
            "rt": rt,
            "t": int(forecast_time.timestamp() * 1000),
            "format": "geojson",
            "method": "nearest",
            "apiKey": api_key
        }

        grid_params = {
            "rt": rt,
            "t": int(forecast_time.timestamp() * 1000),
            "apiKey": api_key,
            "lod": 2,
            "x": 0,
            "y": 0
        }

        prod_num = int(prod_code) - 1
        FLIGHT_LEVELS = range(10, 110, args.sfl)[:args.nfl]

        url_params = grid_params if args.grid else point_params
        for flight_level in FLIGHT_LEVELS:
            prod_num += 1
            prod_at_fl = f"{prod_num}:{prod_name}AtFL{flight_level:03d}"
            url_params["products"] = prod_at_fl


            point_data = make_request(SUN_DATA_URL if args.grid else SUN_POINT_URL, url_params, verbose=args.verbose)
            if not point_data:
                continue

            features = point_data.get("features", [])
            if features:
                for feature in features:
                    properties = feature["properties"]
                    value = properties["value"]
                    name = properties["variable"]
                    product = properties["product"]
                    t = properties["t"]
                    dt = datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc)
                    dt_str = format_datetime(dt)
                    print(f" {dt_str} {product}:{name} {value:.3f}")
            else:
                dt_str = format_datetime(forecast_time)
                print(f" {dt_str} {prod_at_fl}  --No data--")

            if args.verbose:
                print(json.dumps(point_data, indent=2))

        request_time += step_time
        if step_time.total_seconds() == 0:
            break

def fetch_tile(args):
    api_key = os.getenv('SUN_API_KEY')
    product = args.product

    prod_code, prod_name = product.split(':', 1)

    layers = load_product_info(product, verbose=args.verbose)
    if layers is None:
        print(f"Error: failed to load product info for {product}", file=sys.stderr)
        return

    prod_layer = layers.get(prod_code)
    if prod_layer is None:
        print(f"Error: product code '{prod_code}' not found in layers", file=sys.stderr)
        return

    prod_entry = prod_layer.get(prod_name)
    if prod_entry is None:
        print(f"Error: product name '{prod_name}' not found under layer '{prod_code}'", file=sys.stderr)
        return

    dimensions = prod_entry.get("dimensions", [])
    if not dimensions:
        print(f"Error: no dimensions for {product}", file=sys.stderr)
        return

    first_dim = dimensions[0]
    rt = first_dim["rt"][0]
    t  = first_dim["t"][0]

    meta = prod_entry.get("meta", {})
    description  = meta.get("description", "")
    data_type = meta.get("dataType", "")
    units     = meta.get("attributes", {}).get("units", "")
    missing   = meta.get("attributes", {}).get("missing_value", "")
    tileset = meta.get("tileset", [])
    tile_levels = tileset.get("Web Mercator", {}).get("tiles", [])

    lod_values = [entry["lod"] for entry in tile_levels if "lod" in entry]
    min_lod = min(lod_values) if lod_values else None
    max_lod = max(lod_values) if lod_values else None

    print(f"Product={product}\n  rt={rt}\n  t={t}\n")
    print(f"  description={description}\n  dataType={data_type}\n  units={units}\n  missing={missing}\n")
    print(f"  minLod={min_lod}\n  maxLod={max_lod}\n")

    x, y, z = (int(v.strip()) for v in args.tile.split(','))
    tile_url = SUN_DATA_URL + f"?products={product}&rt={rt}&t={t}&lod={z}&x={x}&y={y}&apiKey={api_key}"

    tile_data = make_binary_request(tile_url, params={}, verbose=args.verbose)
    if tile_data is None:
        print(f"Error: no tile data returned for {product} tile={x},{y},{z}", file=sys.stderr)
        return

    print(f"Tile {x},{y},{z} — {len(tile_data)} bytes received", file=sys.stderr)

    data_type, byte_order = args.type.split(':', 1)

    if data_type == 'float4':
        num_floats = len(tile_data) // 4
        flat = struct.unpack(f'>{num_floats}f', tile_data)
        side = int(math.sqrt(num_floats))
        grid = [list(flat[row * side:(row + 1) * side]) for row in range(side)]

        if args.verbose:
            print(f"--tile info--\n", file=sys.stderr)
            save_histogram(flat, product, units, x, y, z)
            # tile_url = SUN_DATA_URL + f"?products={product}&rt={rt}&t={t}&apiKey={api_key}" + "&lod={z}&x={x}&y={y}"
            # load_all_tiles(tile_url, 0, 6, )

    else:
        print(f"Error: unsupported type '{data_type}'", file=sys.stderr)
        return


def load_all_tiles(url_template, from_lod, to_lod):
    """Load all map tiles for LOD levels from_lod to to_lod (inclusive).

    url_template: URL string with {x}, {y}, {z} placeholders for tile coordinates.
    Tile coordinate ranges at LOD z: x in [0, 2^z), y in [0, 2^z).
    """
    for z in range(from_lod, to_lod + 1):
        num_tiles = 2 ** z
        for y in range(num_tiles):
            for x in range(num_tiles):
                url = url_template.replace('{x}', str(x)).replace('{y}', str(y)).replace('{z}', str(z))
                try:
                    response = requests.get(url, headers=get_headers(accept="*/*"), timeout=10)
                    if response.ok:
                        print(f"  OK   z={z} x={x} y={y}  ({len(response.content)} bytes)  {url}")
                    else:
                        print(f"  FAIL z={z} x={x} y={y}  HTTP {response.status_code}  {url}")
                except requests.exceptions.RequestException as e:
                    print(f"  ERR  z={z} x={x} y={y}  {e}  {url}")


def save_histogram(flat, product, units, x, y, z):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    hist_file = f"tile_{x}_{y}_{z}.png"
    with plt.style.context('grayscale'):
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(flat, bins=256, color='black', edgecolor='none')
        ax.set_xlabel(f'Value ({units})')
        ax.set_ylabel('Count')
        ax.set_title(f'{product}  tile={x},{y},{z}')
        fig.tight_layout()
        fig.savefig(hist_file, dpi=96)
        plt.close(fig)
    print(f"Histogram saved to {hist_file}", file=sys.stderr)

def load_product_info(product, verbose=False):
    """Fetch and parse the tiler info JSON for the given product string.
    Returns the parsed 'layers' dict, or None on failure.

    {
      "layers": {
        "1900": {
          "FIPaltitudeabovemsl": {
            "dimensions": [
              {
                "rt": [
                  "1774893600000"
                ],
                "t": [
                  "1775152800000",
                  "1775149200000",
                  "1775145600000",
    """
    api_key = os.getenv('SUN_API_KEY')
    params = {"products": product, "apiKey": api_key, "meta": True}
    data = make_request(SUN_INFO_URL, params, verbose=verbose)
    if not data:
        return None
    if verbose:
        print(json.dumps(data, indent=2))
    return data.get("layers", {})


_ALERT_SECTIONS = ["summary", "counts", "total"]
_ALERT_DEFAULT   = "summary+counts+total"

def _parse_alert_sections(value):
    """Parse comma/plus-separated section tokens, allowing prefix abbreviation.
    Returns a set of full section names, or raises ValueError on bad token.
    """
    tokens = re.split(r'[,+]', value)
    result = set()
    for tok in tokens:
        tok = tok.strip().lower()
        if not tok:
            continue
        matches = [s for s in _ALERT_SECTIONS if s.startswith(tok)]
        if not matches:
            raise ValueError(f"Unknown alert section '{tok}'. Choose from: {', '.join(_ALERT_SECTIONS)}")
        result.add(matches[0])
    return result


def _count_coords(geometry):
    """Return total number of [lon, lat] points across all rings/polygons."""
    coords = geometry.get("coordinates", [])
    geo_type = geometry.get("type", "")
    if geo_type == "Polygon":
        return sum(len(ring) for ring in coords)
    if geo_type == "MultiPolygon":
        return sum(len(ring) for polygon in coords for ring in polygon)
    # Point, LineString, etc.
    return len(coords)


def _print_alert_report(data, sections):
    features = data.get("features", [])

    HDR = f"{'CC':<4} {'Expire (local/UTC)':<26} {'Category':<10} {'Ph':<5} {'Sg':<3} {'#Coords':>7}  EventDescription"
    SEP = "-" * len(HDR)
    show_summary = "summary" in sections
    show_counts  = "counts"  in sections
    show_total   = "total"   in sections

    if show_summary:
        print(HDR)
        print(SEP)

    phenom_sig_counts = {}
    country_counts = {}
    total_coords = 0

    for feature in features:
        props = feature.get("properties", {})
        geom  = feature.get("geometry", {})

        country     = props.get("countryCode", "")
        expire_utc  = props.get("expireTimeUTC")
        category    = props.get("category", "")
        phenomena   = props.get("phenomena", "")
        significance = props.get("significance", "")
        event_desc  = props.get("eventDescription", "")

        if expire_utc is not None:
            expire_dt = datetime.fromtimestamp(int(expire_utc), tz=timezone.utc)
            expire_str = format_datetime(expire_dt)
        else:
            expire_str = "N/A"

        n_coords = _count_coords(geom)
        total_coords += n_coords

        key = f"{phenomena}_{significance}"
        phenom_sig_counts[key] = phenom_sig_counts.get(key, 0) + 1
        country_counts[country] = country_counts.get(country, 0) + 1

        if show_summary:
            print(f"{country:<4} {expire_str:<26} {category:<10} {phenomena:<5} {significance:<3} {n_coords:>9,}  {event_desc}")

    if show_summary:
        print(SEP)

    if show_counts:
        print(f"\nTotals by phenomena+significance:")
        for key in sorted(phenom_sig_counts):
            print(f"  {key:<15}  {phenom_sig_counts[key]:>7,}")

        print(f"\nAlerts by country:")
        for cc in sorted(country_counts):
            print(f"  {cc:<4}  {country_counts[cc]:>7,}")

    if show_total:
        print(f"\n  Total items : {len(features):>7,}")
        print(f"  Total coords: {total_coords:>7,}")


def load_alert(args):
    api_key = os.getenv('SUN_API_KEY')
    prodcode = args.prodcode

    info_url = ALERT_INFO_URL.format(prodcode=prodcode)
    info_data = make_request(info_url, {"meta": "true", "apiKey": api_key}, verbose=args.verbose)
    if not info_data:
        return

    products = info_data.get("products", {})
    for row_name in sorted(products.keys()):
        print(f"row={row_name}")

        if row_name != prodcode:
            continue

        row = products[row_name]
        meta = row.get("meta")
        times = row.get("time", [])

        if meta is None or not times:
            print(f"{row_name}: no meta or time data", file=sys.stderr)
            continue

        time_val = times[0]
        print(f"{row_name}, Forecast time={time_val}")

        features_url = ALERT_FEATURES_URL.format(prodcode=prodcode)
        params = {
            "x": 0, "y": 0, "lod": 0, "tile-size": 256,
            "apiKey": api_key, "time": time_val
        }
        if args.verbose:
            print(f"Features URL: {features_url}  params={params}", file=sys.stderr)

        response = make_request(features_url, params, verbose=args.verbose)
        if response is None:
            print(f"Error: no data returned for {prodcode}", file=sys.stderr)
            return

        filename = f"watchwarn-{prodcode}.json"
        with open(filename, "w") as f:
            json.dump(response, f)
        print(f"Json response saved in {filename}")

        sections = _parse_alert_sections(args.alert)
        _print_alert_report(response, sections)


def main():
    global OUT_TIME_UTC

    parser = argparse.ArgumentParser(
        description=f"{VERSION}\nAccess SUN/SSDS products.",
        epilog="""Example usage:
  python sun-loader.py --series --product=all --all
  python sun-loader.py --series --product=radar
  
  python sun-loader.py --multipoint
  python sun-loader.py --multipoint --location=38.83,-104.82 --time=+2H
  python sun-loader.py --multipoint -p=temperature_FLPacked:packed
  
  python sun-loader.py --elevation
  python sun-loader.py --elevation --product=8170:Temperature --location=38.83,-104.82 --time=+2H
  
  python sun-loader.py --tile 2,2,2 --product=1900:FIPaltitudeabovems --type=float4:BigIndian 
  
Products:
  Multipoint:
      Flight level is relative to sea level
        temperature_FLPacked:packed
        relativeHumidity_FLPacked:packed
        packed_FLWind:packed

      AGL - above-ground-level, is relative to ground
        temperature_AGLPacked:packed
        wind_AGLPacked:packed
        relativeHumidity_AGLPacked:packed

      Surface only
        1248:Temperaturesurface
        150:Wmoseastate
        150:Significantheightofcombinedwindwavesandswellsurface


  Elevation:
        8170:Temperature
        8270:WindSpeed
        1900:FIPaltitudeabovemsl,
        1950:GTGaltitudeabovemsl
  
Locations (latitude,longitude) degrees:
  38.83,-104.82 = Denver CO (5,991 ft)
  42.35,-71.05  = Boston MA (   14 ft)
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--series', '-s', action='store_true', help='Time series')
    group.add_argument('--multipoint', '-m', action='store_true', help='Multipoint FL010 to FL100')
    group.add_argument('--elevation', '-e', action='store_true', help='Elevation FL010 to FL100')
    group.add_argument('--tile',  type=str, default=None, help='Tile coordinates x,y,z')
    group.add_argument('--alert', nargs='?', const=_ALERT_DEFAULT, default=None,
                       metavar='SECTIONS',
                       help=f'Load vector alert data. SECTIONS: summary,counts,total (comma/+ separated, prefix ok). Default: {_ALERT_DEFAULT}')

    # parser.add_argument('--time', '-t', type=str, default='+1H', help='Time offset +hhH or +ddD (default: +1H)')
    parser.add_argument('--time', '-t',  type=str,  default='+1H', help='Time from,to,step  Ex: +1H or +1H,+7H,+0.5H')
    parser.add_argument('--product', '-p', type=str, default=DEFAULT_PRODUCT, help=f'Product code (default: {DEFAULT_PRODUCT})')
    parser.add_argument('--prodset', type=str, default=DEFAULT_PRODSET, help=f'Product set (default: {DEFAULT_PRODSET})')
    parser.add_argument('--location', '-l', default=DEFAULT_LOCATION, help=f'Location lat,lon (default: {DEFAULT_LOCATION})')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--utc', '-u', action='store_true', help='Output times in UTC')
    parser.add_argument('--all', '-a', action='store_true', help='All time series data')
    parser.add_argument('--ts', type=int, default=1, help='Number of time series (default: 1, 0=all)')

    parser.add_argument('--nfl', type=int, default=10, help='Number of flight levels (default: 10, max=10)')
    parser.add_argument('--sfl', type=int, default=10, help='Step flight levels (default: 10)')

    parser.add_argument('--prodcode', type=str, default=DEFAULT_ALERT_PRODCODE, help=f'Alert product code (default: {DEFAULT_ALERT_PRODCODE})')
    parser.add_argument('--grid', '-g', action='store_true', help='Grid tile, use with --elevation')
    parser.add_argument('--type',  type=str, default='float4:BigIndian', help='Tile data type, float4:BigIndian')

    args = parser.parse_args()
    OUT_TIME_UTC = args.utc

    api_key = os.getenv('SUN_API_KEY')
    if not api_key:
        print("Error: SUN_API_KEY environment variable must be set.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.series:
            fetch_time_series(args)
        elif args.multipoint:
            fetch_multipoint(args)
        elif args.elevation:
            fetch_elevation(args)
        elif args.tile is not None:
            fetch_tile(args)
        elif args.alert:
            load_alert(args)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            raise
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        sys.exit(0)