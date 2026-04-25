#!/usr/bin/python3

#
# TWC ATAK tool to encode json device list into a binary license.dat file
#

import json
import struct
import os
import argparse
import sys
import zipfile

# --- Configuration ---
VERSION = "v1.03 (Oct-2025)"
VN_BYTES = b'vn01'              # Sync vnXX version with program version vXX.nn
DEF_OUTPUT ="twc_license.lic"   # Sync dXX version with program version vXX.nn
DS_BYTES = b'ds01'              # Device ids
CG_BYTES = b'cg01'              # Config
SEP_CHAR = ','
COMMENT_CHAR = ';'
PAD_CHAR = ' '
CHUNK = 16

# -------------------------------------------------------
def pad(out_bytes:bytearray, chunk:int, filler) -> bytearray:
    while (len(out_bytes) % chunk) != 0:
        out_bytes.append(filler)
    return out_bytes

# -------------------------------------------------------
def encode_append(out_bytes:bytearray, tag:bytearray, data, key) -> bytearray:
    """Encodes data (list of strings, list of integers, or single string) into a byte array."""

    sep_byte = ord(SEP_CHAR)
    start_at = len(out_bytes)
    out_bytes.append(0) # length 16 byte chunks.
    out_bytes.extend(tag)
    out_bytes = pad(out_bytes, CHUNK, 0)

    try:
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    encoded_bytes = item.encode('ascii')
                    out_bytes.extend((byte_value + key) % 256 for byte_value in encoded_bytes)
                    out_bytes.append((sep_byte + key) % 256)
                elif isinstance(item, int):
                    out_bytes.extend(struct.pack(">i", item))

        elif isinstance(data, str):
            encoded_bytes = data.encode('ascii')
            out_bytes.extend((byte_value + key) % 256 for byte_value in encoded_bytes)

    except struct.error as e:
        raise ValueError(f"Warning: Could not encode '{data}', Error: {e}")
    except Exception as e:
        raise ValueError(f"An unexpected error occurred while processing item '{data}': {e}")

    pad(out_bytes, CHUNK, (ord(SEP_CHAR) + key) % 256)
    assert len(out_bytes) % CHUNK == 0
    assert len(out_bytes) / CHUNK < 255
    out_bytes[start_at] = (len(out_bytes) - start_at) // CHUNK

    return out_bytes

# -------------------------------------------------------
def decode_bytes(byte_array, start_at, key) -> tuple[str, int, str]:
    """Decodes a byte array into a list of ASCII strings."""

    section_len = byte_array[start_at] * CHUNK
    end_at = start_at +2
    while end_at < start_at + CHUNK and byte_array[end_at] != 0:
        end_at += 1
    section = byte_array[start_at+1:end_at].decode("ascii")

    decoded_bytes = bytes((byte_enc - key) % 256 for byte_enc in byte_array[start_at+CHUNK : start_at+section_len])
    try:
        ascii_string = decoded_bytes.decode('ascii').rstrip(SEP_CHAR)
        # return section, section_len, [item for item in ascii_string.split(SEP_CHAR) if item]
        return section, section_len, ascii_string
    except UnicodeDecodeError as e:
        raise ValueError(f"Error: Cannot decode byte array as pure ASCII. {e}")

# -------------------------------------------------------
def write_binary_file(filepath, byte_data):
    """Writes byte data to a file."""
    try:
        with open(filepath, 'wb') as f:
            f.write(byte_data)
    except Exception as e:
        raise IOError(f"An error occurred while writing the binary file: {e}")

