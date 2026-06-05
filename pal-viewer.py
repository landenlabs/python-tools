#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""pal-viewer.py - Qt viewer for color palette images with OCR text extraction."""

import sys
import re
import math
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple

VERSION = "v1.04.00 (Jun-2026)"

# Canonical icon PNG lives next to this script
_ICON_PNG = Path(__file__).with_name("pal-viewer.png")

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTableWidget, QTableWidgetItem, QSplitter, QFileDialog,
        QPushButton, QHeaderView, QMessageBox, QSizePolicy, QAbstractItemView,
        QProgressBar,
    )
    from PyQt6.QtGui import (
        QPixmap, QColor, QFont, QAction, QIcon,
        QPainter, QPen, QBrush, QPolygonF,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPointF, QRectF
    _AlignCenter   = Qt.AlignmentFlag.AlignCenter
    _AlignRight    = Qt.AlignmentFlag.AlignRight
    _AlignVCenter  = Qt.AlignmentFlag.AlignVCenter
    _AspectRatio   = Qt.AspectRatioMode.KeepAspectRatio
    _Smooth        = Qt.TransformationMode.SmoothTransformation
    _Horizontal    = Qt.Orientation.Horizontal
    _Vertical      = Qt.Orientation.Vertical
    _Expanding     = QSizePolicy.Policy.Expanding
    _NoEdit        = QAbstractItemView.EditTrigger.NoEditTriggers
    _SelectRows    = QAbstractItemView.SelectionBehavior.SelectRows
    _RTC           = QHeaderView.ResizeMode.ResizeToContents
    _Stretch       = QHeaderView.ResizeMode.Stretch
    _Bold          = QFont.Weight.Bold
    _Black         = Qt.GlobalColor.black
    _White         = Qt.GlobalColor.white
    _Antialias     = QPainter.RenderHint.Antialiasing
    _TextAntialias = QPainter.RenderHint.TextAntialiasing
    _exec          = "exec"
except ImportError:
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QTableWidget, QTableWidgetItem, QSplitter, QFileDialog,
            QPushButton, QHeaderView, QMessageBox, QSizePolicy, QAbstractItemView,
            QProgressBar,
        )
        from PyQt5.QtGui import (
            QPixmap, QColor, QFont, QIcon,
            QPainter, QPen, QBrush, QPolygonF,
        )
        from PyQt5.QtWidgets import QAction
        from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPointF, QRectF
        _AlignCenter   = Qt.AlignCenter
        _AlignRight    = Qt.AlignRight
        _AlignVCenter  = Qt.AlignVCenter
        _AspectRatio   = Qt.KeepAspectRatio
        _Smooth        = Qt.SmoothTransformation
        _Horizontal    = Qt.Horizontal
        _Vertical      = Qt.Vertical
        _Expanding     = QSizePolicy.Expanding
        _NoEdit        = QAbstractItemView.NoEditTriggers
        _SelectRows    = QAbstractItemView.SelectRows
        _RTC           = QHeaderView.ResizeToContents
        _Stretch       = QHeaderView.Stretch
        _Bold          = QFont.Bold
        _Black         = Qt.black
        _White         = Qt.white
        _Antialias     = QPainter.Antialiasing
        _TextAntialias = QPainter.TextAntialiasing
        _exec          = "exec_"
    except ImportError:
        print("error: PyQt6 or PyQt5 is required.", file=sys.stderr)
        print("Install:  pip install PyQt6", file=sys.stderr)
        sys.exit(1)


# ── OCR (logic mirrored from img2txt.py) ─────────────────────────────────────

def ocr_image(path: str, lang: str = "eng", psm: int = 6,
              oem: Optional[int] = None, config_extra: str = "",
              scale: str = "auto") -> str:
    """Run Tesseract OCR on *path* and return the extracted text string."""
    from PIL import Image
    import pytesseract

    parts = []
    if psm is not None:
        parts.append(f"--psm {psm}")
    if oem is not None:
        parts.append(f"--oem {oem}")
    if config_extra:
        parts.append(config_extra)
    config = " ".join(parts)

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
            img = img.resize(
                (int(img.width * factor), int(img.height * factor)), Image.LANCZOS
            )

        return pytesseract.image_to_string(img, lang=lang, config=config)


# ── Palette parser ────────────────────────────────────────────────────────────

