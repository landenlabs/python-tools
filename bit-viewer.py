#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Qt GUI hex viewer for binary data with configurable bit-packing decode.

Left pane is a classic hex dump (offset + 8/16 hex bytes + optional ASCII).
Right pane shows the same bytes decoded as configurable bit-packed samples
(continuous N-bit, grouped/padded, or native 8-bit), as hex or decimal.

Rows are aligned to whole-sample boundaries, so every decoded value sits
fully inside its row and hex<->decoded selection stays exactly in sync.
"""

import sys
import os
import math
import argparse
import traceback

_QT_EXEC = "exec_"   # overridden to "exec" for PyQt6 below

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSpinBox, QComboBox, QCheckBox, QFileDialog,
        QAbstractScrollArea, QSizePolicy, QFrame, QDialog, QLineEdit,
        QScrollArea, QFormLayout, QToolTip,
    )
    from PyQt5.QtCore import Qt, pyqtSignal, QRect
    from PyQt5.QtGui import (
        QFont, QFontMetrics, QPainter, QColor, QPen, QImage, QPixmap,
        QIntValidator, QCursor,
    )
except ImportError:
    try:
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QPushButton, QSpinBox, QComboBox, QCheckBox, QFileDialog,
            QAbstractScrollArea, QSizePolicy, QFrame, QDialog, QLineEdit,
            QScrollArea, QFormLayout, QToolTip,
        )
        from PyQt6.QtCore import Qt, pyqtSignal, QRect
        from PyQt6.QtGui import (
            QFont, QFontMetrics, QPainter, QColor, QPen, QImage, QPixmap,
            QIntValidator, QCursor,
        )
        # PyQt6 renamed enums — wire compat aliases onto the Qt/class objects
        Qt.AlignLeft            = Qt.AlignmentFlag.AlignLeft
        Qt.AlignRight           = Qt.AlignmentFlag.AlignRight
        Qt.AlignVCenter         = Qt.AlignmentFlag.AlignVCenter
        Qt.AlignCenter          = Qt.AlignmentFlag.AlignCenter
        Qt.LeftButton           = Qt.MouseButton.LeftButton
        Qt.ScrollBarAsNeeded    = Qt.ScrollBarPolicy.ScrollBarAsNeeded
        Qt.ScrollBarAlwaysOff   = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        Qt.KeepAspectRatio      = Qt.AspectRatioMode.KeepAspectRatio
        Qt.FastTransformation   = Qt.TransformationMode.FastTransformation
        QSizePolicy.Expanding   = QSizePolicy.Policy.Expanding
        QSizePolicy.Fixed       = QSizePolicy.Policy.Fixed
        QFrame.VLine            = QFrame.Shape.VLine
        QImage.Format_Indexed8  = QImage.Format.Format_Indexed8
        QImage.Format_RGBA8888  = QImage.Format.Format_RGBA8888
        _QT_EXEC = "exec"
    except ImportError:
        print("Error: PyQt5 or PyQt6 required.  Install: pip install PyQt5", file=sys.stderr)
        sys.exit(1)


VERSION = "v1.0 (Jun-2026)"

# Colors (theme-independent so it looks the same regardless of system palette)
C_BG        = QColor(253, 253, 250)
C_OFFSET    = QColor(150, 150, 150)
C_HEX       = QColor(30, 30, 30)
C_HEX_ALT   = QColor(90, 90, 160)   # every other byte column, for readability
C_ASCII     = QColor(40, 110, 40)
C_DECODE    = QColor(150, 40, 40)
C_SEL_BYTE  = QColor(255, 236, 150)
C_SEL_SAMP  = QColor(190, 225, 255)
C_GRID      = QColor(225, 225, 225)
C_HEADER    = QColor(245, 245, 240)


# ---------------------------------------------------------------------------
# Pure bit-unpacking core (no Qt) — independently testable
# ---------------------------------------------------------------------------

class BitUnpacker:
    """Decodes a byte buffer into fixed-width bit-packed samples.

    mode:
      'native'      — one 8-bit sample per byte
      'continuous'  — samples packed back-to-back across byte boundaries
      'grouped'     — `samples_per_group` samples in `group_bytes` bytes,
                      any leftover bits in the group are padding/filler
    bit_order: 'msb' (first sample uses the most-significant bits) or 'lsb'
    signed: interpret each sample as two's-complement
    """

    def __init__(self, mode='continuous', bit_width=9, group_bytes=3,
                 samples_per_group=2, bit_order='msb', signed=False):
        self.mode = mode
        self.bit_width = max(1, min(64, int(bit_width)))
        self.group_bytes = max(1, int(group_bytes))
        self.samples_per_group = max(1, int(samples_per_group))
        self.bit_order = bit_order
        self.signed = bool(signed)
        if mode == 'native':
            self.bit_width = 8

    # -- row geometry ------------------------------------------------------

    def base_block(self):
        """Smallest (bytes, samples) unit that aligns on a byte boundary."""
        W = self.bit_width
        if self.mode == 'native':
            return 1, 1
        if self.mode == 'grouped':
            return self.group_bytes, self.samples_per_group
        # continuous: lcm(W, 8) bits is the first byte-aligned block
        block_bits = W * 8 // math.gcd(W, 8)
        return block_bits // 8, block_bits // W

    def row_layout(self, target_bytes):
        """Pick (bytes_per_row, samples_per_row) near target, snapped to a
        whole number of base blocks so rows never split a sample."""
        bb, bs = self.base_block()
        blocks = max(1, round(target_bytes / bb))
        return bb * blocks, bs * blocks

    # -- decode ------------------------------------------------------------

    def _finish(self, val):
        if self.signed and val >= (1 << (self.bit_width - 1)):
            val -= (1 << self.bit_width)
        return val

    def _read_block(self, chunk, out, base_bit):
        """Decode one base block (bytes object) -> appends (bit_offset, value).
        bit_offset is relative to the start of the chunk's owning row."""
        W = self.bit_width
        mask = (1 << W) - 1
        nbits = len(chunk) * 8
        nsamp = nbits // W if self.mode == 'continuous' else self.samples_per_group
        nsamp = min(nsamp, nbits // W)
        if self.bit_order == 'msb':
            acc = int.from_bytes(chunk, 'big')
            for j in range(nsamp):
                shift = nbits - (j + 1) * W
                out.append((base_bit + j * W, self._finish((acc >> shift) & mask)))
        else:  # lsb-first: stream bit 0 is the LSB of byte 0
            acc = int.from_bytes(chunk, 'little')
            for j in range(nsamp):
                out.append((base_bit + j * W, self._finish((acc >> (j * W)) & mask)))

    def decode_row(self, data, byte_off, row_bytes):
        """Decode the row starting at byte_off. Returns list of
        (bit_offset_in_row, value). Handles a short final row."""
        chunk = data[byte_off:byte_off + row_bytes]
        out = []
        if self.mode == 'native':
            for i, b in enumerate(chunk):
                out.append((i * 8, self._finish(b) if self.signed else b))
            return out
        if self.mode == 'continuous':
            self._read_block(chunk, out, 0)
            return out
        # grouped: independent base blocks, padding bits ignored
        gb = self.group_bytes
        for g in range(0, len(chunk), gb):
            self._read_block(chunk[g:g + gb], out, g * 8)
        return out

    def _block_values(self, chunk):
        """Decode one base block (bytes) into a flat list of values."""
        W = self.bit_width
        mask = (1 << W) - 1
        if self.mode == 'native':
            return [self._finish(b) if self.signed else b for b in chunk]
        nbits = len(chunk) * 8
        nsamp = (nbits // W if self.mode == 'continuous'
                 else min(self.samples_per_group, nbits // W))
        vals = []
        if self.bit_order == 'msb':
            acc = int.from_bytes(chunk, 'big')
            for j in range(nsamp):
                shift = nbits - (j + 1) * W
                vals.append(self._finish((acc >> shift) & mask))
        else:
            acc = int.from_bytes(chunk, 'little')
            for j in range(nsamp):
                vals.append(self._finish((acc >> (j * W)) & mask))
        return vals

    def decode_samples(self, data, byte_off, count, skip=0):
        """Decode `count` samples starting at the base-block boundary at/just
        below byte_off. Returns (values, actual_start_byte, end_byte) where
        end_byte is the byte just past the consumed data (where the next image
        should begin).

        `skip` (>= 0) drops that many samples between each kept value: take a
        value, step one, add `skip` to reach the next kept value (stride =
        skip + 1). skip=0 yields consecutive samples."""
        step = max(1, int(skip) + 1)
        raw = count * step
        bb, _ = self.base_block()
        start = max(0, (byte_off // bb) * bb)
        if self.mode == 'native':
            seg = data[start:start + raw]
            vals = [self._finish(b) if self.signed else b for b in seg]
            end = min(start + len(seg), len(data))
            return vals[::step][:count], start, end
        out = []
        pos = start
        while len(out) < raw and pos < len(data):
            out.extend(self._block_values(data[pos:pos + bb]))
            pos += bb
        return out[:raw][::step][:count], start, min(pos, len(data))

    def sample_span(self, count, skip=0):
        """Bytes a full image of `count` samples (with `skip`) consumes,
        independent of file length. Used to count/index whole chunks."""
        step = max(1, int(skip) + 1)
        raw = count * step
        bb, bs = self.base_block()
        if self.mode == 'native':
            return raw
        blocks = (raw + bs - 1) // bs   # whole base blocks needed
        return blocks * bb

    def sample_byte_offset(self, start, raw_index):
        """Byte offset where raw sample `raw_index` begins, counting from the
        block-aligned byte `start`."""
        W = self.bit_width
        if self.mode == 'native':
            return start + raw_index
        if self.mode == 'grouped':
            g, within = divmod(raw_index, self.samples_per_group)
            return start + g * self.group_bytes + (within * W) // 8
        return start + (raw_index * W) // 8   # continuous

    # -- formatting --------------------------------------------------------

    def field_chars(self, as_hex):
        if as_hex:
            return max(2, (self.bit_width + 3) // 4)
        lo = -(1 << (self.bit_width - 1)) if self.signed else 0
        hi = (1 << (self.bit_width - 1)) - 1 if self.signed else (1 << self.bit_width) - 1
        return max(len(str(lo)), len(str(hi)))

    def format_value(self, val, as_hex):
        w = self.field_chars(as_hex)
        if as_hex:
            return ("%0*X" % (w, val & ((1 << self.bit_width) - 1)))
        return ("%*d" % (w, val))


# ---------------------------------------------------------------------------
# Virtualized painted hex/decode view
# ---------------------------------------------------------------------------

class HexView(QAbstractScrollArea):
    """Paints only the visible rows, so multi-MB files scroll smoothly."""

    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = b""
        self.unpacker = BitUnpacker()
        self.bytes_per_row = 16
        self.samples_per_row = 16
        self.target_bytes = 16
        self.show_ascii = True
        self.hex_decode = False          # decoded pane as hex (True) or decimal
        self.sel_byte = None             # global byte index, or None
        self.sel_samples = set()         # global sample indices to highlight
        self.sel_bytes = set()           # global byte indices to highlight

        f = QFont("Menlo")
        f.setStyleHint(QFont.StyleHint.TypeWriter if _QT_EXEC == "exec"
                       else QFont.TypeWriter)
        f.setPointSize(12)
        self.setFont(f)
        self.viewport().setBackgroundRole(self.viewport().backgroundRole())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self._recompute()

    # -- public config -----------------------------------------------------

    def set_data(self, data):
        self.data = data or b""
        self.sel_byte = None
        self.sel_bytes.clear()
        self.sel_samples.clear()
        self._recompute()
        self.selectionChanged.emit()

    def set_unpacker(self, unpacker, target_bytes=None):
        self.unpacker = unpacker
        if target_bytes is not None:
            self.target_bytes = target_bytes
        self._recompute()

    def set_show_ascii(self, on):
        self.show_ascii = bool(on)
        self._recompute()

    def set_hex_decode(self, on):
        self.hex_decode = bool(on)
        self._recompute()

    # -- geometry ----------------------------------------------------------

    def _recompute(self):
        fm = QFontMetrics(self.font())
        self.ch = fm.horizontalAdvance("0")
        self.line_h = fm.height() + 4
        self.ascent = fm.ascent()
        self.bytes_per_row, self.samples_per_row = \
            self.unpacker.row_layout(self.target_bytes)
        bpr = self.bytes_per_row

        # x positions in pixels (relative to content origin)
        self.x_off = 6
        self.off_chars = max(6, len("%X" % max(1, len(self.data))))
        self.x_hex = self.x_off + (self.off_chars + 2) * self.ch
        # hex: each byte = "XX " (3 chars) + extra space every 8 bytes
        self.hex_w = (bpr * 3 + (bpr - 1) // 8) * self.ch
        self.x_ascii = self.x_hex + self.hex_w + 2 * self.ch
        if self.show_ascii:
            self.ascii_w = bpr * self.ch
            self.x_dec = self.x_ascii + self.ascii_w + 2 * self.ch
        else:
            self.ascii_w = 0
            self.x_dec = self.x_hex + self.hex_w + 2 * self.ch
        self.fc = self.unpacker.field_chars(self.hex_decode)
        self.dec_field_w = (self.fc + 1) * self.ch
        self.dec_w = self.samples_per_row * self.dec_field_w
        self.content_w = self.x_dec + self.dec_w + 2 * self.ch

        self.total_rows = (len(self.data) + bpr - 1) // bpr if bpr else 0
        self._update_scrollbars()
        self.viewport().update()

    def _byte_x(self, i):
        return self.x_hex + (i * 3 + i // 8) * self.ch

    def _visible_rows(self):
        return max(1, self.viewport().height() // self.line_h)

    def _update_scrollbars(self):
        vis = self._visible_rows()
        vbar = self.verticalScrollBar()
        vbar.setRange(0, max(0, self.total_rows - vis))
        vbar.setPageStep(vis)
        vbar.setSingleStep(1)
        hbar = self.horizontalScrollBar()
        hbar.setRange(0, max(0, self.content_w - self.viewport().width()))
        hbar.setPageStep(self.viewport().width())
        hbar.setSingleStep(self.ch)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_scrollbars()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), C_BG)
        p.setFont(self.font())
        xoff = -self.horizontalScrollBar().value()
        top = self.verticalScrollBar().value()
        vis = self._visible_rows() + 1
        as_hex = self.hex_decode
        up = self.unpacker
        bpr = self.bytes_per_row

        for vr in range(vis):
            row = top + vr
            if row >= self.total_rows:
                break
            y = vr * self.line_h
            base = row * bpr
            chunk = self.data[base:base + bpr]

            # offset
            p.setPen(C_OFFSET)
            p.drawText(xoff + self.x_off, y + self.ascent,
                       "%0*X:" % (self.off_chars, base))

            # selection backgrounds for bytes
            for i in range(len(chunk)):
                gi = base + i
                if gi in self.sel_bytes:
                    bx = xoff + self._byte_x(i)
                    p.fillRect(QRect(bx - self.ch // 4, y,
                                     int(2.5 * self.ch), self.line_h), C_SEL_BYTE)

            # hex bytes + ascii
            for i, b in enumerate(chunk):
                bx = xoff + self._byte_x(i)
                p.setPen(C_HEX if (i % 2 == 0) else C_HEX_ALT)
                p.drawText(bx, y + self.ascent, "%02X" % b)
                if self.show_ascii:
                    p.setPen(C_ASCII)
                    ch = chr(b) if 32 <= b < 127 else "."
                    p.drawText(xoff + self.x_ascii + i * self.ch, y + self.ascent, ch)

            # decoded samples
            samples = up.decode_row(self.data, base, bpr)
            sample_base = row * self.samples_per_row
            for j, (bit_off, val) in enumerate(samples):
                gj = sample_base + j
                dx = xoff + self.x_dec + j * self.dec_field_w
                if gj in self.sel_samples:
                    p.fillRect(QRect(dx - self.ch // 4, y,
                                     self.dec_field_w, self.line_h), C_SEL_SAMP)
                p.setPen(C_DECODE)
                p.drawText(dx, y + self.ascent, up.format_value(val, as_hex))

        # column separators
        p.setPen(QPen(C_GRID))
        for x in (self.x_hex - self.ch, self.x_dec - self.ch):
            p.drawLine(xoff + x, 0, xoff + x, self.viewport().height())
        if self.show_ascii:
            p.drawLine(xoff + self.x_ascii - self.ch, 0,
                       xoff + self.x_ascii - self.ch, self.viewport().height())
        p.end()

    # -- hit testing / selection ------------------------------------------

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position() if hasattr(ev, "position") else ev.pos()
        x = int(pos.x()) + self.horizontalScrollBar().value()
        y = int(pos.y())
        row = self.verticalScrollBar().value() + y // self.line_h
        if row < 0 or row >= self.total_rows:
            return
        base = row * self.bytes_per_row

        # which region?
        if x >= self.x_dec:
            self._select_sample_at(row, x)
        elif self.show_ascii and self.x_ascii <= x < self.x_dec:
            i = (x - self.x_ascii) // self.ch
            self._select_byte(base + i)
        elif x >= self.x_hex:
            i = self._hex_col_at(x)
            if i is not None:
                self._select_byte(base + i)
        self.viewport().update()
        self.selectionChanged.emit()

    def _hex_col_at(self, x):
        for i in range(self.bytes_per_row):
            bx = self._byte_x(i)
            if bx - self.ch // 2 <= x < bx + int(2.5 * self.ch):
                return i
        return None

    def _select_sample_at(self, row, x):
        j = (x - self.x_dec) // self.dec_field_w
        if j < 0 or j >= self.samples_per_row:
            return
        gj = row * self.samples_per_row + j
        samples = self.unpacker.decode_row(
            self.data, row * self.bytes_per_row, self.bytes_per_row)
        if j >= len(samples):
            return
        bit_off, _ = samples[j]
        W = self.unpacker.bit_width
        b0 = (row * self.bytes_per_row) + bit_off // 8
        b1 = (row * self.bytes_per_row) + (bit_off + W - 1) // 8
        self.sel_byte = b0
        self.sel_samples = {gj}
        self.sel_bytes = set(range(b0, b1 + 1))

    def _select_byte(self, gi):
        if gi < 0 or gi >= len(self.data):
            return
        self.sel_byte = gi
        self.sel_bytes = {gi}
        # find the sample(s) in this byte's row that overlap this byte
        row = gi // self.bytes_per_row
        base = row * self.bytes_per_row
        local_byte = gi - base
        W = self.unpacker.bit_width
        samples = self.unpacker.decode_row(self.data, base, self.bytes_per_row)
        self.sel_samples = set()
        for j, (bit_off, _) in enumerate(samples):
            sb0 = bit_off // 8
            sb1 = (bit_off + W - 1) // 8
            if sb0 <= local_byte <= sb1:
                self.sel_samples.add(row * self.samples_per_row + j)

    def selection_info(self):
        """Human-readable status string for the current selection."""
        if self.sel_byte is None:
            return ""
        gi = self.sel_byte
        parts = ["byte 0x%X (%d)" % (gi, gi), "val 0x%02X" % self.data[gi]]
        if self.sel_samples:
            j = min(self.sel_samples)
            row = j // self.samples_per_row
            local = j - row * self.samples_per_row
            samples = self.unpacker.decode_row(
                self.data, row * self.bytes_per_row, self.bytes_per_row)
            if local < len(samples):
                _, v = samples[local]
                parts.append("sample #%d = %d (0x%X)" % (j, v, v & ((1 << self.unpacker.bit_width) - 1)))
        return "   ".join(parts)


# ---------------------------------------------------------------------------
# Rainbow palette + image dialog
# ---------------------------------------------------------------------------

def rainbow_palette(n=256):
    """Return n (R, G, B) tuples spanning a 7-stop rainbow (no numpy needed)."""
    stops_t = [0.0, 1/6, 2/6, 3/6, 4/6, 5/6, 1.0]
    stops_c = [
        [148, 0, 211], [75, 0, 130], [0, 0, 255],
        [0, 255, 0], [255, 255, 0], [255, 127, 0], [255, 0, 0],
    ]
    out = []
    for i in range(n):
        t = i / max(n - 1, 1)
        for j in range(len(stops_t) - 1):
            if stops_t[j] <= t <= stops_t[j + 1]:
                f = (t - stops_t[j]) / (stops_t[j + 1] - stops_t[j])
                lo, hi = stops_c[j], stops_c[j + 1]
                out.append((int(lo[0] + f * (hi[0] - lo[0])),
                            int(lo[1] + f * (hi[1] - lo[1])),
                            int(lo[2] + f * (hi[2] - lo[2]))))
                break
    return out


class ImageCanvas(QWidget):
    """Displays a QImage scaled to fill the widget while keeping aspect ratio,
    and reports the image pixel under the mouse (click and hover)."""

    hovered = pyqtSignal(int, int)   # image x, y  (-1, -1 when off the image)
    clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img = None
        self._src_w = 0            # sample-grid dimensions for coord mapping
        self._src_h = 0
        self._mappable = False     # data image maps to samples; histogram not
        self._disp = QRect()       # rect the image is painted into
        self.setMouseTracking(True)
        self.setMinimumSize(80, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_image(self, img, src_w=0, src_h=0, mappable=False):
        self._img = img
        self._src_w = src_w
        self._src_h = src_h
        self._mappable = bool(mappable) and src_w > 0 and src_h > 0
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)
        if self._img is not None and not self._img.isNull():
            iw, ih = self._img.width(), self._img.height()
            if iw and ih:
                scale = min(self.width() / iw, self.height() / ih)
                dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
                dx, dy = (self.width() - dw) // 2, (self.height() - dh) // 2
                self._disp = QRect(dx, dy, dw, dh)
                p.drawImage(self._disp, self._img)
        p.end()

    def _pt(self, ev):
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        return pos

    def _img_xy(self, pos):
        if (not self._mappable or self._disp.isEmpty()
                or not self._disp.contains(pos)):
            return -1, -1
        fx = (pos.x() - self._disp.x()) / self._disp.width()
        fy = (pos.y() - self._disp.y()) / self._disp.height()
        x = min(max(0, int(fx * self._src_w)), self._src_w - 1)
        y = min(max(0, int(fy * self._src_h)), self._src_h - 1)
        return x, y

    def mouseMoveEvent(self, ev):
        x, y = self._img_xy(self._pt(ev))
        self.hovered.emit(x, y)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x, y = self._img_xy(self._pt(ev))
        if x >= 0:
            self.clicked.emit(x, y)


class ImageDialog(QDialog):
    """Render a W x H block of decoded samples as an 8-bit indexed PNG image."""

    def __init__(self, view, parent=None, owner=None):
        super().__init__(parent)
        self.view = view
        self.owner = owner            # MainWindow: holds remembered settings
        self.resize(560, 620)
        self._palette = rainbow_palette(256)
        self._buf = None   # keep QImage backing bytes alive
        self._img = None

        # Remembered defaults (persist across dialogs while the program runs)
        s = owner.img_settings if owner is not None else {}
        def_w = int(s.get("width", 64))
        def_h = int(s.get("height", 64))
        def_skip = int(s.get("skip", 0))
        def_auto = bool(s.get("autoscale", False))
        def_single = bool(s.get("single", False))

        lay = QVBoxLayout(self)
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        iv = QIntValidator(1, 100000, self)
        ov = QIntValidator(0, 1 << 30, self)

        def field(target, label, validator, value):
            target.addWidget(QLabel(label))
            e = QLineEdit(str(value))
            e.setValidator(validator)
            e.setFixedWidth(80)
            target.addWidget(e)
            return e

        # Row 1: geometry / source
        self.w_edit = field(row1, "Width:", iv, def_w)
        self.h_edit = field(row1, "Height:", iv, def_h)
        off = view.sel_byte if view.sel_byte is not None else 0
        self.off_edit = field(row1, "Offset:", ov, off)
        self.skip_edit = field(row1, "Skip:", ov, def_skip)
        self.skip_edit.setToolTip(
            "Samples skipped between kept values (stride = skip + 1). 0 = consecutive.")
        row1.addStretch(1)
        lay.addLayout(row1)

        # Row 2: options / actions
        self.autoscale_cb = QCheckBox("Auto-scale")
        self.autoscale_cb.setToolTip(
            "Scale colors to the window's min/max instead of the full bit range")
        self.autoscale_cb.setChecked(def_auto)
        self.autoscale_cb.stateChanged.connect(self.draw)
        row2.addWidget(self.autoscale_cb)

        self.single_cb = QCheckBox("Single Viewer")
        self.single_cb.setToolTip(
            "Reuse this one image window: pressing Image again re-points it at "
            "the current selection and redraws instead of opening a new window.")
        self.single_cb.setChecked(def_single)
        self.single_cb.stateChanged.connect(self._on_single_toggled)
        row2.addWidget(self.single_cb)

        draw = QPushButton("Draw")
        draw.clicked.connect(self.draw)
        row2.addWidget(draw)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setToolTip(
            "Previous: step the offset back by one image and draw the block "
            "just before the current one.")
        self.prev_btn.clicked.connect(self.draw_prev)
        row2.addWidget(self.prev_btn)

        self.next_btn = QPushButton("▶")
        self.next_btn.setToolTip(
            "Next: advance the offset to where the current image ended and "
            "draw the following block.")
        self.next_btn.clicked.connect(self.draw_next)
        row2.addWidget(self.next_btn)

        self.pos_lbl = QLabel("0 of 0")
        self.pos_lbl.setToolTip(
            "Current image chunk position of the total whole chunks in the "
            "file (partial trailing chunk excluded).")
        row2.addWidget(self.pos_lbl)
        row2.addStretch(1)
        lay.addLayout(row2)

        self._last_start = None   # block-aligned start of the last drawn image
        self._last_end = None     # byte just past the last drawn image

        # Remember changes to width/height/skip while the program runs
        self.w_edit.textChanged.connect(self._save_settings)
        self.h_edit.textChanged.connect(self._save_settings)
        self.skip_edit.textChanged.connect(self._save_settings)

        self.info = QLabel("")
        lay.addWidget(self.info)

        self.canvas = ImageCanvas()
        self.canvas.hovered.connect(self._on_hover)
        self.canvas.clicked.connect(self._on_click)
        lay.addWidget(self.canvas, 1)

        # Pixel readout (updated on click), under the image / above the buttons
        self.pixel_lbl = QLabel("Click the image to inspect a pixel.")
        lay.addWidget(self.pixel_lbl)

        # Current data-image context for pixel -> offset/value mapping
        self._px_w = self._px_h = self._px_start = self._px_skip = 0
        self._px_values = None

        bottom = QHBoxLayout()
        self.hist_cb = QCheckBox("Histogram")
        self.hist_cb.setToolTip(
            "Show a histogram of the decoded sample values instead of the image.")
        self.hist_cb.stateChanged.connect(self.draw)
        bottom.addWidget(self.hist_cb, 1)
        save = QPushButton("Save PNG…")
        save.clicked.connect(self.save_png)
        bottom.addWidget(save, 1)
        lay.addLayout(bottom)

        self._update_title()
        self.draw()

    # -- single-viewer / remembered-settings plumbing ---------------------

    def _file_label(self):
        path = getattr(self.owner, "_path", None) if self.owner is not None else None
        if not path:
            return "(no file)"
        name = os.path.basename(path)
        return name if len(name) <= 40 else name[:37] + "…"

    def _update_title(self):
        self.setWindowTitle("Image of %s" % self._file_label())

    def set_offset(self, offset):
        self.off_edit.setText(str(int(offset)))

    def _save_settings(self, *_):
        if self.owner is None:
            return
        try:
            w = int(self.w_edit.text() or 0)
            h = int(self.h_edit.text() or 0)
            skip = int(self.skip_edit.text() or 0)
        except ValueError:
            return
        s = self.owner.img_settings
        if w > 0:
            s["width"] = w
        if h > 0:
            s["height"] = h
        s["skip"] = max(0, skip)
        s["autoscale"] = self.autoscale_cb.isChecked()
        s["single"] = self.single_cb.isChecked()

    def _on_single_toggled(self, *_):
        if self.owner is not None:
            self.owner.register_single_dialog(
                self if self.single_cb.isChecked() else None)
        self._save_settings()

    def closeEvent(self, ev):
        if self.owner is not None and self.owner._img_dialog is self:
            self.owner.register_single_dialog(None)
        super().closeEvent(ev)

    def _make_image(self, w, h, offset, autoscale, skip=0):
        up = self.view.unpacker
        data = self.view.data
        values, start, end = up.decode_samples(data, offset, w * h, skip=skip)
        mask = (1 << up.bit_width) - 1
        n = len(values)
        if autoscale and n:
            vmin, vmax = min(values), max(values)
            span = (vmax - vmin) or 1
        else:
            vmin, vmax, span = 0, mask, (mask or 1)
        bpl = (w + 3) & ~3   # scanlines are 4-byte aligned
        buf = bytearray(bpl * h)
        for i in range(min(n, w * h)):
            v = values[i] if autoscale else (values[i] & mask)
            idx = (v - vmin) * 255 // span
            buf[(i // w) * bpl + (i % w)] = 0 if idx < 0 else (255 if idx > 255 else idx)
        img = QImage(bytes(buf), w, h, bpl, QImage.Format_Indexed8)
        img.setColorTable([QColor(r, g, b).rgb() for (r, g, b) in self._palette])
        return img, buf, start, n, vmin, vmax, end, values

    def _make_histogram(self, values):
        """Histogram of the decoded values. Uses matplotlib if present,
        otherwise a simple QPainter fallback. Returns QImage/QPixmap or None."""
        if not values:
            return None
        vmin, vmax = min(values), max(values)
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except ImportError:
            return self._histogram_qpainter(values, vmin, vmax)
        fig = Figure(figsize=(5.12, 4.0), dpi=100)
        canvas = FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.hist(values, bins=256, color='steelblue', edgecolor='none')
        ax.set_xlabel('Value')
        ax.set_ylabel('Count')
        ax.set_title('n=%d  [%g, %g]' % (len(values), vmin, vmax))
        fig.tight_layout()
        canvas.draw()
        buf = canvas.buffer_rgba()
        w, h = canvas.get_width_height()
        qi = QImage(bytes(buf), w, h, w * 4, QImage.Format_RGBA8888)
        return qi.copy()

    def _histogram_qpainter(self, values, vmin, vmax):
        """Dependency-free 256-bin bar histogram drawn onto a QPixmap."""
        W, H, bins = 512, 400, 256
        ml, mr, mt, mb = 55, 12, 26, 40
        span = (vmax - vmin) or 1
        counts = [0] * bins
        for v in values:
            b = (v - vmin) * (bins - 1) // span
            counts[0 if b < 0 else (bins - 1 if b >= bins else b)] += 1
        peak = max(counts) or 1
        plot_w, plot_h = W - ml - mr, H - mt - mb

        pm = QPixmap(W, H)
        pm.fill(QColor(255, 255, 255))
        p = QPainter(pm)
        bar = QColor(70, 130, 180)   # steelblue
        for i, c in enumerate(counts):
            bh = c * plot_h // peak
            x0 = ml + i * plot_w // bins
            x1 = ml + (i + 1) * plot_w // bins
            if bh:
                p.fillRect(x0, H - mb - bh, max(1, x1 - x0), bh, bar)
        p.setPen(QColor(0, 0, 0))
        p.drawLine(ml, mt, ml, H - mb)              # y axis
        p.drawLine(ml, H - mb, W - mr, H - mb)      # x axis
        p.drawText(ml, mt - 8,
                   "n=%d  [%g, %g]   Value →  (Count ↑)"
                   % (len(values), vmin, vmax))
        p.end()
        return pm

    def draw(self):
        try:
            w = int(self.w_edit.text() or 0)
            h = int(self.h_edit.text() or 0)
            offset = int(self.off_edit.text() or 0)
            skip = max(0, int(self.skip_edit.text() or 0))
        except ValueError:
            return
        if w <= 0 or h <= 0 or not self.view.data:
            self.info.setText("Enter width, height (>0) and load a file.")
            return
        self._update_title()
        self._save_settings()
        autoscale = self.autoscale_cb.isChecked()
        img, buf, start, n, vmin, vmax, end, values = self._make_image(
            w, h, offset, autoscale, skip=skip)
        self._img = img
        self._buf = buf   # must outlive the QImage
        self._last_start = start   # block-aligned start of this image
        self._last_end = end       # where the next image should begin

        # Save context for pixel -> offset/value mapping
        self._px_w, self._px_h = w, h
        self._px_start, self._px_skip = start, skip
        self._px_values = values

        # Chunk position "n of nn" (whole chunks only, partial tail ignored)
        span = self.view.unpacker.sample_span(w * h, skip)
        total = len(self.view.data) // span if span else 0
        pos = (start // span + 1) if span else 0
        self.pos_lbl.setText("%d of %d" % (min(pos, total) if total else 0, total))
        self.info.setText(
            "%d x %d = %d samples   from byte 0x%X (%d)   skip %d   got %d   next 0x%X   range %d..%d%s"
            % (w, h, w * h, start, start, skip, n, end, vmin, vmax,
               "  (auto)" if autoscale else ""))

        if self.hist_cb.isChecked():
            hist = self._make_histogram(values)
            if hist is not None:
                self._img = hist   # save the histogram, not the data image
                qi = hist if isinstance(hist, QImage) else hist.toImage()
                self.canvas.set_image(qi, mappable=False)   # not pixel-mapped
                return
            self.info.setText("No values to histogram.")

        # The canvas scales the image to fill the viewer, keeping aspect ratio
        self.canvas.set_image(img, src_w=w, src_h=h, mappable=True)

    def _pixel_at(self, x, y):
        """Return (byte_offset, value) for image pixel (x, y), or None."""
        if (self._px_values is None or x < 0 or y < 0
                or x >= self._px_w or y >= self._px_h):
            return None
        i = y * self._px_w + x
        if i >= len(self._px_values):
            return None
        raw_index = i * (self._px_skip + 1)
        off = self.view.unpacker.sample_byte_offset(self._px_start, raw_index)
        return off, self._px_values[i]

    def _on_click(self, x, y):
        hit = self._pixel_at(x, y)
        if hit is None:
            return
        off, val = hit
        mask = (1 << self.view.unpacker.bit_width) - 1
        self.pixel_lbl.setText(
            "x=%d  y=%d     offset 0x%X (%d)     value %d (0x%X)"
            % (x, y, off, off, val, val & mask))

    def _on_hover(self, x, y):
        hit = self._pixel_at(x, y)
        if hit is None:
            QToolTip.hideText()
            return
        _, val = hit
        mask = (1 << self.view.unpacker.bit_width) - 1
        QToolTip.showText(QCursor.pos(),
                          "x=%d y=%d  val=%d (0x%X)" % (x, y, val, val & mask),
                          self.canvas)

    def draw_next(self):
        """Move the offset to where the last image ended and draw again."""
        if self._last_end is None:
            self.draw()
            return
        if self._last_end >= len(self.view.data):
            self.info.setText("End of data — no more samples.")
            return
        self.set_offset(self._last_end)
        self.draw()

    def draw_prev(self):
        """Step the offset back by one image's span and draw the block before."""
        if self._last_start is None or self._last_end is None:
            self.draw()
            return
        if self._last_start <= 0:
            self.info.setText("Start of data — nothing before offset 0.")
            return
        span = max(1, self._last_end - self._last_start)
        self.set_offset(max(0, self._last_start - span))
        self.draw()

    def save_png(self):
        if self._img is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "image.png",
                                              "PNG (*.png)")
        if path:
            self._img.save(path, "PNG")


# ---------------------------------------------------------------------------
# About dialog
# ---------------------------------------------------------------------------

class AboutDialog(QDialog):
    """About box for bit-viewer (modeled on the color-picker one)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About bit-viewer")
        self.setModal(True)
        self.setFixedWidth(440)

        def bold(text):
            lbl = QLabel(text)
            f = lbl.font(); f.setBold(True); lbl.setFont(f)
            return lbl

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        name_font = QFont()
        name_font.setPointSize(15)
        name_font.setBold(True)
        name_lbl = QLabel("bit-viewer")
        name_lbl.setFont(name_font)
        root.addWidget(name_lbl)

        desc = QLabel(
            "%s  —  Hex viewer for binary data with a configurable "
            "bit-packing decode pane (continuous, grouped, or native "
            "samples) and a rainbow image preview." % VERSION)
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addSpacing(4)

        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.addRow(bold("Author:"), QLabel("Dennis Lang"))
        form.addRow(QLabel(""), QLabel("Created by LanDen Labs (2026)"))

        link = QLabel('<a href="https://landenlabs.com">https://landenlabs.com</a>')
        link.setOpenExternalLinks(True)
        form.addRow(bold("Web:"), link)

        root.addLayout(form)
        root.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, initial_path=None, mode='continuous', bit_width=9,
                 group_bytes=3, samples_per_group=2, bit_order='msb',
                 signed=False, target_bytes=16):
        super().__init__()
        self.setWindowTitle("bit-viewer %s" % VERSION)
        self.resize(1100, 720)

        self.view = HexView()
        self.view.target_bytes = target_bytes
        self.view.selectionChanged.connect(self._update_status)

        self._path = None            # path of the loaded file, if any

        # Remembered image-dialog settings (persist while the program runs)
        self.img_settings = {"width": 64, "height": 64, "skip": 0,
                             "autoscale": False, "single": False}
        self._img_dialog = None      # the live single-viewer dialog, if any

        ctrl = self._build_controls(mode, bit_width, group_bytes,
                                     samples_per_group, bit_order, signed,
                                     target_bytes)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(ctrl)
        lay.addWidget(self.view, 1)
        self.setCentralWidget(central)

        self.status = self.statusBar()
        self._apply_config()
        if initial_path:
            self.load_file(initial_path)
        else:
            self._update_status()

    def _build_controls(self, mode, bit_width, group_bytes,
                        samples_per_group, bit_order, signed, target_bytes):
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)

        open_btn = QPushButton("Open…")
        open_btn.clicked.connect(self._on_open)
        h.addWidget(open_btn)

        def sep():
            f = QFrame(); f.setFrameShape(QFrame.VLine); h.addWidget(f)

        sep()
        h.addWidget(QLabel("Mode:"))
        self.mode_cb = QComboBox()
        self.mode_cb.addItems(["native", "continuous", "grouped"])
        self.mode_cb.setCurrentText(mode)
        self.mode_cb.currentTextChanged.connect(self._apply_config)
        h.addWidget(self.mode_cb)

        h.addWidget(QLabel("Bits:"))
        self.bits_sb = QSpinBox(); self.bits_sb.setRange(1, 64)
        self.bits_sb.setValue(bit_width)
        self.bits_sb.valueChanged.connect(self._apply_config)
        h.addWidget(self.bits_sb)

        self.grp_lbl = QLabel("Group bytes:")
        h.addWidget(self.grp_lbl)
        self.grp_sb = QSpinBox(); self.grp_sb.setRange(1, 64)
        self.grp_sb.setValue(group_bytes)
        self.grp_sb.valueChanged.connect(self._apply_config)
        h.addWidget(self.grp_sb)

        self.spg_lbl = QLabel("Samples/grp:")
        h.addWidget(self.spg_lbl)
        self.spg_sb = QSpinBox(); self.spg_sb.setRange(1, 64)
        self.spg_sb.setValue(samples_per_group)
        self.spg_sb.valueChanged.connect(self._apply_config)
        h.addWidget(self.spg_sb)

        sep()
        h.addWidget(QLabel("Order:"))
        self.order_cb = QComboBox()
        self.order_cb.addItems(["msb", "lsb"])
        self.order_cb.setCurrentText(bit_order)
        self.order_cb.currentTextChanged.connect(self._apply_config)
        h.addWidget(self.order_cb)

        self.signed_cb = QCheckBox("Signed")
        self.signed_cb.setChecked(signed)
        self.signed_cb.stateChanged.connect(self._apply_config)
        h.addWidget(self.signed_cb)

        sep()
        h.addWidget(QLabel("Decode:"))
        self.disp_cb = QComboBox()
        self.disp_cb.addItems(["decimal", "hex"])
        self.disp_cb.currentTextChanged.connect(self._apply_config)
        h.addWidget(self.disp_cb)

        h.addWidget(QLabel("Bytes/row:"))
        self.bpr_cb = QComboBox()
        self.bpr_cb.addItems(["8", "16", "32"])
        self.bpr_cb.setCurrentText(str(target_bytes))
        self.bpr_cb.currentTextChanged.connect(self._apply_config)
        h.addWidget(self.bpr_cb)

        self.ascii_cb = QCheckBox("ASCII")
        self.ascii_cb.setChecked(True)
        self.ascii_cb.stateChanged.connect(self._apply_config)
        h.addWidget(self.ascii_cb)

        self.image_btn = QPushButton("Image…")
        self.image_btn.clicked.connect(self._on_image)
        h.addWidget(self.image_btn)

        h.addStretch(1)

        self.about_btn = QPushButton("?")
        self.about_btn.setFixedSize(28, 28)
        self.about_btn.setToolTip("Show the About dialog (version and credits)")
        self.about_btn.clicked.connect(self._on_about)
        h.addWidget(self.about_btn)
        return bar

    def register_single_dialog(self, dlg):
        """Track (or clear) the dialog that owns single-viewer mode."""
        self._img_dialog = dlg

    def _current_offset(self):
        return self.view.sel_byte if self.view.sel_byte is not None else 0

    def _on_image(self):
        # Single Viewer: reuse the open window, re-point it at the current
        # selection, and redraw — instead of opening another window.
        if self.img_settings.get("single") and self._img_dialog is not None:
            dlg = self._img_dialog
            dlg.set_offset(self._current_offset())
            dlg.draw()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = ImageDialog(self.view, self, owner=self)
        if dlg.single_cb.isChecked():
            self.register_single_dialog(dlg)
        dlg.show()

    def _on_about(self):
        getattr(AboutDialog(self), _QT_EXEC)()

    def _apply_config(self, *_):
        mode = self.mode_cb.currentText()
        grouped = (mode == "grouped")
        native = (mode == "native")
        self.grp_lbl.setVisible(grouped)
        self.grp_sb.setVisible(grouped)
        self.spg_lbl.setVisible(grouped)
        self.spg_sb.setVisible(grouped)
        self.bits_sb.setEnabled(not native)

        up = BitUnpacker(
            mode=mode,
            bit_width=self.bits_sb.value(),
            group_bytes=self.grp_sb.value(),
            samples_per_group=self.spg_sb.value(),
            bit_order=self.order_cb.currentText(),
            signed=self.signed_cb.isChecked(),
        )
        self.view.set_hex_decode(self.disp_cb.currentText() == "hex")
        self.view.set_show_ascii(self.ascii_cb.isChecked())
        self.view.set_unpacker(up, target_bytes=int(self.bpr_cb.currentText()))
        self._update_status()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open binary file")
        if path:
            self.load_file(path)

    def load_file(self, path):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            self.status.showMessage("Error: %s" % e)
            return
        self.view.set_data(data)
        self._path = path
        self.setWindowTitle("bit-viewer %s — %s" % (VERSION, os.path.basename(path)))
        self._update_status()

    def _update_status(self, *_):
        v = self.view
        base = ("%d bytes   %d bytes/row   %d samples/row"
                % (len(v.data), v.bytes_per_row, v.samples_per_row))
        sel = v.selection_info()
        self.status.showMessage(base + ("    |    " + sel if sel else ""))


# ---------------------------------------------------------------------------
# Headless helpers
# ---------------------------------------------------------------------------

def dump_samples(args):
    """Print the first N decoded samples to stdout (no GUI)."""
    with open(args.input, "rb") as fh:
        data = fh.read()
    up = BitUnpacker(mode=args.mode, bit_width=args.bits,
                     group_bytes=args.group_bytes,
                     samples_per_group=args.samples_per_group,
                     bit_order=args.order, signed=args.signed)
    bpr, spr = up.row_layout(args.bytes_per_row)
    print("# mode=%s bits=%d order=%s signed=%s  bytes/row=%d samples/row=%d  total=%d bytes"
          % (args.mode, up.bit_width, args.order, args.signed, bpr, spr, len(data)))
    shown = 0
    row = 0
    while shown < args.dump and row * bpr < len(data):
        samples = up.decode_row(data, row * bpr, bpr)
        for bit_off, val in samples:
            if shown >= args.dump:
                break
            gi = row * bpr + bit_off // 8
            print("  #%-6d @0x%-6X  %6d  0x%X" % (shown, gi, val, val & ((1 << up.bit_width) - 1)))
            shown += 1
        row += 1


def selftest():
    """Verify the unpacker against the spec examples."""
    ok = True

    # Example 1: continuous 9-bit, MSB-first. Pack 0,1,2,3,...
    vals = [0, 1, 2, 3, 0x1FF, 256, 9, 9]
    W = 9
    acc = 0
    for v in vals:
        acc = (acc << W) | (v & 0x1FF)
    nbytes = (len(vals) * W + 7) // 8
    data = acc.to_bytes(nbytes, 'big')
    up = BitUnpacker('continuous', 9, bit_order='msb')
    got = [v for _, v in up.decode_row(data, 0, nbytes)][:len(vals)]
    print("continuous msb: expect %s got %s  %s" % (vals, got, "OK" if got == vals else "FAIL"))
    ok &= (got == vals)

    # Example 2: grouped, two 9-bit in 3 bytes (6 pad bits), MSB-first.
    # group bits: [s0:9][s1:9][pad:6]
    def pack_group(a, b):
        g = (a & 0x1FF) << 15 | (b & 0x1FF) << 6
        return g.to_bytes(3, 'big')
    data = pack_group(257, 42) + pack_group(0x1FF, 1)
    up = BitUnpacker('grouped', 9, group_bytes=3, samples_per_group=2, bit_order='msb')
    got = [v for _, v in up.decode_row(data, 0, 6)]
    exp = [257, 42, 0x1FF, 1]
    print("grouped msb:    expect %s got %s  %s" % (exp, got, "OK" if got == exp else "FAIL"))
    ok &= (got == exp)

    # Example 3: native 8-bit
    data = bytes([0, 127, 128, 255])
    up = BitUnpacker('native')
    got = [v for _, v in up.decode_row(data, 0, 4)]
    print("native:         expect %s got %s  %s" % (list(data), got, "OK" if got == list(data) else "FAIL"))
    ok &= (got == list(data))

    # Signed round-trip (9-bit): 0x1FF -> -1
    up = BitUnpacker('continuous', 9, bit_order='msb', signed=True)
    # two 9-bit samples left-aligned in 3 bytes (6 trailing pad bits)
    data = ((0x1FF << 9 | 0x100) << 6).to_bytes(3, 'big')  # -1, then -256
    got = [v for _, v in up.decode_row(data, 0, 3)][:2]
    print("signed 9-bit:   expect [-1, -256] got %s  %s" % (got, "OK" if got == [-1, -256] else "FAIL"))
    ok &= (got == [-1, -256])

    print("\n%s" % ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_MODES = ["native", "continuous", "grouped"]


def _mode_arg(value):
    """Resolve a (possibly partial) mode name to its full form."""
    v = value.lower()
    if v in _MODES:
        return v
    matches = [m for m in _MODES if m.startswith(v)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise argparse.ArgumentTypeError(
            "invalid mode %r (choose from %s)" % (value, ", ".join(_MODES)))
    raise argparse.ArgumentTypeError(
        "ambiguous mode %r (matches %s)" % (value, ", ".join(matches)))


def main():
    parser = argparse.ArgumentParser(
        description="Hex viewer with configurable bit-packing decode.",
        epilog="bit-viewer %s\nCopyright (c) 2026 LanDen Labs - Dennis Lang" % VERSION,
        formatter_class=type(
            "Fmt",
            (argparse.ArgumentDefaultsHelpFormatter,
             argparse.RawDescriptionHelpFormatter),
            {}))
    parser.add_argument("--version", "-V", action="version",
                        version="bit-viewer %s" % VERSION)
    parser.add_argument("input_arg", nargs="?", metavar="input",
                        help="binary file to open (positional; overridden by --input)")
    parser.add_argument("--input", "--in", "-i", dest="input", default=None,
                        help="binary file to open")
    parser.add_argument("--mode", type=_mode_arg, default="continuous",
                        help="native | continuous | grouped (prefix ok)")
    parser.add_argument("--bits", type=int, default=9, help="bit width per sample")
    parser.add_argument("--group-bytes", type=int, default=3,
                        help="bytes per group (grouped mode)")
    parser.add_argument("--samples-per-group", type=int, default=2,
                        help="samples per group (grouped mode)")
    parser.add_argument("--order", choices=["msb", "lsb"], default="msb",
                        help="bit order: msb-first or lsb-first")
    parser.add_argument("--signed", action="store_true")
    parser.add_argument("--bytes-per-row", type=int, default=16,
                        help="target bytes/row (snapped to whole samples)")
    parser.add_argument("--dump", type=int, metavar="N",
                        help="headless: print first N decoded samples and exit")
    parser.add_argument("--selftest", action="store_true",
                        help="run unpacker self-tests and exit")
    args = parser.parse_args()
    if not args.input:
        args.input = args.input_arg

    if args.selftest:
        sys.exit(selftest())
    if args.dump is not None:
        if not args.input:
            parser.error("--dump requires an input file")
        dump_samples(args)
        return

    app = QApplication(sys.argv)
    app.setApplicationName("bit-viewer")
    win = MainWindow(
        initial_path=args.input,
        mode=args.mode,
        bit_width=args.bits,
        group_bytes=args.group_bytes,
        samples_per_group=args.samples_per_group,
        bit_order=args.order,
        signed=args.signed,
        target_bytes=args.bytes_per_row,
    )
    win.show()
    sys.exit(getattr(app, _QT_EXEC)())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception:
        print("\n" + "=" * 40, file=sys.stderr)
        print("CRITICAL ERROR: Unexpected exception caught", file=sys.stderr)
        print("=" * 40, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
