#!/usr/bin/env python3
""" Dump to terminal formatted floating point values from binary file and optionally generate a heatmap PNG """
import struct
import argparse
import sys
import os
import traceback
import numpy as np
import matplotlib.pyplot as plt

def main():
    # Use add_help=False to allow using -h for histogram
    parser = argparse.ArgumentParser(
        description="Binary Float32 Hex-style Dumper and Heatmap Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=False
    )
    
    # Required Arguments
    group = parser.add_argument_group("Required Arguments")
    group.add_argument("--input", "-i", required=True, help="Input binary file to read")
    
    # Formatting Options
    opt_group = parser.add_argument_group("Options")
    opt_group.add_argument("--order", choices=['bigendian', 'littleendian'], default='bigendian', 
                        help="Byte order of the input data")
    opt_group.add_argument("--width", "-w", type=int, default=8, help="Total character width per float")
    opt_group.add_argument("--decimal", "-d", type=int, default=2, help="Number of decimal places")
    opt_group.add_argument("--per-row", type=int, default=16, help="Number of floats to print per row")
    
    # Histogram Option
    opt_group.add_argument("--histogram", "-h", action="store_true", 
                        help="Output a histogram of truncated integer values after dump completes or on Ctrl+C")
    
    # Heatmap Options
    hm_group = parser.add_argument_group("Heatmap Options")
    hm_group.add_argument("--dimension", type=int, help="Width and height of data as a square grid for PNG creation")
    hm_group.add_argument("--min", type=float, help="Min value for computing color palette")
    hm_group.add_argument("--max", type=float, help="Max value for computing color palette")
    hm_group.add_argument("--output", "-o", default="heatmap.png", help="Output PNG file name")

    # Re-add help
    opt_group.add_argument("--help", action="help", help="show this help message and exit")

    args = parser.parse_args()

    # Determine struct format
    # '>' is Big Endian, '<' is Little Endian. 'f' is 4-byte float.
    endian_char = '>' if args.order == 'bigendian' else '<'
    fmt = f"{endian_char}f"
    chunk_size = 4

    if not os.path.exists(args.input):
        print(f"Error: File '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)

    # Build the float format string, e.g., "{:8.2f}"
    float_map = f"{{:{args.width}.{args.decimal}f}}"

    histogram_data = {} if args.histogram else None
    all_values = [] if args.dimension else None

    try:
        with open(args.input, 'rb') as f:
            offset = 0
            while True:
                # Read a full row's worth of bytes
                bytes_to_read = chunk_size * args.per_row
                raw_data = f.read(bytes_to_read)
                
                if not raw_data:
                    break

                # Print the hex offset (e.g., 00000010)
                print(f"{offset:08X}: ", end="")

                # Unpack all floats in this chunk
                row_floats = []
                for i in range(0, len(raw_data), chunk_size):
                    chunk = raw_data[i:i+chunk_size]
                    if len(chunk) == chunk_size:
                        val = struct.unpack(fmt, chunk)[0]
                        row_floats.append(float_map.format(val))
                        
                        if histogram_data is not None:
                            try:
                                int_val = int(val)
                            except (ValueError, OverflowError):
                                int_val = 0
                            histogram_data[int_val] = histogram_data.get(int_val, 0) + 1
                        
                        if all_values is not None:
                            all_values.append(val)
                
                print(" ".join(row_floats))
                offset += len(raw_data)

    except KeyboardInterrupt:
        print("\nDump interrupted by user.")
    except Exception as e:
        print("\n" + "="*40, file=sys.stderr)
        print("CRITICAL ERROR: Unexpected exception caught", file=sys.stderr)
        print("="*40, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        if histogram_data:
            print("\n--- Histogram ---")
            for int_val in sorted(histogram_data.keys()):
                print(f"{int_val}: {histogram_data[int_val]}")

        if args.dimension and all_values:
            try:
                expected_size = args.dimension * args.dimension
                if len(all_values) < expected_size:
                    print(f"\nWarning: Not enough data for {args.dimension}x{args.dimension} grid. Have {len(all_values)}, need {expected_size}.", file=sys.stderr)
                    all_values.extend([0.0] * (expected_size - len(all_values)))
                
                data = np.array(all_values[:expected_size]).reshape((args.dimension, args.dimension))
                
                vmin = args.min if args.min is not None else np.nanmin(data)
                vmax = args.max if args.max is not None else np.nanmax(data)
                
                plt.figure(figsize=(8, 8))
                plt.imshow(data, cmap='rainbow', vmin=vmin, vmax=vmax, interpolation='nearest')
                plt.colorbar(label='Value')
                plt.title(f"Heatmap: {args.dimension}x{args.dimension}")
                plt.savefig(args.output)
                print(f"\nHeatmap saved to {args.output}")
            except Exception as e:
                print("\n" + "="*40, file=sys.stderr)
                print("ERROR: Failed to generate heatmap PNG", file=sys.stderr)
                print("="*40, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    main()
