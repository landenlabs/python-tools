#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""stitch-images - Stitch multiple images into a single composite image"""

import argparse
import glob
import os
import sys
import traceback

import cv2
import numpy as np

VERSION = "v1.00.00 (May-2026)"


# ---------------------------------------------------------------------------
# Input expansion
# ---------------------------------------------------------------------------

def expand_inputs(input_args, verbose=False):
    """
    Expand a list of input arguments into a deduplicated list of image paths.

    Each item is handled as follows:
      - Existing file path        -> used directly.
      - Glob/wildcard pattern     -> expanded via glob.glob (sorted).
      - Non-existent literal path -> reported as a warning and skipped.
    """
    paths = []
    seen = set()

    def _add(path):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            paths.append(path)

    for arg in input_args:
        expanded = os.path.expanduser(arg)

        if any(ch in expanded for ch in '*?[]'):
            matches = sorted(glob.glob(expanded))
            if not matches:
                print(f"Warning: pattern matched no files: {arg}", file=sys.stderr)
                continue
            if verbose:
                print(f"Pattern '{arg}' matched {len(matches)} file(s)", file=sys.stderr)
            for m in matches:
                _add(m)
        elif os.path.isfile(expanded):
            _add(expanded)
        else:
            print(f"Warning: input not found: {arg}", file=sys.stderr)

    return paths


# ---------------------------------------------------------------------------
# Common-edge detection (two-pass stitch)
# ---------------------------------------------------------------------------

def _leading_true(mask):
    """Number of leading True values in a 1-D bool array."""
    not_mask = ~mask
    if not not_mask.any():
        return int(mask.size)
    return int(np.argmax(not_mask))


def _trailing_true(mask):
    return _leading_true(mask[::-1])


def detect_common_edges(images):
    """
    Detect the largest top/bottom/left/right edge blocks that are pixel-identical
    across every input image. Requires all images to share the same shape.

    Returns {'top': n, 'bottom': n, 'left': n, 'right': n} in pixels,
    or None if shapes differ.
    """
    if not images:
        return None
    ref = images[0][1]
    shape = ref.shape
    for _, img in images[1:]:
        if img.shape != shape:
            return None

    h, w = shape[:2]
    if len(images) == 1:
        return {'top': h, 'bottom': 0, 'left': w, 'right': 0}

    # Build per-row / per-col "matches everywhere" masks
    row_match = np.ones(h, dtype=bool)
    col_match = np.ones(w, dtype=bool)
    is_color = (ref.ndim == 3)

    for _, img in images[1:]:
        eq = (ref == img)
        if is_color:
            row_match &= eq.all(axis=(1, 2))
            col_match &= eq.all(axis=(0, 2))
        else:
            row_match &= eq.all(axis=1)
            col_match &= eq.all(axis=0)

    top    = _leading_true(row_match)
    bottom = _trailing_true(row_match)
    left   = _leading_true(col_match)
    right  = _trailing_true(col_match)

    # If all rows/cols matched, the whole image is identical — cap so we don't
    # consume the entire image into edge blocks.
    if top + bottom > h:
        bottom = h - top
    if left + right > w:
        right = w - left

    return {'top': top, 'bottom': bottom, 'left': left, 'right': right}


def _print_input_summary(images, orientation, file=sys.stderr):
    """Verbose: one line per input plus a totals line."""
    print(f"Input images ({len(images)}, orientation={orientation}):", file=file)
    total_pixels = 0
    shapes_seen = set()
    for path, img in images:
        h, w = img.shape[:2]
        ch = img.shape[2] if img.ndim == 3 else 1
        total_pixels += h * w
        shapes_seen.add((w, h, ch))
        print(f"  {w:5d} x {h:5d} x {ch}ch  {path}", file=file)
    uniform = "uniform shape" if len(shapes_seen) == 1 else f"{len(shapes_seen)} distinct shapes"
    print(f"  total: {total_pixels:,} pixels across {len(images)} input(s)  ({uniform})",
          file=file)