# -------------------------------------------------------
def read_binary_file(filepath):
    """Reads the full content of a binary file."""
    try:
        with open(filepath, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        raise
    except Exception as e:
        raise IOError(f"An error occurred while reading the binary file: {e}")

# -------------------------------------------------------
def decode_cfg_bytes(read_bytes, key, show_text, verbose):
    """Decodes and displays sections from a binary license byte array."""
    start_at = 0
    byte_cnt = len(read_bytes)
    while start_at < byte_cnt:
        section, section_len, read_strings = decode_bytes(read_bytes, start_at, key)
        end_at = start_at + section_len
        if verbose:
            print(f"\n--- Display, section {section} length {section_len} ---")
            print(f"Encoded {read_bytes[start_at:end_at].hex(' ')}")
            print(f"Read strings: {read_strings}")
        elif show_text:
            print(f"{section}:\n{read_strings}\n")
        start_at = end_at

# -------------------------------------------------------
def decode_file(binary_file, key, show_text, verbose):
    """Reads a binary license file and displays its decoded contents."""
    try:
        read_bytes = read_binary_file(binary_file)
        if read_bytes:
            decode_cfg_bytes(read_bytes, key, show_text, verbose)
    except Exception as e:
        print(f"Verification failed: {e}")
        raise

# -------------------------------------------------------
APK_LICENSE_ENTRY = 'assets/def_license.dat'

def display_apk_license(apk_path, key, show_text, verbose):
    """Extracts assets/def_license.dat from an APK (zip) and displays its decoded contents."""
    try:
        with zipfile.ZipFile(apk_path, 'r') as apk:
            if APK_LICENSE_ENTRY not in apk.namelist():
                raise FileNotFoundError(f"'{APK_LICENSE_ENTRY}' not found in '{apk_path}'.")
            raw = apk.read(APK_LICENSE_ENTRY)
    except zipfile.BadZipFile:
        raise ValueError(f"'{apk_path}' is not a valid ZIP/APK file.")
    decode_cfg_bytes(raw, key, show_text, verbose)

# -------------------------------------------------------
def valid_device_list(devices):

    if not isinstance(devices, list):
        raise TypeError(f"Invalid license format, must be a list. Found: {type(devices).__name__}.")

    index = 0
    while index < len(devices):
        device = devices[index]
        if SEP_CHAR in device:
            raise ValueError(f"Invalid device id {device}, must not contain {SEP_CHAR}")
        index += 1

# -------------------------------------------------------
def get_json_devices(input_json, device_key) -> list:
    """
    Read JSON file, extracts array data, encode data, return bytes
    """
    with open(input_json, 'r', encoding='utf-8') as infile:
        in_full_json = json.load(infile)

    if not isinstance(in_full_json, dict):
        raise ValueError("Input JSON file must be a dictionary.")

    if device_key not in in_full_json:
        raise ValueError(f"Missing key '{device_key}' in input JSON. Available keys: {list(in_full_json.keys())}")

    devices = in_full_json[device_key]
    if not isinstance(devices, list):
        raise TypeError(f"Value for '{device_key}' must be a list. Found: {type(devices).__name__}.")

    valid_device_list(devices)
    return devices

# -------------------------------------------------------
def get_text_devices(input_text) -> list:
    """
    Read TEXT file, extracts array data, encode data, return bytes
    """
    devices = []
    with open(input_text, 'r') as f:
        for line in f:
            devices.append(line.strip().split(COMMENT_CHAR)[0].rstrip(' '))

    valid_device_list(devices)
    return devices

# -------------------------------------------------------
def append_file(out_bytes, input_text, key, tag_bytes) -> bytearray:
    """
    Read TEXT file,   encode data, return bytes
    """
    with open(input_text, 'r', encoding='utf-8') as f:
        contents = f.read()

    out_bytes = encode_append(out_bytes, tag_bytes, contents, key)
    if out_bytes is None:
        raise RuntimeError("Failed to encode data.")

    return out_bytes


# -------------------------------------------------------
def main():
    """Main function to parse arguments and run the tool."""
    parser = argparse.ArgumentParser(
        description="\n" + VERSION + "\nConvert TWC ATAK device uid strings to license.dat file.",
        epilog="Example usage (provide valid key value):\n"
            " Use one of these to create .dat file:"
            "   python atak-tool.py  --json devices.json [--output license.dat] [--section devices] [--verbose]\n"
            "   python atak-tool.py  --text devices.txt [--output license.dat]  [--verbose]\n"
            "   python atak-tool.py  --ids 'AP3A.240905.015.A2' [--output license.dat]  [--verbose]\n"
            "   python atak-tool.py  --ids 'id1,id2,id3' [--output license.dat]  [--verbose]\n"
            "   python atak-tool.py  --text devices.txt --config cfg.json [--output license.dat]  [--verbose]\n"
            "   python atak-tool.py  --config cfg.json [--output license.dat]  [--verbose]\n"
            "   python atak-tool.py  -i id1,id2 -t ids.txt -j ids.json -c cfg.json -d . -v \n"
            "   python atak-tool.py  -c cfg.json   \n"
            "\n"
            " Display contents of existing dat or apk file:\n"
            "   python atak-tool.py  --display license.dat \n"
            "   python atak-tool.py  --display plugin.apk \n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # input switches
    parser.add_argument('--text', '-t', action='append', help='Input text list of device ids. Can be used multiple times.')
    parser.add_argument('--ids', '-i', type=str, help='Input list of device ids, comma separated.')
    parser.add_argument('--json', '-j', action='append', help='Input json device ids. Can be used multiple times. See --section.')
    parser.add_argument('--section', '-s', default='devices', help='The json device section key, defaults to "devices"')
    parser.add_argument('--config', '-c', action='append', help='Include json config file in output. Can be used multiple times.')
    parser.add_argument('--display', '-d', help='Display contents of dat file or APK license (assets/def_license.dat). Use . for default file.')

    # optional switches
    parser.add_argument('--output', "-o", default=DEF_OUTPUT, help='Output file path, defaults to ' + DEF_OUTPUT)
    parser.add_argument('--key', '-k', type=int, default=13, help='Encryption key')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output.')
    args = parser.parse_args()

    out_bytes = bytearray()
    devices = list()

    try:
        if args.json:
            for json_file in args.json:
                devices += get_json_devices(json_file, args.section)
        if args.text:
            for text_file in args.text:
                devices += get_text_devices(text_file)
        if args.ids:
            devices += args.ids.split(SEP_CHAR)

        if devices:
            if args.verbose:  print(f"Devices: {devices}\n")
            out_bytes = encode_append(out_bytes, VN_BYTES, [VERSION], args.key)
            out_bytes = encode_append(out_bytes, DS_BYTES, devices, args.key)

        if args.config:
            if not out_bytes:
                out_bytes = encode_append(out_bytes, VN_BYTES, [VERSION], args.key)
            for config_file in args.config:
                out_bytes = append_file(out_bytes, config_file, args.key, CG_BYTES)

        if len(out_bytes) > 0:
            write_binary_file(args.output, out_bytes)
            print(VERSION + f" Successfully wrote {len(out_bytes)} bytes to: {args.output}")
            if args.display == None:
                decode_file(args.output, args.key, False, args.verbose)

        if args.display != None:
            if len(args.display) == 1:
                args.display = args.output
            if args.display.lower().endswith('.apk'):
                display_apk_license(args.display, args.key, True, args.verbose)
            else:
                decode_file(args.display, args.key, True, args.verbose)
        elif len(out_bytes) == 0:
            parser.print_help()

    except (ValueError, TypeError, IOError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
