import pandas as pd
import re
import os
import argparse
import glob
import importlib.metadata
import sys
import traceback

#  python.exe -m pip install --upgrade pip
# Windows
#    Automate installing all depenencies - first manually install pipreqs
#      python -m pip install pipreqs
#      python -m pipreqs.pipreqs . --force
#      pip install -r requirements.txt
#
#    Run python only from command line:
#      python -m pip install --upgrade pip
#      python -m pip install --no-cache-dir --upgrade --force-reinstall numpy pandas
#
#      pip list
#
#      python -c "import numpy; print('NumPy Fixed!'); import pandas; print('Pandas Fixed!')"
#      python -v merge_csv.py --help



def get_args():
    parser = argparse.ArgumentParser(description="Merge CSVs with regex filtering and column alignment.")

    # Required: The directory or specific file pattern
    parser.add_argument('--path', type=str, required=True,
                        help="Directory path or glob pattern for CSV files (e.g., './data' or './data/*.csv')")

    # Optional: Filter for which files to include in the merge
    parser.add_argument('--include', type=str, default=r'.*\.csv',
                        help="Regex pattern to match filenames for inclusion. Defaults to all .csv files.")

    # Optional: Patterns to exclude rows (can be used multiple times)
    parser.add_argument('--exclude', action='append', default=[],
                        help="Regex pattern(s) to exclude rows. Can be specified multiple times.")

    parser.add_argument('--output', type=str, default="master_unified.csv",
                        help="The name of the resulting merged CSV file.")
    parser.add_argument('--min-columns', type=int, default=10,
                        help="Minimum csv columns to per row to keep, default is 10")
    parser.add_argument('--sort-by', type=str, help="Column name to use for date-based sorting")

    return parser.parse_args()


def check_environment():
    """Ensures the environment matches the stability requirements."""
    try:
        # Check NumPy without importing it (to avoid the silent binary crash)
        np_version = importlib.metadata.version("numpy")
        major_v = int(np_version.split('.')[0])

        if major_v >= 2:
            print(f"CRITICAL ERROR: NumPy {np_version} detected.")
            print("This script is restricted to NumPy < 2.0 on Windows to prevent silent crashes.")
            print("Please run: python -m pip install 'numpy<2.0'")
            sys.exit(1)

        # Optional: Print versions for the help banner
        if "--help" in sys.argv:
            pd_version = importlib.metadata.version("pandas")
            print(f"--- Environment Verified: NumPy {np_version}, Pandas {pd_version} ---")

    except importlib.metadata.PackageNotFoundError as e:
        print(f"MISSING DEPENDENCY: {e}")
        print("Please run: python -m pip install -r requirements.txt")
        sys.exit(1)

def main():
    args = get_args()

    # 1. Resolve file paths
    # Handle if user passed a directory or a specific pattern
    search_path = args.path
    if os.path.isdir(search_path):
        search_path = os.path.join(search_path, '*')

    all_files = glob.glob(search_path)

    # Filter files based on the --include regex
    include_re = re.compile(args.include)
    target_files = [f for f in all_files if include_re.search(os.path.basename(f))]

    if not target_files:
        print(f"No files matched the path '{args.path}' and include pattern '{args.include}'.")
        return

    # 2. Load and Align with "Noise Filtering"
    dataframes = []
    min_columns = args.min_columns  # Only rows with this many columns are considered "data"

    for file in target_files:
        try:
            clean_lines = []
            with open(file, 'r', encoding='utf-8-sig', errors='ignore') as f:
                for line in f:
                    # 1. Count commas to see if it matches the expected structure
                    if line.count(',') >= min_columns:
                        # 2. STRIP check: Remove whitespace and commas.
                        # If the result is empty, it was just a row like ",,,,,"
                        if line.strip().strip(',').strip().count(",") >= min_columns:
                            clean_lines.append(line)

            if not clean_lines:
                print(f"Skipping {file}: No rows found with {min_columns}+ columns.")
                continue

            # Convert the list of clean strings into a temporary file-like object
            import io
            clean_data = io.StringIO("".join(clean_lines))

            # Now Pandas only sees the "Good" rows
            df = pd.read_csv(clean_data, on_bad_lines='skip', engine='python')

            if not df.empty:
                dataframes.append(df)
                print(f"Adding: {file} ({len(df)} rows)")

        except Exception as e:
            print(f"Could not process {file}: {e}")

    if not dataframes:
        print("\nError: No valid data was found in any files.")
        return

    # Merge: Columns are aligned automatically
    master_df = pd.concat(dataframes, axis=0, ignore_index=True, sort=False)

    # --- IMPROVEMENT: Advanced Column Stripping ---
    initial_cols = list(master_df.columns)
    cols_to_keep = []
    cols_removed = []

    for col in master_df.columns:
        # Get the count of unique values, excluding NaNs
        unique_count = master_df[col].nunique(dropna=True)

        # Logic: If it has more than 2 unique values, it's likely "real" data.
        # If it has 0, 1, or 2, we check if it's worth keeping.
        if unique_count > 2:
            cols_to_keep.append(col)
        else:
            cols_removed.append(f"{col} ({unique_count} unique values)")

    master_df = master_df[cols_to_keep]

    print(f"\n--- Column Cleanup ---")
    print(f"Removed {len(cols_removed)} static or empty columns:")
    for item in cols_removed:
        print(f"  - {item}")
    print(f"Columns remaining: {len(master_df.columns)}")


    # --- IMPROVEMENT 2: Date Sorting ---
    if args.sort_by:
        if args.sort_by in master_df.columns:
            print(f"Sorting by date column: {args.sort_by}")
            # Convert to datetime objects for accurate chronological sorting
            master_df[args.sort_by] = pd.to_datetime(master_df[args.sort_by], errors='coerce')
            master_df = master_df.sort_values(by=args.sort_by, ascending=True)
        else:
            print(f"Warning: Sort column '{args.sort_by}' not found in data.")

    # --- IMPROVEMENT 3: Remove Duplicate Rows ---
    before_dup = len(master_df)
    master_df = master_df.drop_duplicates()
    print(f"Removed {before_dup - len(master_df)} duplicate rows.")

    # 3. Row Filtering (Regex Exclusions)
    if args.exclude:
        print(f"Applying filters: {args.exclude}")
        # Combine row content into a single string for rapid regex searching
        row_strings = master_df.astype(str).agg(' '.join, axis=1)

        # Combine all exclude patterns into one "OR" regex
        combined_exclude_re = '|'.join(args.exclude)
        mask_to_drop = row_strings.str.contains(combined_exclude_re, regex=True, na=False)

        initial_count = len(master_df)
        master_df = master_df[~mask_to_drop]
        print(f"Filtered out {mask_to_drop.sum()} rows. {len(master_df)} rows remaining.")

    # 4. Save
    master_df.to_csv(args.output, index=False)
    print(f"\nSuccessfully unified {len(target_files)} files into '{args.output}'.")


if __name__ == "__main__":

    try:
        # Execute the check before any heavy imports
        check_environment()
        main()

    except Exception as ex:
        # This captures the full trace, including file and line number
        error_details = traceback.format_exc()
        print(f"Critical Error:\n{error_details}", file=sys.stderr)
        print("[Done]", file=sys.stderr)