def _print_output_summary(images, result, orientation, file=sys.stderr):
    """Verbose: compare naive-concat dimensions to actual output and show savings."""
    out_h, out_w = result.shape[:2]
    out_pixels = out_h * out_w

    # Compute the naive (no-dedupe) concat dimensions for comparison
    if orientation == 'vertical':
        # vconcat resizes widths to the minimum
        target_w = min(img.shape[1] for _, img in images)
        naive_h = sum(int(round(img.shape[0] * target_w / img.shape[1])) for _, img in images)
        naive_w = target_w
    elif orientation == 'horizontal':
        target_h = min(img.shape[0] for _, img in images)
        naive_w = sum(int(round(img.shape[1] * target_h / img.shape[0])) for _, img in images)
        naive_h = target_h
    else:
        naive_w, naive_h = out_w, out_h  # 'auto' has no simple naive baseline

    naive_pixels = naive_h * naive_w
    saved = naive_pixels - out_pixels
    pct = (100.0 * saved / naive_pixels) if naive_pixels else 0.0

    print(f"Output image:", file=file)
    print(f"  size:    {out_w} x {out_h}  ({out_pixels:,} pixels)", file=file)
    if orientation in ('vertical', 'horizontal'):
        print(f"  naive:   {naive_w} x {naive_h}  ({naive_pixels:,} pixels)  [no edge dedupe]",
              file=file)
        if saved > 0:
            axis = 'rows' if orientation == 'vertical' else 'cols'
            delta = (naive_h - out_h) if orientation == 'vertical' else (naive_w - out_w)
            print(f"  saved:   {saved:,} pixels ({pct:.1f}%)  ({delta} {axis} of overlap removed)",
                  file=file)
        else:
            print(f"  saved:   0 pixels (no common edges in stitch direction)", file=file)


def _report_common_edges(edges, w, h, orientation, file=sys.stderr):
    """Print a per-edge report of detected common regions."""
    relevant = {
        'vertical':   ('top', 'bottom'),
        'horizontal': ('left', 'right'),
    }.get(orientation, ('top', 'bottom', 'left', 'right'))

    print("  edge detection (common pixels across all inputs):", file=file)
    for name in ('top', 'bottom', 'left', 'right'):
        n = edges[name]
        dim = 'rows' if name in ('top', 'bottom') else 'cols'
        max_dim = h if dim == 'rows' else w
        pct = (100.0 * n / max_dim) if max_dim else 0.0
        used = 'used' if name in relevant and n > 0 else (
               'ignored (no savings for this orientation)' if n > 0 else 'none')
        print(f"    {name:7s} {n:5d} {dim}  ({pct:5.1f}%)  {used}", file=file)


def stitch_with_edge_dedupe(images, orientation, verbose=False, stitcher_mode='scans',
                            stitcher_opts=None, method='overlap', match_band=100,
                            match_thresh=0.8):
    """
    Two-pass stitch: detect identical edge blocks, stitch only the variable
    cores, then reattach a single copy of each saved edge.

    Only applies to 'horizontal' and 'vertical' orientations. For 'auto' or
    when no useful edges are detected, falls through to stitch_images().
    """
    if orientation == 'auto' or len(images) < 2:
        return stitch_images(images, orientation, verbose=verbose,
                             stitcher_mode=stitcher_mode, stitcher_opts=stitcher_opts,
                             method=method, match_band=match_band, match_thresh=match_thresh)

    edges = detect_common_edges(images)
    if edges is None:
        if verbose:
            print("  edge detection: input shapes differ; falling back to single-pass.",
                  file=sys.stderr)
        return stitch_images(images, orientation, verbose=verbose,
                             stitcher_mode=stitcher_mode, stitcher_opts=stitcher_opts,
                             method=method, match_band=match_band, match_thresh=match_thresh)

    ref = images[0][1]
    h, w = ref.shape[:2]
    top, bottom = edges['top'], edges['bottom']
    left, right = edges['left'], edges['right']

    if verbose:
        _report_common_edges(edges, w, h, orientation)

    if orientation == 'vertical':
        # Useful: trim top + bottom. Left/right stay in each core (no savings).
        if top == 0 and bottom == 0:
            return stitch_images(images, orientation, verbose=verbose,
                                 stitcher_mode=stitcher_mode, stitcher_opts=stitcher_opts,
                                 method=method, match_band=match_band, match_thresh=match_thresh)
        top_block = ref[:top, :].copy() if top else None
        bot_block = ref[h - bottom:, :].copy() if bottom else None
        cores = [(p, img[top:h - bottom, :]) for p, img in images]

        core_result, msg = stitch_images(cores, 'vertical', verbose=verbose,
                                         stitcher_mode=stitcher_mode,
                                         stitcher_opts=stitcher_opts, method=method,
                                         match_band=match_band, match_thresh=match_thresh)
        if core_result is None:
            return None, msg

        parts = []
        if top_block is not None: parts.append(top_block)
        parts.append(core_result)
        if bot_block is not None: parts.append(bot_block)
        result = cv2.vconcat(parts) if len(parts) > 1 else parts[0]
        return result, f"{msg} (deduped top={top}, bottom={bottom})"

    if orientation == 'horizontal':
        # Useful: trim left + right. Top/bottom stay in each core.
        if left == 0 and right == 0:
            return stitch_images(images, orientation, verbose=verbose,
                                 stitcher_mode=stitcher_mode, stitcher_opts=stitcher_opts,
                                 method=method, match_band=match_band, match_thresh=match_thresh)
        left_block  = ref[:, :left].copy() if left else None
        right_block = ref[:, w - right:].copy() if right else None
        cores = [(p, img[:, left:w - right]) for p, img in images]

        core_result, msg = stitch_images(cores, 'horizontal', verbose=verbose,
                                         stitcher_mode=stitcher_mode,
                                         stitcher_opts=stitcher_opts, method=method,
                                         match_band=match_band, match_thresh=match_thresh)
        if core_result is None:
            return None, msg

        parts = []
        if left_block is not None:  parts.append(left_block)
        parts.append(core_result)
        if right_block is not None: parts.append(right_block)
        result = cv2.hconcat(parts) if len(parts) > 1 else parts[0]
        return result, f"{msg} (deduped left={left}, right={right})"

    return stitch_images(images, orientation, verbose=verbose,
                         stitcher_mode=stitcher_mode, stitcher_opts=stitcher_opts,
                         method=method, match_band=match_band, match_thresh=match_thresh)


