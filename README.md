# python-tools

A collection of small, single-file Python command-line utilities — no shared framework,
each script is independent and can be copied out and used on its own.

**By [LanDen Labs](https://github.com/landenlabs) (2026)**

---

## Tools

| Script | Purpose |
| --- | --- |
| [`py-tool.py`](#py-toolpy) | pip/python maintenance: list, install, upgrade, scan imports for missing packages |
| [`make-colors.py`](#make-colorspy) | Generate PNG color-box, gradient, or alpha images from a CSV of RGBA values |
| [`colorize.py`](#colorizepy) | Colorize regex matches in piped text using ANSI escape codes |
| [`clean-html.py`](#clean-htmlpy) | Strip styling/scripts and attributes from an HTML or MHTML file |
| [`merge_csv.py`](#merge_csvpy) | Merge multiple CSVs with regex filtering and column alignment |

---

## py-tool.py

Common pip/python maintenance commands, in one place — list, install, upgrade,
freeze, and scan `.py` files/directories for imports that aren't installed.

**Requirements:** Python 3.9+ (stdlib only)

```bash
python3 py-tool.py --list
python3 py-tool.py --outdated
python3 py-tool.py --install requests numpy
python3 py-tool.py --uninstall requests
python3 py-tool.py --upgrade numpy
python3 py-tool.py --upgrade-all
python3 py-tool.py --show numpy
python3 py-tool.py --freeze
python3 py-tool.py --check
python3 py-tool.py --info

# Scan source files/directories for imports missing from the environment,
# then optionally install whatever's missing.
python3 py-tool.py --scan-missing file1.py file2.py dir1
python3 py-tool.py --scan-install file1.py file2.py dir1
```

`--install`/`--upgrade`/`--scan-install` always run
`pip install --user --break-system-packages`, which installs into your user
site-packages directory and bypasses Homebrew's externally-managed-environment
guard without touching Homebrew's own packages. `--scan-missing` maps common
import names to their pip package (e.g. `PIL` → `Pillow`, `cv2` → `opencv-python`,
`yaml` → `PyYAML`) so it can suggest the right install target.

---

## make-colors.py

Generate PNG color-box, gradient, or alpha-checkerboard images from a CSV of
RGBA values, or convert between color-palette formats.

**Requirements:** Python 3.9+, Pillow (`pip install Pillow`)

```bash
# Color boxes over white / checkerboard / black backgrounds, quad decimal CSV
python3 make-colors.py --colorboxes -i colors.csv -o boxes.png

# Color boxes from packed hex RGBA/ARGB values
python3 make-colors.py --colorboxes -i colors.csv -o boxes.png --color-values rgba --color-unit hex

# Smooth N-step gradient interpolated from CSV color stops
python3 make-colors.py --gradient 256 -i stops.csv -o gradient.png --size 16x256

# Gradient with range labels (vertical only)
python3 make-colors.py --gradient 256 -i stops.csv -o gradient.png --range 0.00:0.77

# White alpha gradient over a checkerboard background, no CSV needed
python3 make-colors.py --alpha -o alpha.png

# Convert a JSON color-gradient palette to CSV (red,green,blue,alpha,value,label)
python3 make-colors.py --from-json -i palette.json -o palette.csv

# Android Vector Drawable XML gradient from Step:/A:/R:/G:/B: input
python3 make-colors.py --make-avg -i vil-colors.txt -o gradient.xml
```

CSV input supports three layouts via `--color-values`: `quad` (four
`red,green,blue,alpha` fields, the default), `rgba` (one packed 32-bit
`RRGGBBAA` value), or `argb` (one packed 32-bit `AARRGGBB` value) — each in
either decimal or hex (`--color-unit`). Lines starting with `#` and blank
lines are ignored.

---

## colorize.py

Colorize regex matches in piped text using ANSI escape codes — like `grep
--color` but with multiple independent colors/patterns in a single pass.

**Requirements:** Python 3.9+ (stdlib only)

```bash
# Single color, one pattern
tail -f app.log | python3 colorize.py --color red --find "ERROR"

# Single color, multiple patterns
tail -f app.log | python3 colorize.py --color red --find "ERROR" "FATAL" "panic"

# Multiple colors, each with its own patterns
tail -f app.log | python3 colorize.py \
    --color red    --find "ERROR" "FATAL" \
    -c yellow -f "WARN" \
    -c green  -f "OK" "success" "done"

# Mix hex / RGB / names freely
cat access.log | python3 colorize.py \
    --color "#ff8800" --find "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" \
    --color "0,200,255" --find "GET" "POST" "PUT" "DELETE"

# No --color/--find: bare positional args are joined and used as a single yellow regex
tail -f app.log | python3 colorize.py "connection (refused|reset)"
```

`--color` must appear before any `--find` — each `--color` opens a new group
that subsequent `--find` patterns attach to, until the next `--color`. Colors
accept a name (`red`, `green`, …), 3/6-digit hex (`#f80`, `#ff8800`), or a
decimal `r,g,b` triple. Use `--ignore-case`/`-i` for case-insensitive matching
across all patterns, or the inline `(?i:...)`/`(?-i:...)` regex flag to
toggle case for a single pattern. Honors the `NO_COLOR` environment variable
and `--no-color`.

---

## clean-html.py

Strip `<style>`, `<script>`, `<link>`, and `<font>` tags (with their contents)
and remove every attribute (colors, fonts, classes, ids, etc.) from an HTML or
MHTML file — useful for turning a saved web page into plain, readable markup.

**Requirements:** Python 3.9+, beautifulsoup4 (`pip install beautifulsoup4`)

```bash
# Clean an HTML file, print result to the console
python3 clean-html.py --input page.html

# Clean an MHTML (saved web page) archive
python3 clean-html.py --input page.mhtml

# Write the cleaned result to a file instead of the console
python3 clean-html.py --input page.html --output clean.html
```

`.mhtml`/`.mht` inputs are parsed as MIME archives; the `text/html` part is
extracted and cleaned.

---

## merge_csv.py

Merge every CSV under a directory (or matching a glob) into a single CSV,
with regex-based file inclusion, row exclusion, a minimum-column filter, and
optional date-based sorting.

**Requirements:** Python 3.9+, pandas, NumPy < 2.0 (the script refuses to run
against NumPy 2.x — see the version check at startup)

```bash
python3 merge_csv.py --path ./data --output master_unified.csv

# Only merge files matching a pattern, drop rows matching an exclude regex,
# require at least 12 columns, and sort by a date column
python3 merge_csv.py --path './data/*.csv' \
    --include '\d{4}-\d{2}\.csv$' \
    --exclude '^#' \
    --min-columns 12 \
    --sort-by date \
    --output master_unified.csv
```

`--exclude` can be repeated to apply multiple row-exclusion regexes.

---

## Installation

Each script is standalone — copy the one you need, or clone the whole
directory. Install dependencies as needed per tool (see **Requirements**
above), or use `py-tool.py` itself:

```bash
python3 py-tool.py --scan-install make-colors.py clean-html.py merge_csv.py
```

`install-python-modules.csh` is a one-line convenience install for `pandas`
(used by `merge_csv.py`) on macOS/Linux.

---

## License

Apache 2.0 © [LanDen Labs](https://github.com/landenlabs) 2026