def parse_palette(text: str) -> List[Dict]:
    """
    Parse OCR text into palette gradient-stop rows.

    The OCR output groups values in horizontal bands, e.g.:
        Step: 0.25  Step: 5   Step: 10
        A: 255      A: 255    A: 255
        R: 0        R: 0      R: 0
        G: 225      G: 198    G: 165
        B: 129      B: 85     B: 67

    Collect all Step/A/R/G/B values in document order then zip.
    This survives multi-block layouts where the pattern repeats.
    """
    pattern = re.compile(r'\b(Step|A|R|G|B)\s*:\s*([\d.]+)', re.IGNORECASE)

    buckets: Dict[str, List[str]] = {
        "Step": [], "A": [], "R": [], "G": [], "B": []
    }

    for m in pattern.finditer(text):
        key = m.group(1)
        key = "Step" if key.lower() == "step" else key.upper()
        if key in buckets:
            buckets[key].append(m.group(2))

    count = min(len(v) for v in buckets.values())
    rows: List[Dict] = []
    for i in range(count):
        try:
            rows.append({
                "Step": buckets["Step"][i],
                "A":    max(0, min(255, int(float(buckets["A"][i])))),
                "R":    max(0, min(255, int(float(buckets["R"][i])))),
                "G":    max(0, min(255, int(float(buckets["G"][i])))),
                "B":    max(0, min(255, int(float(buckets["B"][i])))),
            })
        except (ValueError, IndexError):
            continue

    return rows


# ── Gradient linearisation ────────────────────────────────────────────────────

def convert_gradient(old_stops, old_values, num_new_steps: int):
    """
    Convert a non-linear gradient to an evenly-spaced linear gradient.

    Parameters
    ----------
    old_stops     : sequence of floats in [0.0, 1.0]  (must be sorted)
    old_values    : sequence of scalars or (N, channels) array-like
    num_new_steps : number of output stops

    Returns
    -------
    new_stops  : ndarray shape (num_new_steps,)
    new_values : ndarray shape (num_new_steps,) or (num_new_steps, channels)
    """
    import numpy as np

    new_stops  = np.linspace(0.0, 1.0, num_new_steps)
    old_stops  = np.asarray(old_stops,  dtype=float)
    old_values = np.asarray(old_values, dtype=float)

    if old_values.ndim == 1:
        new_values = np.interp(new_stops, old_stops, old_values)
    else:
        new_values = np.zeros((num_new_steps, old_values.shape[1]))
        for ch in range(old_values.shape[1]):
            new_values[:, ch] = np.interp(new_stops, old_stops, old_values[:, ch])

    return new_stops, new_values


def _fmt_step(v: float) -> str:
    """Format a step value: whole numbers as int, others with up to 2 decimals."""
    if v == int(v):
        return str(int(v))
    s = f"{v:.2f}".rstrip("0")
    return s if s[-1] != "." else s[:-1]


def compute_linear_palette(rows: List[Dict]) -> List[Dict]:
    """
    Re-sample *rows* onto evenly-spaced stops using linear interpolation.

    The step range is preserved: the output spans the same min..max step
    values as the input, divided into len(rows) equal intervals.
    Returns an empty list if numpy is unavailable or rows is too short.
    """
    if len(rows) < 2:
        return list(rows)

    try:
        import numpy as np
    except ImportError:
        return []

    step_vals = [float(r["Step"]) for r in rows]
    v_min, v_max = step_vals[0], step_vals[-1]

    if v_max == v_min:
        return list(rows)

    # Normalise original step positions to [0, 1]
    old_stops = [(v - v_min) / (v_max - v_min) for v in step_vals]
    old_stops[0], old_stops[-1] = 0.0, 1.0   # clamp floating-point drift

    # ARGB per row as (N, 4) array
    old_values = [[r["A"], r["R"], r["G"], r["B"]] for r in rows]

    new_stops, new_vals = convert_gradient(old_stops, old_values, len(rows))

    result: List[Dict] = []
    for i in range(len(rows)):
        step_v = v_min + float(new_stops[i]) * (v_max - v_min)
        a, r, g, b = new_vals[i]
        result.append({
            "Step": _fmt_step(step_v),
            "A":    max(0, min(255, round(float(a)))),
            "R":    max(0, min(255, round(float(r)))),
            "G":    max(0, min(255, round(float(g)))),
            "B":    max(0, min(255, round(float(b)))),
        })

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nice_ticks(lo: float, hi: float, target: int = 5) -> List[float]:
    """Return a list of round tick values spanning [lo, hi]."""
    if hi <= lo:
        return [lo]
    span  = hi - lo
    raw   = span / max(target, 1)
    mag   = 10.0 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step  = mag
    for mult in (1, 2, 5, 10):
        step = mult * mag
        if span / step <= target * 1.5:
            break
    first = math.ceil(lo / step) * step
    ticks: List[float] = []
    t = first
    while t <= hi + step * 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


def _pixmap_to_temp_file(pixmap: QPixmap) -> str:
    """Save *pixmap* to a temporary PNG and return its path.

    The caller must delete the file when finished (OcrWorker does this
    automatically when constructed with is_temp=True).
    """
    fd, path = tempfile.mkstemp(suffix=".png", prefix="palview_")
    os.close(fd)
    pixmap.save(path, "PNG")
    return path