# ---------------------------------------------------------------------------
# Stitching
# ---------------------------------------------------------------------------

# Map cv2 stitcher status codes to human-readable strings
_STATUS_MESSAGES = {
    getattr(cv2, 'Stitcher_OK', 0):                       "OK",
    getattr(cv2, 'Stitcher_ERR_NEED_MORE_IMGS', 1):       "need more images",
    getattr(cv2, 'Stitcher_ERR_HOMOGRAPHY_EST_FAIL', 2):  "homography estimation failed",
    getattr(cv2, 'Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL', 3): "camera parameters adjustment failed",
}


def load_images(paths, verbose=False):
    """Load images from disk; return a list of (path, image). Skips unreadable files."""
    images = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            print(f"Warning: could not read image: {p}", file=sys.stderr)
            continue
        h, w = img.shape[:2]
        if verbose:
            print(f"  loaded {p}  ({w}x{h})", file=sys.stderr)
        images.append((p, img))
    return images


def concat_images(images, orientation):
    """Manually concatenate images along the given orientation, resizing on the
    cross-axis so dimensions match. Returns the composite image."""
    arrs = [img for _, img in images]

    if orientation == 'horizontal':
        # Match heights
        target_h = min(a.shape[0] for a in arrs)
        resized = []
        for a in arrs:
            h, w = a.shape[:2]
            if h != target_h:
                new_w = int(round(w * target_h / h))
                a = cv2.resize(a, (new_w, target_h), interpolation=cv2.INTER_AREA)
            resized.append(a)
        return cv2.hconcat(resized)
    else:
        # vertical: match widths
        target_w = min(a.shape[1] for a in arrs)
        resized = []
        for a in arrs:
            h, w = a.shape[:2]
            if w != target_w:
                new_h = int(round(h * target_w / w))
                a = cv2.resize(a, (target_w, new_h), interpolation=cv2.INTER_AREA)
            resized.append(a)
        return cv2.vconcat(resized)


def _match_cross_axis(arrs, orientation):
    """Resize images on the cross-axis so they share a common width (vertical)
    or height (horizontal). Returns the resized list."""
    if orientation == 'horizontal':
        target_h = min(a.shape[0] for a in arrs)
        out = []
        for a in arrs:
            h, w = a.shape[:2]
            if h != target_h:
                a = cv2.resize(a, (int(round(w * target_h / h)), target_h),
                               interpolation=cv2.INTER_AREA)
            out.append(a)
        return out
    target_w = min(a.shape[1] for a in arrs)
    out = []
    for a in arrs:
        h, w = a.shape[:2]
        if w != target_w:
            a = cv2.resize(a, (target_w, int(round(h * target_w / w))),
                           interpolation=cv2.INTER_AREA)
        out.append(a)
    return out


def _overlap_offset(prev, nxt, orientation, band):
    """Find how much of `prev`'s trailing edge is duplicated at the leading edge
    of `nxt`, using a sliding template match (cv2.matchTemplate).

    Grabs a band from the leading edge of `nxt` (top rows for vertical, left
    cols for horizontal) and slides it across `prev` to locate the best match.

    Returns (overlap, score):
      overlap -> pixels of `prev` that repeat at the start of `nxt`
      score   -> normalized correlation of the best match (0..1)
    """
    if orientation == 'vertical':
        band_px = int(min(band, prev.shape[0], nxt.shape[0]))
        if band_px < 1:
            return 0, 0.0
        templ = nxt[:band_px, :]
        res = cv2.matchTemplate(prev, templ, cv2.TM_CCOEFF_NORMED)
        _, score, _, maxloc = cv2.minMaxLoc(res)
        overlap = prev.shape[0] - maxloc[1]
    else:  # horizontal
        band_px = int(min(band, prev.shape[1], nxt.shape[1]))
        if band_px < 1:
            return 0, 0.0
        templ = nxt[:, :band_px]
        res = cv2.matchTemplate(prev, templ, cv2.TM_CCOEFF_NORMED)
        _, score, _, maxloc = cv2.minMaxLoc(res)
        overlap = prev.shape[1] - maxloc[0]

    if not np.isfinite(score):  # constant/blank band -> no usable correlation
        return 0, 0.0
    return int(max(0, overlap)), float(score)


