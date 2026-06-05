#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""clean-html - Strip styling/scripts and attributes from an HTML or MHTML file"""

import argparse
import sys
import traceback

VERSION = "v1.00 (May-2026)"

# Tags removed entirely (with their contents).
STRIP_TAGS = ["style", "script", "link", "font"]


def read_input(path):
    """Read the input file and return its HTML text.

    Files ending in .mhtml/.mht are MIME HTML archives; extract and decode
    their text/html part. Everything else is read as plain HTML.
    """
    if path.lower().endswith((".mhtml", ".mht")):
        return extract_mhtml(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_mhtml(path):
    """Extract the text/html part from an MHTML (MIME HTML) archive."""
    import email

    with open(path, "rb") as f:
        message = email.message_from_binary_file(f)

    for part in message.walk():
        if part.get_content_type() == "text/html":
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            return payload.decode(charset, errors="replace")

    raise ValueError(f"No text/html part found in MHTML file: {path}")


def clean_html(html):
    """Remove style/script/link/font tags and strip all attributes."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("BeautifulSoup not installed. Run: pip install beautifulsoup4")

    soup = BeautifulSoup(html, "html.parser")

    # 1. Remove styling/scripting tags entirely (tag and contents).
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    # 2. Strip all attributes (colors, fonts, classes, etc.) from remaining tags.
    for tag in soup.find_all(True):
        tag.attrs = {}

    return soup.prettify()


def write_output(text, path):
    """Write cleaned HTML to path, or to the console when path is None."""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Cleaned HTML written to {path}  ({len(text):,} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(
        description=f"clean-html {VERSION}\nStrip styling/scripts and attributes from an HTML or MHTML file.",
        epilog="""Examples:
  # Clean an HTML file, print result to the console:
  clean-html.py --input page.html

  # Clean an MHTML (saved web page) archive:
  clean-html.py --input page.mhtml

  # Write the cleaned result to a file instead of the console:
  clean-html.py --input page.html --output clean.html
  clean-html.py -i page.mhtml -o clean.html

Notes:
  Removes <style>, <script>, <link>, and <font> tags (with contents).
  Strips every attribute (colors, fonts, classes, ids, etc.) from all tags.
  .mhtml / .mht inputs are parsed as MIME archives; the text/html part is used.
  Requires beautifulsoup4 (pip install beautifulsoup4).
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument('--input', '-i', required=True, metavar='FILE',
                        help='Input HTML or MHTML file to clean')
    parser.add_argument('--output', '-o', metavar='FILE', default=None,
                        help='Output file for cleaned HTML (default: console)')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    html = read_input(args.input)
    cleaned = clean_html(html)
    write_output(cleaned, args.output)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