def _load_app_icon() -> Optional["QIcon"]:
    """Return a QIcon built from pal-viewer.png, or None if the file is missing."""
    if _ICON_PNG.exists():
        return QIcon(str(_ICON_PNG))
    return None


def _ensure_icon_files() -> None:
    """Generate platform icon files next to pal-viewer.png the first time.

    pal-viewer.ico  — multi-size Windows icon (16 … 256 px)
    pal-viewer.icns — macOS icon bundle

    Both files are skipped if they already exist.  Failures are silently
    swallowed so a missing Pillow installation never blocks the app start.
    """
    if not _ICON_PNG.exists():
        return
    try:
        from PIL import Image
        img = Image.open(_ICON_PNG).convert("RGBA")

        ico_path = _ICON_PNG.with_suffix(".ico")
        if not ico_path.exists():
            sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
            frames = [img.resize(s, Image.LANCZOS) for s in sizes]
            frames[0].save(str(ico_path), format="ICO",
                           append_images=frames[1:], sizes=sizes)

        icns_path = _ICON_PNG.with_suffix(".icns")
        if not icns_path.exists():
            img.save(str(icns_path), format="ICNS")

    except Exception:
        pass   # packaging icons are optional; never break the app over this


def _export_btn(label: str) -> QPushButton:
    """Small, tight export button — disabled until data is available."""
    btn = QPushButton(label)
    btn.setFixedHeight(20)
    btn.setEnabled(False)
    btn.setStyleSheet("QPushButton { padding: 1px 6px; font-size: 10px; }")
    return btn


def _to_java_float(s: str) -> str:
    """Format a step string as a Java float literal, e.g. '25.50' → '25.5f'."""
    try:
        v = float(s)
        text = f"{v:g}"          # drops trailing zeros
        return text + "f"
    except ValueError:
        return "0f"


def _make_palette_table(bold_font: QFont) -> QTableWidget:
    """Build a consistently-styled palette QTableWidget."""
    col_headers = ["Step", "A", "R", "G", "B", "Color"]
    tbl = QTableWidget(0, len(col_headers))
    tbl.setHorizontalHeaderLabels(col_headers)
    tbl.setAlternatingRowColors(True)
    tbl.setEditTriggers(_NoEdit)
    tbl.setSelectionBehavior(_SelectRows)
    tbl.verticalHeader().setDefaultSectionSize(22)
    tbl.verticalHeader().setVisible(False)
    hh = tbl.horizontalHeader()
    for col in range(5):
        hh.setSectionResizeMode(col, _RTC)
    hh.setSectionResizeMode(5, _Stretch)
    mono = QFont("Courier New", 10)
    tbl.setFont(mono)
    tbl.horizontalHeader().setFont(bold_font)
    return tbl


# ── Widgets ───────────────────────────────────────────────────────────────────