def stitch_by_overlap(images, orientation, match_band=100, match_thresh=0.8,
                      verbose=False):
    """Stitch images by detecting and removing the duplicated overlap between
    consecutive images (template-match slide), then concatenating.

    For each adjacent pair the leading band of image N+1 is located within
    image N; the duplicated region is dropped from N+1 before joining. Pairs
    whose best match falls below `match_thresh` are joined with no trimming.

    Returns (result_image_or_None, message). Only valid for 'vertical' and
    'horizontal'.
    """
    arrs = _match_cross_axis([img for _, img in images], orientation)
    concat = cv2.vconcat if orientation == 'vertical' else cv2.hconcat
    axis_name = 'rows' if orientation == 'vertical' else 'cols'

    result = arrs[0]
    seams = []          # (overlap, score, used) per seam, for the message
    total_removed = 0
    for i in range(1, len(arrs)):
        prev, nxt = arrs[i - 1], arrs[i]
        overlap, score = _overlap_offset(prev, nxt, orientation, match_band)
        used = score >= match_thresh and overlap > 0
        if used:
            trimmed = nxt[overlap:, :] if orientation == 'vertical' else nxt[:, overlap:]
            total_removed += overlap
        else:
            trimmed = nxt
        seams.append((overlap, score, used))
        if verbose:
            paths = images[i - 1][0], images[i][0]
            if used:
                print(f"  seam {paths[0]} -> {paths[1]}: overlap {overlap} {axis_name} "
                      f"(score {score:.3f}) removed", file=sys.stderr)
            else:
                print(f"  seam {paths[0]} -> {paths[1]}: no confident overlap "
                      f"(best {overlap} {axis_name}, score {score:.3f} < {match_thresh}); "
                      f"joining without trim", file=sys.stderr)
        result = concat([result, trimmed])

    matched = sum(1 for _, _, u in seams if u)
    msg = (f"overlap-stitch: {matched}/{len(seams)} seam(s) trimmed, "
           f"{total_removed} {axis_name} of overlap removed")
    return result, msg


_STITCHER_MODES = {
    'panorama': getattr(cv2, 'Stitcher_PANORAMA', 0),
    'scans':    getattr(cv2, 'Stitcher_SCANS',    1),
}

_FEATURE_FINDERS = ('orb', 'sift', 'akaze', 'brisk')


def _make_features_finder(name):
    """Create a cv2 Feature2D detector for the given name, or None on failure."""
    creators = {
        'orb':   getattr(cv2, 'ORB_create',   None),
        'sift':  getattr(cv2, 'SIFT_create',  None),
        'akaze': getattr(cv2, 'AKAZE_create', None),
        'brisk': getattr(cv2, 'BRISK_create', None),
    }
    create = creators.get(name)
    if create is None:
        return None
    try:
        return create()
    except cv2.error:
        return None


