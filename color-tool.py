#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Color Tool - Generate color box and gradient PNG images from CSV input"""

import argparse
import csv
import os
import sys
import traceback

VERSION = "v1.2 (Apr-2026)"

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def require_pil():
    if not HAS_PIL:
        print("Error: Pillow is required. Install with 'pip install Pillow'.", file=sys.stderr)
        sys.exit(1)


def load_font(size=11):
    """Try common monospace TTF paths; fall back to PIL built-in."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _font_height(font):
    """Return pixel height of a font, compatible with old and new Pillow."""
    try:
        bb = font.getbbox("Mg0")
        return bb[3] - bb[1]
    except AttributeError:
        return font.getsize("Mg0")[1]


def _font_width(font, text):
    """Return pixel width of text, compatible with old and new Pillow."""
    try:
        bb = font.getbbox(text)
        return bb[2] - bb[0]
    except AttributeError:
        return font.getsize(text)[0]


def _fmt_value(v):
    """Format a float label value with up to 4 significant digits."""
    return f"{v:.4g}"


def parse_range(range_str):
    """Parse 'from:to' string into (float, float). Exits on error."""
    try:
        parts = range_str.split(':')
        if len(parts) != 2:
            raise ValueError("expected FROM:TO")
        return float(parts[0]), float(parts[1])
    except ValueError as e:
        print(f"Error: invalid --range '{range_str}': {e}", file=sys.stderr)
        sys.exit(1)


def parse_color_value(val_str, unit):
    """Parse a single color component. unit: 'hex' or 'dec'."""
    val_str = val_str.strip()
    if unit == 'hex':
        return int(val_str, 16)
    return int(val_str)


def parse_packed_value(val_str, unit, layout):
    """
    Parse a single packed 32-bit value into (r, g, b, a).
    unit:   'hex' | 'dec'
    layout: 'rgba' (RRGGBBAA) | 'argb' (AARRGGBB)
    """
    val_str = val_str.strip()
    val = int(val_str, 16) if unit == 'hex' else int(val_str)
    b0 = (val >> 24) & 0xFF
    b1 = (val >> 16) & 0xFF
    b2 = (val >>  8) & 0xFF
    b3 =  val        & 0xFF
    if layout == 'rgba':
        return b0, b1, b2, b3   # r, g, b, a
    else:                        # argb
        return b1, b2, b3, b0   # r, g, b, a  (a was b0)


def load_colors(input_file, unit, color_values, verbose=False):
    """
    Load RGBA colors from CSV. Returns list of (r, g, b, a) tuples (0-255).
    unit:         'hex' | 'dec'             — numeric base of values
    color_values: 'quad' | 'rgba' | 'argb' — CSV layout
    """
    colors = []
    addHeader = True
    packed = color_values in ('rgba', 'argb')
    with open(input_file, newline='') as f:
        reader = csv.reader(f)
        for lineno, row in enumerate(reader, 1):
            if not row or row[0].strip().startswith('#'):
                continue
            try:
                if packed:
                    if not row[0].strip():
                        continue
                    r, g, b, a = parse_packed_value(row[0], unit, color_values)
                else:
                    if len(row) < 4:
                        print(f"Warning: line {lineno}: fewer than 4 fields, skipping.", file=sys.stderr)
                        continue
                    r = parse_color_value(row[0], unit)
                    g = parse_color_value(row[1], unit)
                    b = parse_color_value(row[2], unit)
                    a = parse_color_value(row[3], unit)
                colors.append((r, g, b, a))
                if verbose:
                    if addHeader:
                        print("#  Line     red  green   blue   alpha", file=sys.stderr)
                        addHeader = False
                    print(f"  {lineno:4d}:  {r:3d}/{r:2x} {g:3d}/{g:2x} {b:3d}/{b:2x} {a:3d}/{a:2x}/{a / 255:.2f}%", file=sys.stderr)
            except ValueError as e:
                print(f"Warning: line {lineno}: parse error: {e}, skipping.", file=sys.stderr)
    if verbose:
        print(f"Loaded {len(colors)} color(s) from {input_file}", file=sys.stderr)
    return colors


def make_box(r, g, b, a, bg, size, checker_sq=5):
    """
    Create a square RGBA image with background composited under color (r,g,b,a).
    bg: 'checker' or an (R,G,B) tuple.
    """
    img = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(img)

    if bg == 'checker':
        c1 = (160, 180, 205, 255)   # blue-grey dark
        c2 = (205, 215, 228, 255)   # blue-grey light
        for row in range(0, size, checker_sq):
            for col in range(0, size, checker_sq):
                c = c1 if (row // checker_sq + col // checker_sq) % 2 == 0 else c2
                draw.rectangle([col, row, col + checker_sq - 1, row + checker_sq - 1], fill=c)
    else:
        draw.rectangle([0, 0, size - 1, size - 1], fill=(*bg, 255))

    color_layer = Image.new('RGBA', (size, size), (r, g, b, a))
    img.alpha_composite(color_layer)
    return img


def fmt_rgba(val):
    """Format a 0-255 component as 'dec/HEX'."""
    return f"{val}/{val:02X}"


def fmt_alpha(a):
    """Format alpha as 'dec/HEX/pct'."""
    return f"{a}/{a:02X}/{a / 255:.2f}"


# ---------------------------------------------------------------------------
# --colorboxes command
# ---------------------------------------------------------------------------

def cmd_colorboxes(args):
    """Generate a PNG showing each color over white, checkerboard, and black."""
    require_pil()

    if args.verbose:
        print(f"Loading colors from {args.input} (unit={args.color_unit}, layout={args.color_values})", file=sys.stderr)

    colors = load_colors(args.input, args.color_unit, args.color_values, verbose=args.verbose)
    if not colors:
        print("Error: no colors loaded from input file.", file=sys.stderr)
        sys.exit(1)

    BOX = 30       # box side in pixels
    PAD = 6        # padding between elements
    HDR_H = 18     # header row height
    ROW_H = BOX + PAD
    COL_W = 110    # width of each text column (verbose only)

    # x-positions for 3 boxes
    x_white = PAD
    x_check = x_white + BOX + PAD
    x_black = x_check + BOX + PAD
    x_text  = x_black + BOX + PAD * 2  # used only in verbose mode

    if args.verbose:
        img_w = x_text + COL_W * 4 + PAD
    else:
        img_w = x_black + BOX + PAD
    img_h = HDR_H + len(colors) * ROW_H + PAD

    img = Image.new('RGB', (img_w, img_h), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    font = load_font(11)

    # Header
    hdr_y = 3
    hdr_color = (60, 60, 60)
    if args.verbose:
        draw.text((x_white, hdr_y), "White", fill=hdr_color, font=font)
        draw.text((x_check, hdr_y), "Check", fill=hdr_color, font=font)
        draw.text((x_black, hdr_y), "Black", fill=hdr_color, font=font)
        for col_idx, label in enumerate(
            ["Red (dec/hex)", "Green (dec/hex)", "Blue (dec/hex)", "Alpha (dec/hex/pct)"]
        ):
            draw.text((x_text + COL_W * col_idx, hdr_y), label, fill=hdr_color, font=font)

    # Color rows
    for idx, (r, g, b, a) in enumerate(colors):
        y = HDR_H + idx * ROW_H

        for bx, bg in [
            (x_white, (255, 255, 255)),
            (x_check, 'checker'),
            (x_black, (0, 0, 0)),
        ]:
            box_img = make_box(r, g, b, a, bg, BOX)
            img.paste(box_img.convert('RGB'), (bx, y))
            # 1-pixel border for definition
            draw.rectangle([bx, y, bx + BOX - 1, y + BOX - 1], outline=(120, 120, 120))

        if args.verbose:
            # Text labels, vertically centered in row
            ty = y + BOX // 2 - 6
            for col_idx, text in enumerate(
                [fmt_rgba(r), fmt_rgba(g), fmt_rgba(b), fmt_alpha(a)]
            ):
                draw.text((x_text + COL_W * col_idx, ty), text, fill=(0, 0, 0), font=font)

    img.save(args.output)
    print(f"Saved {args.output} ({img_w}x{img_h}px, {len(colors)} color(s))")


# ---------------------------------------------------------------------------
# --gradient command
# ---------------------------------------------------------------------------

def lerp(a, b, t):
    return a + (b - a) * t


def gradient_color_at(stops, t):
    """Interpolate RGBA color at position t in [0.0, 1.0] across color stops."""
    n = len(stops)
    if n == 1:
        return stops[0]
    seg = t * (n - 1)
    i = min(int(seg), n - 2)
    f = seg - i
    return (
        round(lerp(stops[i][0], stops[i + 1][0], f)),
        round(lerp(stops[i][1], stops[i + 1][1], f)),
        round(lerp(stops[i][2], stops[i + 1][2], f)),
        round(lerp(stops[i][3], stops[i + 1][3], f)),
    )


def cmd_gradient(args):
    """Generate a smooth gradient PNG from CSV color stops."""
    require_pil()

    if args.verbose:
        print(f"Loading colors from {args.input} (unit={args.color_unit}, layout={args.color_values})", file=sys.stderr)

    stops = load_colors(args.input, args.color_unit, args.color_values, verbose=args.verbose)
    if not stops:
        print("Error: no colors loaded from input file.", file=sys.stderr)
        sys.exit(1)
    if len(stops) < 2:
        print("Error: --gradient requires at least 2 color stops in CSV.", file=sys.stderr)
        sys.exit(1)

    try:
        w_str, h_str = args.size.lower().split('x')
        img_w, img_h = int(w_str), int(h_str)
        if img_w < 1 or img_h < 1:
            raise ValueError("dimensions must be positive")
    except (ValueError, AttributeError):
        print(f"Error: invalid --size '{args.size}', expected WxH e.g. 16x256.", file=sys.stderr)
        sys.exit(1)

    num_steps = args.gradient
    if num_steps < 2:
        print("Error: --gradient N requires N >= 2.", file=sys.stderr)
        sys.exit(1)

    # Gradient runs along the longer axis
    vertical = img_h >= img_w

    # Parse --range and compute label layout if applicable
    range_vals = None
    label_font = None
    if args.range and vertical:
        range_vals = parse_range(args.range)
        label_font = load_font(11)
        fh = _font_height(label_font)
        min_spacing = fh + 3   # minimum pixels between label baselines
        n_stops = len(stops)
        min_h = (n_stops - 1) * min_spacing + fh
        if img_h < min_h:
            if args.verbose:
                print(f"Enlarging gradient height from {img_h} to {min_h}px to fit {n_stops} labels.", file=sys.stderr)
            img_h = min_h

    # Precompute N gradient colors uniformly spaced across the stops
    gradient = [
        gradient_color_at(stops, i / (num_steps - 1))
        for i in range(num_steps)
    ]

    grad_img = Image.new('RGBA', (img_w, img_h))
    draw = ImageDraw.Draw(grad_img)

    if vertical:
        for i, color in enumerate(gradient):
            y0 = round(i * img_h / num_steps)
            y1 = round((i + 1) * img_h / num_steps)
            if y0 < img_h:
                draw.rectangle([0, y0, img_w - 1, max(y0, min(y1 - 1, img_h - 1))], fill=color)
    else:
        for i, color in enumerate(gradient):
            x0 = round(i * img_w / num_steps)
            x1 = round((i + 1) * img_w / num_steps)
            if x0 < img_w:
                draw.rectangle([x0, 0, max(x0, min(x1 - 1, img_w - 1)), img_h - 1], fill=color)

    # Compose gradient with range labels on the right
    if range_vals is not None:
        range_from, range_to = range_vals
        n_stops = len(stops)
        fh = _font_height(label_font)
        TICK_W = 5
        GAP = 4

        # Build (y_pixel, label_text) for each stop
        labels = []
        for i in range(n_stops):
            value = range_from + i * (range_to - range_from) / (n_stops - 1)
            y_pos = round(i * (img_h - 1) / (n_stops - 1))
            labels.append((y_pos, _fmt_value(value)))

        max_lw = max(_font_width(label_font, t) for _, t in labels)
        grad_label_w = img_w + TICK_W + GAP + max_lw + GAP

        # Padding: generous enough that edge labels and the title never clip
        SIDE_PAD = max(fh + 6, 16)
        TITLE_GAP = 6   # gap between title baseline and gradient top
        title_text = os.path.basename(args.input)
        title_fh = _font_height(label_font)
        PAD_TOP = SIDE_PAD + title_fh + TITLE_GAP

        total_w = SIDE_PAD + grad_label_w + SIDE_PAD
        total_h = PAD_TOP + img_h + SIDE_PAD

        out_img = Image.new('RGB', (total_w, total_h), (255, 255, 255))
        out_img.paste(grad_img.convert('RGB'), (SIDE_PAD, PAD_TOP))

        odraw = ImageDraw.Draw(out_img)

        # Title: centered over the full image, sitting in the top padding zone
        title_w = _font_width(label_font, title_text)
        title_x = (total_w - title_w) // 2
        title_y = SIDE_PAD - title_fh // 2   # vertically centered in top pad
        odraw.text((title_x, title_y), title_text, fill=(40, 40, 40), font=label_font)

        # Labels and ticks, offset into padded coordinate space
        for y_pos, text in labels:
            ay = PAD_TOP + y_pos
            ax = SIDE_PAD + img_w
            # Tick mark connecting gradient edge to label
            odraw.line([ax, ay, ax + TICK_W - 1, ay], fill=(60, 60, 60))
            # Label, vertically centered on the tick row
            ly = ay - fh // 2
            ly = max(0, min(ly, total_h - fh))
            odraw.text((ax + TICK_W + GAP, ly), text, fill=(20, 20, 20), font=label_font)
    else:
        out_img = grad_img

    out_img.save(args.output)
    orient = "vertical" if vertical else "horizontal"
    range_msg = f", range {range_vals[0]}:{range_vals[1]}" if range_vals else ""
    print(
        f"Saved {args.output} "
        f"({out_img.width}x{out_img.height}px, {num_steps} steps, {orient}, {len(stops)} stops{range_msg})"
    )


# ---------------------------------------------------------------------------
# --alpha command
# ---------------------------------------------------------------------------

def cmd_alpha(args):
    """Generate a white alpha gradient over a checkerboard, with margin annotations."""
    require_pil()

    BG_SIZE   = 512
    SQUARE    = 16    # 512/16 = 32 squares per row/col
    GRAD_SIZE = 500
    MARGIN    = 40

    LIGHT_BLUE  = (173, 216, 230)
    LIGHT_GREEN = (144, 238, 144)

    # gap between bg edge and overlay edge on each side
    offset = (BG_SIZE - GRAD_SIZE) // 2   # = 6 px

    # Checkerboard background
    bg = Image.new('RGBA', (BG_SIZE, BG_SIZE))
    draw_bg = ImageDraw.Draw(bg)
    for row in range(0, BG_SIZE, SQUARE):
        for col in range(0, BG_SIZE, SQUARE):
            color = LIGHT_BLUE if (row // SQUARE + col // SQUARE) % 2 == 0 else LIGHT_GREEN
            draw_bg.rectangle([col, row, col + SQUARE - 1, row + SQUARE - 1], fill=(*color, 255))

    # White diagonal gradient: upper-left = alpha 0, lower-right = alpha 255
    # Center 300x300 hole punched out (alpha=0 so background shows through unaltered)
    HOLE = 300
    hole_x0 = (GRAD_SIZE - HOLE) // 2   # = 100
    hole_y0 = (GRAD_SIZE - HOLE) // 2   # = 100
    hole_x1 = hole_x0 + HOLE            # = 400
    hole_y1 = hole_y0 + HOLE            # = 400
    max_sum = 2 * (GRAD_SIZE - 1)
    pixels = bytes(
        v
        for y in range(GRAD_SIZE)
        for x in range(GRAD_SIZE)
        for v in (255, 255, 255,
                  0 if hole_x0 <= x < hole_x1 and hole_y0 <= y < hole_y1
                  else round((x + y) / max_sum * 255))
    )
    grad = Image.frombytes('RGBA', (GRAD_SIZE, GRAD_SIZE), pixels)

    bg.alpha_composite(grad, dest=(offset, offset))

    # Compose with white margins
    total_w = BG_SIZE + 2 * MARGIN
    total_h = BG_SIZE + 2 * MARGIN
    out = Image.new('RGB', (total_w, total_h), (255, 255, 255))
    out.paste(bg.convert('RGB'), (MARGIN, MARGIN))

    draw = ImageDraw.Draw(out)
    font = load_font(10)
    fh   = _font_height(font)

    # Tic geometry relative to the bg edge:
    #   TICK_OUT: stub extending outward into the margin (toward the label)
    #   TICK_IN:  line crossing the gap (offset px) then 10px into the overlay
    TICK_OUT = 4
    TICK_IN  = offset + 10   # = 16 px inside the bg edge

    bg_left  = MARGIN
    bg_top   = MARGIN
    bg_right = MARGIN + BG_SIZE - 1
    bg_bot   = MARGIN + BG_SIZE - 1

    STEPS = 10
    for i in range(STEPS + 1):
        label = f"{i * 10}%"
        lw    = _font_width(font, label)
        t     = i / STEPS
        # Tic position aligned with overlay (not background) edges
        ov_pos = round(t * (GRAD_SIZE - 1))
        tic_x  = MARGIN + offset + ov_pos
        tic_y  = MARGIN + offset + ov_pos

        # Top: stub up into margin, line down into overlay
        draw.line([(tic_x, bg_top - TICK_OUT), (tic_x, bg_top + TICK_IN)], fill=(60, 60, 60))
        draw.text((tic_x - lw // 2, bg_top - TICK_OUT - fh - 1), label, fill=(40, 40, 40), font=font)

        # Bottom: stub down into margin, line up into overlay
        draw.line([(tic_x, bg_bot + TICK_OUT), (tic_x, bg_bot - TICK_IN)], fill=(60, 60, 60))
        draw.text((tic_x - lw // 2, bg_bot + TICK_OUT + 1), label, fill=(40, 40, 40), font=font)

        # Left: stub left into margin, line right into overlay
        draw.line([(bg_left - TICK_OUT, tic_y), (bg_left + TICK_IN, tic_y)], fill=(60, 60, 60))
        draw.text((bg_left - TICK_OUT - lw - 1, tic_y - fh // 2), label, fill=(40, 40, 40), font=font)

        # Right: stub right into margin, line left into overlay
        draw.line([(bg_right + TICK_OUT, tic_y), (bg_right - TICK_IN, tic_y)], fill=(60, 60, 60))
        draw.text((bg_right + TICK_OUT + 1, tic_y - fh // 2), label, fill=(40, 40, 40), font=font)

    out.save(args.output)
    print(f"Saved {args.output} ({total_w}x{total_h}px, {BG_SIZE}x{BG_SIZE} bg, {GRAD_SIZE}x{GRAD_SIZE} overlay)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"color-tool {VERSION}\nGenerate PNG color-box, gradient, or alpha images from a CSV of RGBA values.",
        epilog="""Examples:
  # Color boxes, quad decimal (default):
  color-tool.py --colorboxes -i colors.csv -o boxes.png
  color-tool.py --colorboxes -i colors.csv -o boxes.png -v

  # Color boxes, quad hex:
  color-tool.py --colorboxes -i colors.csv -o boxes.png --color-unit hex

  # Color boxes, packed rgba hex (e.g. FF0000FF = opaque red):
  color-tool.py --colorboxes -i colors.csv -o boxes.png --color-values rgba --color-unit hex

  # Color boxes, packed argb hex (e.g. FFFF0000 = opaque red):
  color-tool.py --colorboxes -i colors.csv -o boxes.png --color-values argb --color-unit hex

  # Gradient from CSV stops:
  color-tool.py --gradient 128 -i stops.csv -o gradient.png --size 16x256
  color-tool.py --gradient 256 -i stops.csv -o ramp.png --size 256x16

  # Gradient with range labels (vertical only):
  color-tool.py --gradient 256 -i stops.csv -o gradient.png --size 16x256 --range 0.00:0.77

  # Alpha gradient over checkerboard (no CSV needed):
  color-tool.py --alpha
  color-tool.py --alpha -o my_alpha.png