class ScaledImageLabel(QLabel):
    """QLabel that scales its pixmap to fill available space (aspect-ratio-correct)."""

    def __init__(self, placeholder: str = ""):
        super().__init__(placeholder)
        self._source: Optional[QPixmap] = None
        self.setAlignment(_AlignCenter)
        self.setSizePolicy(_Expanding, _Expanding)
        self.setMinimumSize(100, 60)
        self.setStyleSheet("background:#1e1e1e; color:#888; border:1px solid #444;")

    def set_image(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self._refresh()

    def _refresh(self) -> None:
        if self._source and not self._source.isNull():
            scaled = self._source.scaled(self.size(), _AspectRatio, _Smooth)
            super().setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()


class StepGraphWidget(QWidget):
    """
    X/Y plot of palette gradient stops — two lines, two X-axes.

      Top X-axis    — source  palette  (step index 0…n-1)   gray line
      Bottom X-axis — linear  palette  (step index 0…n-1)   blue line
      Shared Y-axis — step value

    Each dot is coloured with the stop's actual palette colour.
    """

    # Margins: top is larger to fit the source X-axis above the plot
    _ML = 62;  _MR = 18;  _MT = 44;  _MB = 50

    _BG       = QColor("#1e1e1e");  _PLOT_BG  = QColor("#252525")
    _GRID     = QColor("#333333");  _AXIS     = QColor("#666666")
    _YLABEL   = QColor("#aaaaaa");  _TITLE_Y  = QColor("#cccccc")
    _NO_DATA  = QColor("#555555")
    # Source line/axis: light gray; Linear line/axis: blue
    _SRC_LINE = QColor("#a0a0a0");  _SRC_TICK = QColor("#909090")
    _LIN_LINE = QColor("#4a9eff");  _LIN_TICK = QColor("#4a9eff")

    def __init__(self):
        super().__init__()
        self._src_rows: List[Dict] = []
        self._lin_rows: List[Dict] = []
        self.setSizePolicy(_Expanding, _Expanding)
        self.setMinimumSize(160, 80)
        self.setStyleSheet("background:#1e1e1e;")

    def set_data(self, src_rows: List[Dict],
                 lin_rows: Optional[List[Dict]] = None) -> None:
        self._src_rows = src_rows
        self._lin_rows = lin_rows or []
        self.update()

    def clear(self) -> None:
        self._src_rows = []
        self._lin_rows = []
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(_Antialias)
        p.setRenderHint(_TextAntialias)

        W, H = self.width(), self.height()
        ml, mr, mt, mb = self._ML, self._MR, self._MT, self._MB
        pw = W - ml - mr
        ph = H - mt - mb

        p.fillRect(0, 0, W, H, self._BG)
        if pw < 20 or ph < 20:
            p.end(); return

        p.fillRect(ml, mt, pw, ph, self._PLOT_BG)

        has_src = bool(self._src_rows)
        has_lin = bool(self._lin_rows)

        lbl_font = QFont("Arial", 9)
        p.setFont(lbl_font)
        fm = p.fontMetrics()

        if not has_src and not has_lin:
            p.setPen(QPen(self._NO_DATA))
            p.drawText(QRectF(ml, mt, pw, ph), _AlignCenter, "No data")
            p.end(); return

        # Combined Y range across both datasets
        all_vals: List[float] = (
            [float(r["Step"]) for r in self._src_rows] +
            [float(r["Step"]) for r in self._lin_rows]
        )
        y_lo, y_hi = min(all_vals), max(all_vals)
        if y_hi == y_lo:
            y_lo -= 1;  y_hi += 1

        def px_y(v: float) -> float:
            return mt + ph - (v - y_lo) / (y_hi - y_lo) * ph

        def px_x(i: int, n: int) -> float:
            return ml + (i / (n - 1) * pw if n > 1 else pw / 2)

        def draw_x_ticks(rows: List[Dict], color: QColor,
                         tick_y: float, tick_dir: float,
                         label_y: float, title_y: float, title: str) -> None:
            """Draw ticks + labels + title for one X-axis."""
            n = len(rows)
            if n == 0:
                return
            every = max(1, math.ceil(n / max(pw / 30, 1)))
            p.setPen(QPen(color))
            for i in range(n):
                if i % every != 0 and i != n - 1:
                    continue
                x = px_x(i, n)
                p.drawLine(QPointF(x, tick_y),
                           QPointF(x, tick_y + tick_dir * 5))
                lbl = str(i)
                lw = fm.horizontalAdvance(lbl)
                p.drawText(QRectF(x - lw / 2 - 1, label_y, lw + 2, 13),
                           int(_AlignCenter), lbl)
            p.drawText(QRectF(ml, title_y, pw, 13), int(_AlignCenter), title)

        # ── Y-axis: grid lines + labels ───────────────────────────
        for tv in _nice_ticks(y_lo, y_hi, target=5):
            py = px_y(tv)
            p.setPen(QPen(self._GRID, 1))
            p.drawLine(QPointF(ml, py), QPointF(ml + pw, py))
            lbl = f"{tv:g}"
            lw = fm.horizontalAdvance(lbl)
            p.setPen(QPen(self._YLABEL))
            p.drawText(QRectF(ml - lw - 6, py - 8, lw, 16),
                       int(_AlignVCenter | _AlignRight), lbl)

        # ── Top X-axis: Source  (ticks point UP from plot top) ────
        if has_src:
            draw_x_ticks(
                self._src_rows, self._SRC_TICK,
                tick_y=mt,         tick_dir=-1,       # upward
                label_y=mt - 20,   title_y=2,
                title="Source Index",
            )

        # ── Bottom X-axis: Linear  (ticks point DOWN from plot bottom)
        if has_lin:
            draw_x_ticks(
                self._lin_rows, self._LIN_TICK,
                tick_y=mt + ph,    tick_dir=+1,        # downward
                label_y=mt+ph+7,   title_y=mt+ph+23,
                title="Linear Index",
            )

        # ── Axis border ───────────────────────────────────────────
        p.setPen(QPen(self._AXIS, 1))
        p.drawRect(QRectF(ml, mt, pw, ph))

        # ── Y-axis title (rotated) ────────────────────────────────
        p.setPen(QPen(self._TITLE_Y))
        p.save()
        p.translate(12, mt + ph / 2)
        p.rotate(-90)
        p.drawText(QRectF(-40, -8, 80, 16), int(_AlignCenter), "Value")
        p.restore()

        # ── Linear line + dots (drawn first, underneath source) ───
        if has_lin:
            n_lin = len(self._lin_rows)
            lin_vals = [float(r["Step"]) for r in self._lin_rows]
            poly = QPolygonF([
                QPointF(px_x(i, n_lin), px_y(lin_vals[i])) for i in range(n_lin)
            ])
            p.setPen(QPen(self._LIN_LINE, 1.5))
            p.setBrush(QBrush())
            p.drawPolyline(poly)
            for i, row in enumerate(self._lin_rows):
                cx, cy = px_x(i, n_lin), px_y(lin_vals[i])
                a, r, g, b = row["A"], row["R"], row["G"], row["B"]
                p.setPen(QPen(self._LIN_LINE, 1.5))
                p.setBrush(QBrush(QColor(r, g, b, a)))
                p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)

        # ── Source line + dots (drawn on top) ─────────────────────
        if has_src:
            n_src = len(self._src_rows)
            src_vals = [float(r["Step"]) for r in self._src_rows]
            poly = QPolygonF([
                QPointF(px_x(i, n_src), px_y(src_vals[i])) for i in range(n_src)
            ])
            p.setPen(QPen(self._SRC_LINE, 1.5))
            p.setBrush(QBrush())
            p.drawPolyline(poly)
            for i, row in enumerate(self._src_rows):
                cx, cy = px_x(i, n_src), px_y(src_vals[i])
                a, r, g, b = row["A"], row["R"], row["G"], row["B"]
                p.setPen(QPen(QColor(200, 200, 200, 130), 1))
                p.setBrush(QBrush(QColor(r, g, b, a)))
                p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        # ── Legend (top-right corner of plot area) ────────────────
        p.setFont(QFont("Arial", 8))
        lx = ml + pw - 72
        ly = mt + 6
        SZ = 10
        if has_src:
            p.setPen(QPen(self._SRC_LINE, 1))
            p.setBrush(QBrush(self._SRC_LINE))
            p.drawRect(QRectF(lx, ly, SZ, SZ))
            p.setPen(QPen(self._YLABEL))
            p.drawText(QRectF(lx + SZ + 3, ly - 1, 56, 12),
                       int(_AlignVCenter), "Source")
            ly += 16
        if has_lin:
            p.setPen(QPen(self._LIN_LINE, 1))
            p.setBrush(QBrush(self._LIN_LINE))
            p.drawRect(QRectF(lx, ly, SZ, SZ))
            p.setPen(QPen(self._YLABEL))
            p.drawText(QRectF(lx + SZ + 3, ly - 1, 56, 12),
                       int(_AlignVCenter), "Linear")

        p.end()