def _run_cv_stitcher(images, mode_name, verbose=False, *,
                     conf_thresh=None, reg_resol=None, features=None,
                     wave_correction=True):
    """Run cv2.Stitcher in the given mode. Returns (result_or_None, status_msg)."""
    mode = _STITCHER_MODES[mode_name]
    arrs = [img for _, img in images]
    stitcher = cv2.Stitcher_create(mode)

    applied = []
    if conf_thresh is not None:
        try:
            stitcher.setPanoConfidenceThresh(conf_thresh)
            applied.append(f"conf-thresh={conf_thresh}")
        except cv2.error as err:
            print(f"  WARNING: setPanoConfidenceThresh failed: {err}", file=sys.stderr)
    if reg_resol is not None:
        try:
            stitcher.setRegistrationResol(reg_resol)
            applied.append(f"reg-resol={reg_resol}")
        except cv2.error as err:
            print(f"  WARNING: setRegistrationResol failed: {err}", file=sys.stderr)
    if features is not None:
        finder = _make_features_finder(features)
        if finder is None:
            print(f"  WARNING: features detector '{features}' not available in this cv2 build",
                  file=sys.stderr)
        else:
            try:
                stitcher.setFeaturesFinder(finder)
                applied.append(f"features={features}")
            except (cv2.error, AttributeError) as err:
                print(f"  WARNING: setFeaturesFinder({features}) failed: {err}", file=sys.stderr)
    if not wave_correction:
        try:
            stitcher.setWaveCorrection(False)
            applied.append("wave-correction=off")
        except cv2.error as err:
            print(f"  WARNING: setWaveCorrection failed: {err}", file=sys.stderr)

    if verbose:
        sizes = ', '.join(f"{a.shape[1]}x{a.shape[0]}" for a in arrs)
        opts  = ('  options: ' + ', '.join(applied)) if applied else '  options: (defaults)'
        print(f"  cv2.Stitcher mode={mode_name} (cv2 code {mode}); "
              f"feeding {len(arrs)} image(s): {sizes}", file=sys.stderr)
        print(opts, file=sys.stderr)

    status, result = stitcher.stitch(arrs)

    if verbose:
        if status == cv2.Stitcher_OK and result is not None:
            print(f"  cv2.Stitcher returned OK, result {result.shape[1]}x{result.shape[0]}",
                  file=sys.stderr)
            # Show which input indices cv2 actually merged
            try:
                comp = list(stitcher.component())
            except (cv2.error, AttributeError):
                comp = None
            if comp is not None:
                kept = sorted(comp)
                dropped = [i for i in range(len(arrs)) if i not in kept]
                print(f"  matched inputs: {kept}  (dropped: {dropped or 'none'})",
                      file=sys.stderr)
                if dropped:
                    print(f"  WARNING: cv2.Stitcher dropped {len(dropped)} of {len(arrs)} "
                          f"image(s). Try lowering --conf-thresh (e.g. 0.3), raising "
                          f"--reg-resol (e.g. 1.5 or -1 for full res), or switching "
                          f"--features (e.g. sift).", file=sys.stderr)
            # No-op warning: result shape matches a single input
            for path, a in images:
                if result.shape == a.shape:
                    print(f"  WARNING: result shape matches input '{path}' — "
                          f"cv2 may not have aligned any other image. Try a different "
                          f"--stitcher-mode, --features, or --conf-thresh.",
                          file=sys.stderr)
                    break
        else:
            msg = _STATUS_MESSAGES.get(status, f"unknown status {status}")
            print(f"  cv2.Stitcher returned status={status} ({msg})", file=sys.stderr)

    if status == cv2.Stitcher_OK:
        return result, "OK"
    msg = _STATUS_MESSAGES.get(status, f"unknown status {status}")
    return None, f"stitcher error: {msg} (code {status})"


def stitch_images(images, orientation, verbose=False, stitcher_mode='scans',
                  stitcher_opts=None, method='overlap', match_band=100,
                  match_thresh=0.8):
    """
    Stitch a list of (path, image) tuples into one composite image.

    orientation:
      'auto'       -> use cv2.Stitcher in the given stitcher_mode
      'horizontal' -> join left-to-right (see `method`)
      'vertical'   -> join top-to-bottom (see `method`)

    method (applies to 'horizontal' / 'vertical' only):
      'overlap'   -> detect & remove duplicated overlap via template match,
                     then concatenate (best for scroll screenshots/scans)
      'feature'   -> feature-based cv2.Stitcher in `stitcher_mode`

    stitcher_mode (used by 'auto' and method='feature'):
      'panorama'  -> cv2.Stitcher_PANORAMA  (overlapping camera-style mosaic)
      'scans'     -> cv2.Stitcher_SCANS     (flat translation-only scans)

    Returns (result_image_or_None, message).
    """
    if not images:
        return None, "no images to stitch"
    if len(images) == 1:
        return images[0][1], "single image (no stitching needed)"

    # horizontal/vertical with the overlap method: sliding template-match join
    if orientation in ('horizontal', 'vertical') and method == 'overlap':
        if verbose:
            print(f"Overlap-stitching {len(images)} images ({orientation}, "
                  f"band={match_band}, thresh={match_thresh})...", file=sys.stderr)
        try:
            return stitch_by_overlap(images, orientation, match_band=match_band,
                                     match_thresh=match_thresh, verbose=verbose)
        except cv2.error as err:
            return None, f"overlap-stitch failed: {err}"

    # auto, or method='feature': feature-based stitching
    if verbose:
        print(f"Stitching {len(images)} images (feature-based, mode={stitcher_mode})...",
              file=sys.stderr)
    opts = stitcher_opts or {}
    result, msg = _run_cv_stitcher(images, stitcher_mode, verbose=verbose, **opts)
    if result is not None:
        return result, f"OK (cv2.Stitcher {stitcher_mode})"
    # Auto-fallback: try the other mode and report both outcomes
    alt = 'scans' if stitcher_mode == 'panorama' else 'panorama'
    if verbose:
        print(f"  primary mode '{stitcher_mode}' failed ({msg}); "
              f"trying fallback mode '{alt}'...", file=sys.stderr)
    result2, msg2 = _run_cv_stitcher(images, alt, verbose=verbose, **opts)
    if result2 is not None:
        return result2, f"OK (cv2.Stitcher {alt} after {stitcher_mode} failed)"
    return None, f"both modes failed: {stitcher_mode}={msg}; {alt}={msg2}"


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------