CSV layouts (--color-values):
  quad  — 4 comma-separated fields: red,green,blue,alpha  (default)
            255,0,0,255       decimal opaque red
            FF,00,00,FF       hex     opaque red

  rgba  — 1 packed 32-bit value: RRGGBBAA byte order
            4278190335        decimal  (0xFF0000FF, opaque red)
            FF0000FF          hex

  argb  — 1 packed 32-bit value: AARRGGBB byte order
            4294901760        decimal  (0xFFFF0000, opaque red)
            FFFF0000          hex

  # Lines starting with # and blank lines are ignored.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--colorboxes', action='store_true',
        help='Render each color over white, blue/grey checkerboard, and black backgrounds',
    )
    mode_group.add_argument(
        '--gradient', type=int, metavar='N',
        help='Render a smooth N-step gradient interpolated from CSV color stops',
    )
    mode_group.add_argument(
        '--alpha', '-a', action='store_true',
        help='Render a white alpha gradient (UL=0%%, LR=100%%) over a checkerboard background',
    )

    parser.add_argument('--input',  '-i', required=False, metavar='FILE',
                        help='Input CSV file (required for --colorboxes and --gradient)')
    parser.add_argument('--output', '-o', required=False, default=None, metavar='FILE',
                        help='Output PNG file (default: alpha.png for --alpha)')
    parser.add_argument('--color-unit', choices=['dec', 'hex'], default='dec',
                        help='Numeric base of values in CSV: dec (default) or hex')
    parser.add_argument('--color-values', choices=['quad', 'rgba', 'argb'], default='quad',
                        help='CSV layout: quad=4 fields r,g,b,a (default); rgba or argb=1 packed 32-bit value')
    parser.add_argument('--size', default='16x256', metavar='WxH',
                        help='Image size for --gradient (default: 16x256)')
    parser.add_argument('--range', metavar='FROM:TO',
                        help='Value range for stop labels on a vertical gradient (e.g. 0.00:0.77)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args, unknown = parser.parse_known_args()
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    # Apply mode-specific defaults and validate required args
    if args.alpha:
        if args.output is None:
            args.output = 'alpha.png'
    else:
        if args.input is None:
            parser.error("--input / -i is required for --colorboxes and --gradient")
        if args.output is None:
            parser.error("--output / -o is required for --colorboxes and --gradient")

    try:
        if args.colorboxes:
            cmd_colorboxes(args)
        elif args.gradient is not None:
            cmd_gradient(args)
        elif args.alpha:
            cmd_alpha(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        sys.exit(0)