class OcrWorker(QThread):
    """Runs OCR in a background thread so the UI stays responsive.

    Parameters
    ----------
    path     : file to process
    is_temp  : if True, the file is deleted after OCR (used for
               drag-and-drop / clipboard images saved to a temp file)
    """
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, path: str, is_temp: bool = False):
        super().__init__()
        self._path    = path
        self._is_temp = is_temp

    def run(self) -> None:
        try:
            text = ocr_image(self._path)
            self.finished.emit(text)
        except ImportError as exc:
            self.error.emit(
                f"Missing dependency: {exc.name}\n"
                "Install with:  pip install pillow pytesseract"
            )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if self._is_temp:
                try:
                    os.unlink(self._path)
                except OSError:
                    pass


# ── Main window ───────────────────────────────────────────────────────────────

class PaletteViewer(QMainWindow):

    def __init__(self, image_path: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("Palette Viewer")
        self.resize(1400, 760)
        self.setAcceptDrops(True)
        self._worker: Optional[OcrWorker] = None
        self._source_stem: str = "palette"   # used as default export filename
        self._src_rows_data: List[Dict] = []
        self._lin_rows_data: List[Dict] = []
        icon = _load_app_icon()
        if icon:
            self.setWindowIcon(icon)
        self._build_ui()
        if image_path:
            self.load_image(image_path)

    # ── UI construction ───────────────────────────────────────────

    def _build_ui(self) -> None:
        # Menu bar
        open_act = QAction("Open Image…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_image)

        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        file_menu.addAction(quit_act)

        paste_act = QAction("Paste Image", self)
        paste_act.setShortcut("Ctrl+V")
        paste_act.triggered.connect(self.paste_image)

        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addAction(paste_act)

        # Shared bold header font for both tables
        mono = QFont("Courier New", 10)
        bold_mono = QFont(mono)
        bold_mono.setWeight(_Bold)

        # ── Top-left: Open button + image viewer ──────────────────
        open_btn = QPushButton("Open Image…")
        open_btn.setFixedHeight(30)
        open_btn.clicked.connect(self.open_image)

        self._img_label = ScaledImageLabel(
            "Drop an image here\nor use  File › Open"
        )

        self._img_info = QLabel("")
        self._img_info.setAlignment(_AlignCenter)
        self._img_info.setStyleSheet("color:#aaa; font-size:11px;")

        img_top = QWidget()
        tv = QVBoxLayout(img_top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(3)
        tv.addWidget(open_btn)
        tv.addWidget(self._img_label)
        tv.addWidget(self._img_info)

        # ── Bottom-left: step-value graph ─────────────────────────
        self._graph = StepGraphWidget()

        # ── Left side: vertical splitter ──────────────────────────
        left_split = QSplitter(_Vertical)
        left_split.addWidget(img_top)
        left_split.addWidget(self._graph)
        left_split.setSizes([360, 300])
        left_split.setCollapsible(0, False)
        left_split.setCollapsible(1, False)

        left_wrap = QWidget()
        lv = QVBoxLayout(left_wrap)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.setSpacing(0)
        lv.addWidget(left_split)

        # ── Top-right: original (source) palette table ────────────
        self._src_label = QLabel("Source palette  —  original gradient stops")
        self._src_label.setStyleSheet(
            "font-size:11px; color:#ccc; font-weight:bold; padding:2px 0;"
        )

        self._src_count = QLabel("")
        self._src_count.setStyleSheet("font-size:11px; color:#aaa;")

        self._src_csv_btn  = _export_btn("CSV")
        self._src_java_btn = _export_btn("Java")
        self._src_csv_btn.clicked.connect(
            lambda: self._do_save_csv(self._src_rows_data,
                                      self._source_stem + "_src"))
        self._src_java_btn.clicked.connect(
            lambda: self._do_save_java(self._src_rows_data,
                                       self._source_stem + "_src"))

        self._table = _make_palette_table(bold_mono)

        # Title row: label stretches left, buttons sit right
        src_title_row = QWidget()
        str_ = QHBoxLayout(src_title_row)
        str_.setContentsMargins(0, 0, 0, 0)
        str_.setSpacing(4)
        str_.addWidget(self._src_label, 1)
        str_.addWidget(self._src_csv_btn)
        str_.addWidget(self._src_java_btn)

        src_hdr = QWidget()
        sh = QVBoxLayout(src_hdr)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(1)
        sh.addWidget(src_title_row)
        sh.addWidget(self._src_count)

        src_panel = QWidget()
        sv = QVBoxLayout(src_panel)
        sv.setContentsMargins(0, 0, 0, 4)
        sv.setSpacing(3)
        sv.addWidget(src_hdr)
        sv.addWidget(self._table)

        # ── Bottom-right: linear (resampled) palette table ────────
        self._lin_label = QLabel("Linear palette  —  evenly-spaced gradient stops")
        self._lin_label.setStyleSheet(
            "font-size:11px; color:#ccc; font-weight:bold; padding:2px 0;"
        )

        self._lin_count = QLabel("")
        self._lin_count.setStyleSheet("font-size:11px; color:#aaa;")

        self._lin_csv_btn  = _export_btn("CSV")
        self._lin_java_btn = _export_btn("Java")
        self._lin_csv_btn.clicked.connect(
            lambda: self._do_save_csv(self._lin_rows_data,
                                      self._source_stem + "_lin"))
        self._lin_java_btn.clicked.connect(
            lambda: self._do_save_java(self._lin_rows_data,
                                       self._source_stem + "_lin"))

        self._lin_table = _make_palette_table(bold_mono)

        lin_title_row = QWidget()
        ltr = QHBoxLayout(lin_title_row)
        ltr.setContentsMargins(0, 0, 0, 0)
        ltr.setSpacing(4)
        ltr.addWidget(self._lin_label, 1)
        ltr.addWidget(self._lin_csv_btn)
        ltr.addWidget(self._lin_java_btn)

        lin_hdr = QWidget()
        lh = QVBoxLayout(lin_hdr)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(1)
        lh.addWidget(lin_title_row)
        lh.addWidget(self._lin_count)

        lin_panel = QWidget()
        lnv = QVBoxLayout(lin_panel)
        lnv.setContentsMargins(0, 4, 0, 0)
        lnv.setSpacing(3)
        lnv.addWidget(lin_hdr)
        lnv.addWidget(self._lin_table)

        # ── Right side: vertical splitter (top = source, bot = linear)
        right_split = QSplitter(_Vertical)
        right_split.addWidget(src_panel)
        right_split.addWidget(lin_panel)
        right_split.setSizes([340, 340])
        right_split.setCollapsible(0, False)
        right_split.setCollapsible(1, False)

        right_wrap = QWidget()
        rv = QVBoxLayout(right_wrap)
        rv.setContentsMargins(6, 6, 6, 6)
        rv.setSpacing(0)
        rv.addWidget(right_split)

        # ── Main horizontal splitter ──────────────────────────────
        splitter = QSplitter(_Horizontal)
        splitter.addWidget(left_wrap)
        splitter.addWidget(right_wrap)
        splitter.setSizes([480, 920])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.setCentralWidget(splitter)

        # ── Status bar ────────────────────────────────────────────
        self._status = self.statusBar()
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(150)
        self._progress.setVisible(False)
        self._status.addPermanentWidget(self._progress)
        self._status.showMessage("Ready — open a palette image to begin")

    # ── File handling ─────────────────────────────────────────────

    def open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Palette Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)"
        )
        if path:
            self.load_image(path)

    def load_image(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", f"Could not load image:\n{path}")
            return

        self._source_stem = Path(path).stem
        self.setWindowTitle(f"Palette Viewer — {Path(path).name}")
        self._img_label.set_image(pixmap)
        self._img_info.setText(
            f"{Path(path).name}   {pixmap.width()} × {pixmap.height()} px"
        )
        self._reset_tables()
        self._status.showMessage(f"Running OCR on {Path(path).name} …")
        self._progress.setVisible(True)

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()

        self._worker = OcrWorker(path)
        self._worker.finished.connect(self._on_ocr_done)
        self._worker.error.connect(self._on_ocr_error)
        self._worker.start()

    # ── OCR callbacks ─────────────────────────────────────────────

    def _on_ocr_done(self, text: str) -> None:
        self._progress.setVisible(False)
        rows = parse_palette(text)

        if not rows:
            self._status.showMessage(
                "OCR complete — no palette stops detected.  Check image clarity."
            )
            QMessageBox.information(
                self, "No Data Found",
                "OCR ran successfully but no Step/A/R/G/B groups were detected.\n\n"
                "Tips:\n"
                "• Ensure the image contains labels like  Step:  A:  R:  G:  B:\n"
                "• Try a higher-resolution source image.",
            )
            return

        # Populate source table
        self._fill_table(self._table, rows)
        self._src_count.setText(f"{len(rows)} stop(s)")
        self._src_rows_data = rows
        self._src_csv_btn.setEnabled(True)
        self._src_java_btn.setEnabled(True)

        # Build linear palette
        try:
            lin_rows = compute_linear_palette(rows)
        except Exception as exc:
            lin_rows = []
            self._lin_count.setText(f"Linearisation failed: {exc}")

        if lin_rows:
            self._fill_table(self._lin_table, lin_rows)
            self._lin_count.setText(f"{len(lin_rows)} stop(s) — evenly spaced")
            self._lin_rows_data = lin_rows
            self._lin_csv_btn.setEnabled(True)
            self._lin_java_btn.setEnabled(True)
        else:
            self._lin_count.setText("numpy not available — cannot linearise")

        # Graph gets both datasets so it can draw both lines
        self._graph.set_data(rows, lin_rows)

        self._status.showMessage(
            f"Done — {len(rows)} source stop(s)  |  {len(lin_rows)} linear stop(s)"
        )

    def _on_ocr_error(self, msg: str) -> None:
        self._progress.setVisible(False)
        self._status.showMessage("OCR failed")
        QMessageBox.critical(self, "OCR Error", msg)

    # ── Reset helpers ─────────────────────────────────────────────

    def _reset_tables(self) -> None:
        """Clear both tables, graph, counts, and disable export buttons."""
        self._table.setRowCount(0)
        self._lin_table.setRowCount(0)
        self._graph.clear()
        self._src_count.setText("")
        self._lin_count.setText("")
        self._src_rows_data = []
        self._lin_rows_data = []
        for btn in (self._src_csv_btn, self._src_java_btn,
                    self._lin_csv_btn, self._lin_java_btn):
            btn.setEnabled(False)

    # ── CSV export ────────────────────────────────────────────────

    def _do_save_csv(self, rows: List[Dict], default_stem: str) -> None:
        if not rows:
            QMessageBox.information(self, "Save CSV", "No data to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV",
            f"{default_stem}.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("Step,A,R,G,B\n")
                for row in rows:
                    f.write(
                        f"{row['Step']},{row['A']},"
                        f"{row['R']},{row['G']},{row['B']}\n"
                    )
            self._status.showMessage(f"CSV saved: {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "Save CSV", f"Could not write file:\n{exc}")

    # ── Java export ───────────────────────────────────────────────

    def _do_save_java(self, rows: List[Dict], default_stem: str) -> None:
        if not rows:
            QMessageBox.information(self, "Save Java", "No data to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Java",
            f"{default_stem}.java",
            "Java files (*.java);;All files (*)",
        )
        if not path:
            return

        # Derive the constant name from the chosen filename
        pal_name = Path(path).stem.upper().replace("-", "_").replace(" ", "_")
        v_first  = _to_java_float(rows[0]["Step"])
        v_last   = _to_java_float(rows[-1]["Step"])

        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(
                    f"    public static final SunPalette PAL_{pal_name} ="
                    f" new SunPalette({v_first},{v_last},\n"
                )
                f.write("            new int[]{ // Red, Green, Blue, Alpha\n")
                for row in rows:
                    r, g, b, a = row["R"], row["G"], row["B"], row["A"]
                    f.write(
                        f"                    {r}, {g}, {b}, {a},"
                        f" // {row['Step']}\n"
                    )
                f.write("            } );\n")
            self._status.showMessage(f"Java saved: {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "Save Java", f"Could not write file:\n{exc}")

    # ── Table population ──────────────────────────────────────────

    def _fill_table(self, tbl: QTableWidget, rows: List[Dict]) -> None:
        tbl.setRowCount(len(rows))

        for i, row in enumerate(rows):
            step_item = QTableWidgetItem(row["Step"])
            step_item.setTextAlignment(int(_AlignVCenter | _AlignRight))
            tbl.setItem(i, 0, step_item)

            for col, key in enumerate(("A", "R", "G", "B"), start=1):
                item = QTableWidgetItem(str(row[key]))
                item.setTextAlignment(int(_AlignCenter))
                tbl.setItem(i, col, item)

            a, r, g, b = row["A"], row["R"], row["G"], row["B"]
            swatch = QTableWidgetItem(f"#{r:02X}{g:02X}{b:02X}")
            swatch.setTextAlignment(int(_AlignCenter))
            swatch.setBackground(QColor(r, g, b, a))
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            swatch.setForeground(QColor(_Black if lum > 128 else _White))
            swatch.setToolTip(f"rgba({r}, {g}, {b}, {a})   #{a:02X}{r:02X}{g:02X}{b:02X}")
            tbl.setItem(i, 5, swatch)

    # ── Drag-and-drop ─────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasUrls() and md.urls() and md.urls()[0].isLocalFile():
            event.acceptProposedAction()
        elif md.hasImage():
            # Image data dragged directly (e.g. from a web browser)
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasUrls():
            url = md.urls()[0]
            if url.isLocalFile():
                self.load_image(url.toLocalFile())
        elif md.hasImage():
            qimg = md.imageData()
            if qimg is not None:
                pixmap = QPixmap.fromImage(qimg)
                if not pixmap.isNull():
                    self.load_pixmap(pixmap, "Dropped image")

    # ── Clipboard paste ───────────────────────────────────────────

    def paste_image(self) -> None:
        """Load an image from the system clipboard (Ctrl+V / Edit › Paste Image)."""
        cb = QApplication.clipboard()
        md = cb.mimeData()

        # Prefer a direct pixmap; fall back to raw image data
        pixmap = cb.pixmap()
        if pixmap.isNull() and md.hasImage():
            qimg = md.imageData()
            if qimg is not None:
                pixmap = QPixmap.fromImage(qimg)

        if not pixmap.isNull():
            self.load_pixmap(pixmap, "Pasted image")
            return

        # Nothing usable on the clipboard
        QMessageBox.information(
            self, "Paste Image",
            "No image found on the clipboard.\n\n"
            "Copy an image to the clipboard first, then paste here.",
        )

    # ── Pixmap loader (shared by drop / paste) ────────────────────

    def load_pixmap(self, pixmap: QPixmap, display_name: str) -> None:
        """Start OCR on an in-memory QPixmap (no source file path)."""
        self._source_stem = display_name.replace(" ", "_")
        self.setWindowTitle(f"Palette Viewer — {display_name}")
        self._img_label.set_image(pixmap)
        self._img_info.setText(
            f"{display_name}   {pixmap.width()} × {pixmap.height()} px"
        )
        self._reset_tables()
        self._status.showMessage(f"Running OCR on {display_name} …")
        self._progress.setVisible(True)

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()

        # Persist the pixmap as a temp PNG so the existing OCR path works
        tmp = _pixmap_to_temp_file(pixmap)
        self._worker = OcrWorker(tmp, is_temp=True)
        self._worker.finished.connect(self._on_ocr_done)
        self._worker.error.connect(self._on_ocr_error)
        self._worker.start()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    import argparse

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set app icon (macOS Dock, Windows Taskbar, window chrome)
    # Also generate .ico / .icns alongside the PNG for future packaging use.
    _ensure_icon_files()
    icon = _load_app_icon()
    if icon:
        app.setWindowIcon(icon)

    ap = argparse.ArgumentParser(
        description="Qt viewer for palette images — OCR extracts gradient stops.",
        epilog="Examples:\n  pal-viewer.py pal.png\n  pal-viewer.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("image", nargs="?", metavar="IMAGE",
                    help="Palette image to open on startup.")
    ap.add_argument("--version", "-V", action="version",
                    version=f"pal-viewer {VERSION}")

    args, _ = ap.parse_known_args()

    viewer = PaletteViewer(image_path=args.image)
    viewer.show()
    return getattr(app, _exec)()


if __name__ == "__main__":
    sys.exit(main())