def _parse_crop_value(text):
    """Parse a single 'from' or 'to' value as ('pct', float) or ('px', int)."""
    s = text.strip()
    if not s:
        raise argparse.ArgumentTypeError("empty crop value")
    if s.endswith('%'):
        try:
            return ('pct', float(s[:-1]))
        except ValueError:
            raise argparse.ArgumentTypeError(f"invalid percent value: '{text}'")
    try:
        return ('px', int(s))
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid pixel value: '{text}'")


def _crop_spec_type(value):
    """Parse a 'from,to' crop spec into a tuple of two (kind, value) entries."""
    parts = value.split(',')
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"crop spec must be 'from,to' (got '{value}')")
    return (_parse_crop_value(parts[0]), _parse_crop_value(parts[1]))


def _resolve_crop(spec, size, is_to):
    """Resolve a (kind, value) entry against a dimension size in pixels.

    is_to=True allows negative pixel values to mean offset from the far edge.
    """
    kind, v = spec
    if kind == 'pct':
        result = int(round(v * size / 100.0))
    else:
        if v < 0 and is_to:
            result = size + v
        else:
            result = v
    return max(0, min(size, result))


def apply_crops(images, crop_h, crop_w, verbose=False):
    """Apply optional height/width crops to each (path, image) tuple.

    Returns a new list of (path, cropped_image). Images that would be empty
    after cropping are dropped with a warning.
    """
    if not crop_h and not crop_w:
        return images

    out = []
    for path, img in images:
        h, w = img.shape[:2]
        if crop_h:
            y0 = _resolve_crop(crop_h[0], h, is_to=False)
            y1 = _resolve_crop(crop_h[1], h, is_to=True)
        else:
            y0, y1 = 0, h
        if crop_w:
            x0 = _resolve_crop(crop_w[0], w, is_to=False)
            x1 = _resolve_crop(crop_w[1], w, is_to=True)
        else:
            x0, x1 = 0, w

        if y1 <= y0 or x1 <= x0:
            print(f"Warning: crop produced empty region for {path} "
                  f"(y={y0}:{y1}, x={x0}:{x1}); skipping", file=sys.stderr)
            continue

        cropped = img[y0:y1, x0:x1]
        if verbose:
            ch, cw = cropped.shape[:2]
            print(f"  cropped {path}  {w}x{h} -> {cw}x{ch}  "
                  f"(y={y0}:{y1}, x={x0}:{x1})", file=sys.stderr)
        out.append((path, cropped))
    return out


# ---------------------------------------------------------------------------
# Argparse helpers
# ---------------------------------------------------------------------------

_ORIENTATIONS = ('auto', 'horizontal', 'vertical')
_METHODS = ('overlap', 'feature')


