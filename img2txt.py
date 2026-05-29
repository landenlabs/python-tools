#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""img2txt - Extract text from well-formed, unrotated PNG images using OCR."""

import argparse
import glob
import os
import sys

VERSION = "v1.00.00 (May-2026)"


def expand_inputs(patterns):
    """Expand glob patterns and de-duplicate while preserving order."""
    seen = set()
    files = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches:
            if any(ch in pattern for ch in '*?['):
                print(f"warning: no files matched: {pattern}", file=sys.stderr)
            else:
                print(f"warning: file not found: {pattern}", file=sys.stderr)
            continue
        for path in sorted(matches):
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def ocr_image(path, lang, psm, oem, config_extra, scale):
    """Run OCR on a single image file and return extracted text.

    scale: float multiplier, or 'auto' to upscale small images so the
    short side is at least ~1200 px (tesseract reads small fonts poorly
    below ~30 px x-height).
    """
    from PIL import Image
    import pytesseract

    config_parts = []
    if psm is not None:
        config_parts.append(f"--psm {psm}")
    if oem is not None:
        config_parts.append(f"--oem {oem}")
    if config_extra:
        config_parts.append(config_extra)
    config = " ".join(config_parts)

    with Image.open(path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        factor = 1.0
        if scale == "auto":
            short = min(img.width, img.height)
            if short < 1200:
                factor = 1200.0 / short
        else:
            factor = float(scale)

        if factor != 1.0:
            new_size = (int(img.width * factor), int(img.height * factor))
            img = img.resize(new_size, Image.LANCZOS)

        return pytesseract.image_to_string(img, lang=lang, config=config)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from PNG images using Tesseract OCR.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  img2txt.py --input image1.png\n"
            "  img2txt.py --input '*.png'\n"
            "  img2txt.py --input image1.png --input 'dir1/*.png'\n"
            "  img2txt.py --input image1.png --output out.txt\n"
        ),
    )
    parser.add_argument(
        "--input", "-i",
        action="append",
        required=True,
        metavar="GLOB",
        help="Image file or glob pattern. May be repeated.",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write all extracted text to FILE (default: stdout).",
    )
    parser.add_argument(
        "--lang", "-l",
        default="eng",
        help="Tesseract language code (default: eng).",
    )
    parser.add_argument(
        "--psm",
        type=int,
        default=6,
        help="Tesseract page segmentation mode (default: 6 = uniform block of text).",
    )
    parser.add_argument(
        "--oem",
        type=int,
        default=None,
        help="Tesseract OCR engine mode (default: tesseract default).",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Extra config string passed to tesseract.",
    )
    parser.add_argument(
        "--scale",
        default="auto",
        help="Image upscale factor before OCR. Number (e.g. 2, 3.0) or 'auto' "
             "to upscale small images (default: auto).",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress per-file header banner when processing multiple files.",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"img2txt {VERSION}",
    )

    args = parser.parse_args()

    try:
        from PIL import Image  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError as exc:
        print(f"error: missing dependency: {exc.name}", file=sys.stderr)
        print("install with: pip install pillow pytesseract", file=sys.stderr)
        return 2

    files = expand_inputs(args.input)
    if not files:
        print("error: no input files to process", file=sys.stderr)
        return 1

    out_fh = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    show_header = (len(files) > 1) and not args.no_header
    exit_code = 0

    try:
        for path in files:
            if not os.path.isfile(path):
                print(f"warning: not a file: {path}", file=sys.stderr)
                exit_code = 1
                continue
            try:
                text = ocr_image(path, args.lang, args.psm, args.oem, args.config, args.scale)
            except Exception as exc:
                print(f"error: {path}: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            if show_header:
                out_fh.write(f"===== {path} =====\n")
            out_fh.write(text)
            if not text.endswith("\n"):
                out_fh.write("\n")
    finally:
        if args.output:
            out_fh.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
