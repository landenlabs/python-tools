#!/usr/bin/env python3
"""colorize - Colorize regex matches in piped text using ANSI escape codes."""

import argparse
import os
import re
import sys
import traceback

VERSION = "v1.00.00 (May-2026)"


# ---------------------------------------------------------------------------
# Color support
# ---------------------------------------------------------------------------

def init_colors():
    """
    Return True if ANSI color output should be emitted.

    Honors the NO_COLOR convention (https://no-color.org/). On Windows,
    enables virtual terminal processing on the console so escape codes
    render in legacy cmd.exe / older PowerShell; modern terminals
    (Windows Terminal, VS Code, PowerShell 7+) already have it on.

    Unlike git-tool.py this does NOT gate on isatty(), because colorize
    is a pipe filter — its output is almost always being piped or
    redirected, and the user explicitly opted in by invoking it.
    """
    if os.environ.get('NO_COLOR'):
        return False
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong(0)
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------

def get_ansi_color(color_str):
    """Converts various color formats into ANSI escape sequences."""
    color_str = color_str.lower().strip()

    # 1. Standard Names
    names = {
        'black': '30', 'red': '31', 'green': '32', 'yellow': '33',
        'blue': '34', 'magenta': '35', 'cyan': '36', 'white': '37'
    }
    if color_str in names:
        return f"\033[{names[color_str]}m"

    # 2. Hex Long (#xxxxxx)
    if re.match(r'^#[0-9a-f]{6}$', color_str):
        r = int(color_str[1:3], 16)
        g = int(color_str[3:5], 16)
        b = int(color_str[5:7], 16)
        return f"\033[38;2;{r};{g};{b}m"

    # 3. Hex Short (#xxx)
    if re.match(r'^#[0-9a-f]{3}$', color_str):
        r = int(color_str[1]*2, 16)
        g = int(color_str[2]*2, 16)
        b = int(color_str[3]*2, 16)
        return f"\033[38;2;{r};{g};{b}m"

    # 4. Decimal RGB (xxx,xxx,xxx)
    if re.match(r'^\d{1,3},\d{1,3},\d{1,3}$', color_str):
        r, g, b = map(int, color_str.split(','))
        if all(0 <= c <= 255 for c in (r, g, b)):
            return f"\033[38;2;{r};{g};{b}m"

    # Fallback to Yellow if input is invalid
    return "\033[33m"


# ---------------------------------------------------------------------------
# Argument parsing actions
# ---------------------------------------------------------------------------

class ColorAction(argparse.Action):
    """--color NAME opens a new color group."""
    def __call__(self, parser, namespace, values, option_string=None):
        groups = getattr(namespace, 'groups', None) or []
        groups.append({'color': values, 'patterns': []})
        setattr(namespace, 'groups', groups)


class FindAction(argparse.Action):
    """--find P [P ...] appends patterns to the most-recent --color group."""
    def __call__(self, parser, namespace, values, option_string=None):
        groups = getattr(namespace, 'groups', None) or []
        if not groups:
            parser.error("--find must be preceded by --color")
        groups[-1]['patterns'].extend(values)
        setattr(namespace, 'groups', groups)


# ---------------------------------------------------------------------------
# Stream processing
# ---------------------------------------------------------------------------

def colorize_stream(color_pairs, reset_code, stream_in, stream_out):
    """
    Read lines from stream_in, wrap regex matches in their group's color,
    write to stream_out. color_pairs is a list of (color_code, compiled_regex).
    Groups are applied in order; ANSI escapes inserted by an earlier group
    may shadow matches for a later group on the same span.
    """
    for line in stream_in:
        for code, rx in color_pairs:
            if code:
                line = rx.sub(lambda m: f"{code}{m.group(0)}{reset_code}", line)
        stream_out.write(line)
        stream_out.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"colorize {VERSION}\nColorize regex matches in piped text, with multiple color groups.",
        epilog="""Examples:
  # Single color, one pattern:
  tail -f app.log | colorize.py --color red --find "ERROR"

  # Single color, multiple patterns:
  tail -f app.log | colorize.py --color red --find "ERROR" "FATAL" "panic"

  # Multiple colors, each with its own patterns:
  tail -f app.log | colorize.py \\
      --color red    --find "ERROR" "FATAL" \\
      --color yellow --find "WARN" \\
      --color green  --find "OK" "success" "done"

  # Mix hex / RGB / names freely:
  cat access.log | colorize.py \\
      --color "#ff8800" --find "[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+" \\
      --color "0,200,255" --find "GET" "POST" "PUT" "DELETE"

  # Repeat --find under one --color to keep groups visually separated:
  cat src.py | colorize.py \\
      --color cyan --find "\\bdef\\b" --find "\\bclass\\b" \\
      --color magenta --find "\\bself\\b"

Argument order:
  --color must appear before any --find. Each --color opens a new group
  that all following --find patterns attach to, until the next --color.

Color formats:
  name        one of: black, red, green, yellow, blue, magenta, cyan, white
  #xxxxxx     6-digit hex (e.g. #ff8800)
  #xxx        3-digit hex (e.g. #f80)
  r,g,b       decimal RGB triple (e.g. 255,136,0)

Notes:
  Groups are applied in the order given. If an earlier group has already
  wrapped a span in ANSI escapes, a later group's pattern may not match
  inside that span.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("--color", action=ColorAction, metavar="COLOR",
                        help="Open a new color group (name, #xxx, #xxxxxx, or r,g,b)")
    parser.add_argument("--find", action=FindAction, nargs='+', metavar="PATTERN",
                        help="One or more regex patterns for the current --color group")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable color output (pass input through unchanged)")
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()
    groups = getattr(args, 'groups', None) or []

    if not groups:
        parser.error("at least one --color COLOR --find PATTERN [...] pair is required")

    for g in groups:
        if not g['patterns']:
            parser.error(f"--color {g['color']!r} has no --find patterns")

    compiled = []
    for g in groups:
        try:
            rx = re.compile('|'.join(f'(?:{p})' for p in g['patterns']))
        except re.error as err:
            parser.error(f"regex error in --color {g['color']!r} group: {err}")
        compiled.append((g['color'], rx))

    use_color = False if args.no_color else init_colors()
    reset_code = "\033[0m" if use_color else ""

    color_pairs = [
        (get_ansi_color(color) if use_color else "", rx)
        for color, rx in compiled
    ]

    colorize_stream(color_pairs, reset_code, sys.stdin, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