def _prefix_match(value, choices, name):
    """Accept any unique case-insensitive prefix of a choice."""
    v = value.strip().lower()
    if not v:
        raise argparse.ArgumentTypeError(f"{name} cannot be empty")
    matches = [c for c in choices if c.startswith(v)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise argparse.ArgumentTypeError(
            f"invalid {name} '{value}' (choose from {', '.join(choices)})")
    raise argparse.ArgumentTypeError(
        f"ambiguous {name} '{value}' matches: {', '.join(matches)}")


def _orientation_type(value):
    return _prefix_match(value, _ORIENTATIONS, 'orientation')


def _method_type(value):
    return _prefix_match(value, _METHODS, 'method')


def _stitcher_mode_type(value):
    return _prefix_match(value, tuple(_STITCHER_MODES.keys()), 'stitcher-mode')


def _features_type(value):
    return _prefix_match(value, _FEATURE_FINDERS, 'features')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"stitch-images {VERSION}\nStitch multiple images into a single composite image.",
        epilog="""Examples:
  # Stitch a few images with auto orientation (feature-based, SCANS mode):
  stitch-images.py --input image1.png -i image2.png -i image3.png -o final.png

  # Wildcards expand to all matching files (sorted alphabetically):
  stitch-images.py -i 'shots/shot*.png' -o combined.png

  # Mix individual files and wildcards; order is preserved:
  stitch-images.py -i header.png -i 'body*.png' -i footer.png -o page.png

  # Vertical join (top-to-bottom). Default method 'overlap' detects and removes
  # the duplicated overlap between consecutive scroll-shots. Widths are matched.
  stitch-images.py --orientation vertical -i a.png -i b.png -i c.png -o stack.png

  # Horizontal join (left-to-right); heights are matched automatically.
  stitch-images.py --orientation horizontal -i a.png -i b.png -o row.png

  # Tune overlap detection: bigger band = more distinctive; lower thresh if a
  # real overlap is being missed (joins below thresh are stacked untrimmed).
  stitch-images.py --ori vertical --match-band 200 --match-thresh 0.6 \\
                   -v -i 'scroll*.png' -o page.png

  # Use feature-based cv2.Stitcher instead of overlap detection for h/v:
  stitch-images.py --orientation vertical --method feature -i 'frame*' -o m.png

  # Crop each input before stitching (trim 10px borders top/bottom):
  stitch-images.py --crop-height 10,-10 -i 'shot*.png' -o trimmed.png

  # Crop using percentages (keep the middle 80% vertically):
  stitch-images.py --crop-height 10%,90% -i a.png -i b.png -o middle.png

  # Crop both axes (rows 50..300, columns 0..500):
  stitch-images.py --crop-height 50,300 --crop-width 0,500 -i a.png -i b.png -o box.png

  # Verbose progress and file info:
  stitch-images.py -v -i 'shot*.png' -o out.png

  # Two-pass edge dedupe (default ON): detect identical top/bottom (vertical) or
  # left/right (horizontal) edge blocks and emit one copy in the result.
  stitch-images.py --orientation vertical -v -i 'shot*.png' -o stack.png
  stitch-images.py --no-dedupe-edges --orientation vertical -i 'shot*.png' -o stack.png

  # The feature-based path uses cv2.Stitcher. Default mode is SCANS (flat,
  # translation-only documents/screenshots). Use PANORAMA for overlapping
  # camera-style photo mosaics that need rotation/perspective alignment.
  stitch-images.py --orientation auto -i 'net-conn*' -o mosaic.png
  stitch-images.py --orientation auto --stitcher-mode scans -i 'page*' -o doc.png

  # Auto-stitch troubleshooting (when images fail to merge despite overlap):
  # 1) Lower the confidence threshold (cv2 default 1.0 is often too strict):
  stitch-images.py --ori auto --conf-thresh 0.3 -v -i 'frame*' -o m.png
  # 2) Use full-resolution registration (helps with large images):
  stitch-images.py --ori auto --reg-resol -1 -v -i 'frame*' -o m.png
  # 3) Switch feature detector (sift finds more matches than orb):
  stitch-images.py --ori auto --features sift -v -i 'frame*' -o m.png
  # 4) Combine all of the above and disable wave correction:
  stitch-images.py --ori auto --conf-thresh 0.3 --reg-resol -1 --features sift \\
                   --no-wave-correction -v -i 'frame*' -o m.png

Notes:
  --input / -i can be supplied multiple times and each value may be a literal
  path or a shell wildcard (*, ?, [...]). Wildcards are expanded by this tool,
  so quoting them in the shell ('shot*.png') is recommended.

  Orientation modes:
    auto        Use OpenCV's feature-based stitcher (cv2.Stitcher). Best for
                photographs that overlap and need rotation/perspective alignment.
    horizontal  Join left-to-right; heights are scaled to match.
    vertical    Join top-to-bottom; widths are scaled to match.

  Join method for horizontal/vertical (--method):
    overlap     (default) Slide a band from the leading edge of each image across
                the previous one (cv2.matchTemplate), drop the duplicated overlap,
                then concatenate. Ideal for scroll screenshots and document scans.
    feature     Use cv2.Stitcher (--stitcher-mode) instead.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '--input', '-i', action='append', default=[], metavar='PATH_OR_GLOB',
        help='Input image file or wildcard pattern (repeatable)',
    )
    parser.add_argument(
        '--output', '-o', metavar='PATH', default='stitched_output.png',
        help='Output image path (default: stitched_output.png)',
    )
    parser.add_argument(
        '--crop-height', type=_crop_spec_type, default=None, metavar='FROM,TO',
        help='Crop each input vertically to rows FROM..TO (e.g. 10,110  10,-10  10%%,90%%)',
    )
    parser.add_argument(
        '--crop-width', type=_crop_spec_type, default=None, metavar='FROM,TO',
        help='Crop each input horizontally to cols FROM..TO (same syntax as --crop-height)',
    )
    parser.add_argument(
        '--dedupe-edges', action=argparse.BooleanOptionalAction, default=True,
        help='Two-pass mode: detect identical edge blocks (top/bottom for vertical, '
             'left/right for horizontal) and emit only one copy in the output '
             '(default: enabled; use --no-dedupe-edges to disable)',
    )
    parser.add_argument(
        '--orientation', type=_orientation_type, default='auto',
        metavar='{auto,horizontal,vertical}',
        help='Stitching orientation: auto (feature-based), horizontal, or vertical '
             '(accepts unique prefixes: a, h, v, hor, vert, ...)',
    )
    parser.add_argument(
        '--stitcher-mode', type=_stitcher_mode_type, default='scans',
        metavar='{panorama,scans}',
        help='cv2.Stitcher mode used by the feature-based path: '
             'scans (flat translation-only documents/screenshots; default) '
             'or panorama (overlapping camera-style mosaic with rotation/perspective). '
             'Prefixes accepted (s, scan, p, pano). '
             'If the chosen mode fails, the other is tried as a fallback.',
    )
    parser.add_argument(
        '--conf-thresh', type=float, default=None, metavar='FLOAT',
        help='cv2.Stitcher panorama confidence threshold (cv2 default 1.0). '
             'Lower values (e.g. 0.5, 0.3) allow weaker feature matches — try this '
             'first when images fail to merge despite obvious overlap.',
    )
    parser.add_argument(
        '--reg-resol', type=float, default=None, metavar='MEGAPIXELS',
        help='cv2.Stitcher registration resolution in megapixels (cv2 default 0.6). '
             'Large images get downscaled for feature matching; raise to 1.0 or 1.5, '
             'or pass -1 to use full resolution (slower but finds more features).',
    )
    parser.add_argument(
        '--features', type=_features_type, default=None, metavar='{orb,sift,akaze,brisk}',
        help='Feature detector for cv2.Stitcher (cv2 default: orb). '
             'sift typically finds more matches in textured scenes; akaze is robust '
             'to viewpoint change; brisk is fast. Prefixes accepted (s=sift, a=akaze, ...).',
    )
    parser.add_argument(
        '--no-wave-correction', action='store_true',
        help='Disable cv2.Stitcher wave correction (sometimes helps when only 2-3 '
             'images are being merged and the result is curving unexpectedly).',
    )
    parser.add_argument(
        '--method', type=_method_type, default='overlap', metavar='{overlap,feature}',
        help='How to join images for --orientation horizontal/vertical: '
             'overlap (detect & remove duplicated overlap with a sliding template '
             'match, then concatenate — best for scroll screenshots/scans; default) '
             'or feature (cv2.Stitcher in --stitcher-mode). Prefixes accepted (o, f). '
             'Ignored for --orientation auto (always feature-based).',
    )
    parser.add_argument(
        '--match-band', type=int, default=100, metavar='PIXELS',
        help='Overlap method: height (vertical) or width (horizontal) in pixels of the '
             'leading-edge band slid across the previous image to find the overlap '
             '(default: 100). Larger is more distinctive but must fit within the overlap.',
    )
    parser.add_argument(
        '--match-thresh', type=float, default=0.8, metavar='FLOAT',
        help='Overlap method: minimum normalized-correlation score (0..1) to accept a '
             'detected overlap (default: 0.8). Seams below this are joined without '
             'trimming. Lower if real overlap is being missed; raise to avoid false trims.',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show per-image loading and stitching progress',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    if not args.input:
        parser.error("provide at least one --input / -i (path or wildcard)")

    paths = expand_inputs(args.input, verbose=args.verbose)
    if not paths:
        print("No input images found.", file=sys.stderr)
        sys.exit(1)

    if len(paths) < 2:
        print(f"Warning: only {len(paths)} image provided; output will be a copy.",
              file=sys.stderr)

    images = load_images(paths, verbose=args.verbose)
    if not images:
        print("No readable input images.", file=sys.stderr)
        sys.exit(1)

    images = apply_crops(images, args.crop_height, args.crop_width, verbose=args.verbose)
    if not images:
        print("No images remain after cropping.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        _print_input_summary(images, args.orientation)

    stitcher_opts = {
        'conf_thresh':     args.conf_thresh,
        'reg_resol':       args.reg_resol,
        'features':        args.features,
        'wave_correction': not args.no_wave_correction,
    }
    if args.dedupe_edges:
        result, message = stitch_with_edge_dedupe(
            images, args.orientation, verbose=args.verbose,
            stitcher_mode=args.stitcher_mode, stitcher_opts=stitcher_opts,
            method=args.method, match_band=args.match_band, match_thresh=args.match_thresh)
    else:
        result, message = stitch_images(
            images, args.orientation, verbose=args.verbose,
            stitcher_mode=args.stitcher_mode, stitcher_opts=stitcher_opts,
            method=args.method, match_band=args.match_band, match_thresh=args.match_thresh)
    if result is None:
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(2)

    if not cv2.imwrite(args.output, result):
        print(f"Error: failed to write output: {args.output}", file=sys.stderr)
        sys.exit(3)

    out_h, out_w = result.shape[:2]
    if args.verbose:
        _print_output_summary(images, result, args.orientation)
    print(f"Stitched {len(images)} image(s) -> {args.output}  ({out_w}x{out_h})  [{message}]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
