#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Qt color picker with hue/saturation wheel and R/G/B/A inputs (decimal + hex)."""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QRect, QObject, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QImageReader,
    QIntValidator,
    QKeySequence,
    QMovie,
    QPainter,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
    QShortcut,
)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


__version__ = "1.0.0"
WHEEL_SIZE = 260
SWATCH_SIZE = 260
WINDOW_TITLE = f"Color Picker - v{__version__}   LanDen Labs (2026)"
PICKING_TITLE = "Press escape to end picking"


class ColorWheel(QWidget):
    """Hue/saturation color wheel. Value (brightness) is fixed at 255."""

    colorPicked = pyqtSignal(QColor)

    def __init__(self, size=WHEEL_SIZE, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._wheel = self._render_wheel(size)
        self._marker = None  # (x, y) in widget coords

    @staticmethod
    def _render_wheel(size):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        cx = cy = size / 2.0
        radius = size / 2.0 - 1
        for y in range(size):
            for x in range(size):
                dx = x - cx
                dy = y - cy
                dist = math.hypot(dx, dy)
                if dist > radius:
                    continue
                angle = math.degrees(math.atan2(-dy, dx))
                if angle < 0:
                    angle += 360
                hue = angle / 360.0
                sat = min(1.0, dist / radius)
                c = QColor.fromHsvF(hue, sat, 1.0)
                img.setPixelColor(x, y, c)
        return QPixmap.fromImage(img)

    def setColor(self, color: QColor):
        """Move the marker to the HS position matching `color` (ignores V/A)."""
        h, s, _, _ = color.getHsvF()
        if h < 0:  # achromatic
            h = 0.0
        radius = self._size / 2.0 - 1
        angle = h * 2 * math.pi
        r = s * radius
        cx = cy = self._size / 2.0
        x = cx + r * math.cos(angle)
        y = cy - r * math.sin(angle)
        self._marker = (x, y)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._wheel)
        if self._marker is not None:
            x, y = self._marker
            p.setPen(QPen(Qt.GlobalColor.black, 2))
            p.drawEllipse(QPoint(int(x), int(y)), 6, 6)
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.drawEllipse(QPoint(int(x), int(y)), 6, 6)

    def mousePressEvent(self, event):
        self._pick(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position().x(), event.position().y())

    def _pick(self, x, y):
        cx = cy = self._size / 2.0
        radius = self._size / 2.0 - 1
        dx = x - cx
        dy = y - cy
        dist = math.hypot(dx, dy)
        if dist > radius:
            # clamp to edge
            dx *= radius / dist
            dy *= radius / dist
            dist = radius
        angle = math.degrees(math.atan2(-dy, dx))
        if angle < 0:
            angle += 360
        hue = angle / 360.0
        sat = dist / radius
        c = QColor.fromHsvF(hue, sat, 1.0)
        self._marker = (cx + dx, cy + dy)
        self.update()
        self.colorPicked.emit(c)


class ColorBox(QFrame):
    """Solid swatch of the current color, drawn over a checkerboard for alpha.

    During a screen-pick session it can display a magnified screen patch
    instead, with the sampled center pixel highlighted.
    """

    def __init__(self, size=SWATCH_SIZE, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._color = QColor(255, 0, 0, 255)
        self._preview: QPixmap | None = None
        self._preview_samples = 0
        self._image: QPixmap | None = None

    def setColor(self, color: QColor):
        self._color = QColor(color)
        # Any explicit color change exits image-display mode.
        self._image = None
        self.update()

    def setImage(self, pixmap: QPixmap):
        """Display ``pixmap`` stretched to fill the swatch (drop/paste cue)."""
        self._image = pixmap
        self._preview = None
        self.update()

    def setPreview(self, pixmap: QPixmap, samples: int):
        self._preview = pixmap
        self._preview_samples = max(1, samples)
        self.update()

    def clearPreview(self):
        self._preview = None
        self._preview_samples = 0
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        rect = self.contentsRect()
        if self._preview is not None:
            p.drawPixmap(rect, self._preview)
            pixel_size = rect.width() / self._preview_samples
            cx = rect.center().x()
            cy = rect.center().y()
            box = QRect(
                int(cx - pixel_size / 2),
                int(cy - pixel_size / 2),
                int(pixel_size) + 1,
                int(pixel_size) + 1,
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(Qt.GlobalColor.black, 1))
            p.drawRect(box.adjusted(-1, -1, 1, 1))
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.drawRect(box)
            return
        if self._image is not None:
            p.drawPixmap(rect, self._image)
            return
        # checkerboard so alpha is visible
        tile = 12
        for y in range(rect.top(), rect.bottom() + 1, tile):
            for x in range(rect.left(), rect.right() + 1, tile):
                light = ((x // tile) + (y // tile)) % 2 == 0
                p.fillRect(
                    QRect(x, y, tile, tile),
                    QColor(220, 220, 220) if light else QColor(170, 170, 170),
                )
        p.fillRect(rect, self._color)


class ChannelRow(QWidget):
    """Label + slider + decimal spinbox + hex field for one 0..255 channel."""

    valueChanged = pyqtSignal(int)

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._guard = False

        self.label = QLabel(label)
        self.label.setFixedWidth(20)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.spin = QSpinBox()
        self.spin.setRange(0, 255)
        self.spin.setFixedWidth(70)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self.hex = QLineEdit()
        self.hex.setFixedWidth(50)
        self.hex.setMaxLength(2)
        self.hex.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,2}"))
        )
        self.hex.setPlaceholderText("hex")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        layout.addWidget(self.spin)
        layout.addWidget(QLabel("0x"))
        layout.addWidget(self.hex)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.hex.editingFinished.connect(self._from_hex)

        self.setValue(0)

    def setValue(self, v: int):
        v = max(0, min(255, int(v)))
        self._guard = True
        self.slider.setValue(v)
        self.spin.setValue(v)
        self.hex.setText(f"{v:02X}")
        self._guard = False

    def _from_slider(self, v):
        if self._guard:
            return
        self.setValue(v)
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        if self._guard:
            return
        self.setValue(v)
        self.valueChanged.emit(v)

    def _from_hex(self):
        if self._guard:
            return
        text = self.hex.text().strip()
        if not text:
            self.setValue(self.spin.value())
            return
        try:
            v = int(text, 16)
        except ValueError:
            self.setValue(self.spin.value())
            return
        self.setValue(v)
        self.valueChanged.emit(v)


class _PickerOverlay(QWidget):
    """Fullscreen overlay on a single screen for sampling colors."""

    colorPicked = pyqtSignal(QColor)
    cursorPreview = pyqtSignal(QPixmap, int)
    cancelled = pyqtSignal()

    PREVIEW_SAMPLES = 25  # screen pixels across in the magnified preview (odd)
    PREVIEW_SIZE = SWATCH_SIZE  # matches ColorBox size
    CURSOR_RADIUS = 7  # small circle marking the sampled pixel

    def __init__(self, screen, pixmap, multi: bool = False):
        super().__init__(None)
        self._screen = screen
        self._pixmap = pixmap
        self._image = pixmap.toImage()
        self._dpr = pixmap.devicePixelRatioF() or 1.0
        self._multi = multi
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cursor_pos = None
        self._last_picked: QColor | None = None

    def _color_at(self, pos: QPoint) -> QColor:
        px = int(round(pos.x() * self._dpr))
        py = int(round(pos.y() * self._dpr))
        px = max(0, min(self._image.width() - 1, px))
        py = max(0, min(self._image.height() - 1, py))
        return QColor(self._image.pixel(px, py))

    def _emit_preview(self, pos: QPoint):
        samples = self.PREVIEW_SAMPLES
        half = samples // 2
        src_x = int(round(pos.x() * self._dpr)) - half
        src_y = int(round(pos.y() * self._dpr)) - half
        patch = self._image.copy(src_x, src_y, samples, samples)
        zoomed = QPixmap.fromImage(patch).scaled(
            self.PREVIEW_SIZE, self.PREVIEW_SIZE,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.cursorPreview.emit(zoomed, samples)

    def mouseMoveEvent(self, event):
        self._cursor_pos = event.position().toPoint()
        self._emit_preview(self._cursor_pos)
        self.update()

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            color = self._color_at(pos)
            self._last_picked = color
            self.colorPicked.emit(color)
            if self._multi:
                self.update()
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._cursor_pos is not None:
                color = self._color_at(self._cursor_pos)
                self._last_picked = color
                self.colorPicked.emit(color)
                if self._multi:
                    self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.width(), self.height(), self._pixmap)
        self._draw_hint(p)
        if self._cursor_pos is not None:
            self._draw_cursor_marker(p, self._cursor_pos)

    def _draw_hint(self, p: QPainter):
        if self._multi:
            text = "Click to pick (multiple)  —  Esc / right-click when done"
            if self._last_picked is not None:
                c = self._last_picked
                text += (
                    f"     Last: #{c.red():02X}{c.green():02X}{c.blue():02X}"
                )
        else:
            text = "Click to pick  —  Esc / right-click to cancel"
        font = QFont("Menlo")
        font.setPointSize(12)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        pad_x, pad_y = 18, 8
        bg = QRect(
            self.width() // 2 - tw // 2 - pad_x,
            12,
            tw + pad_x * 2,
            fm.height() + pad_y * 2,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(bg, 8, 8)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(bg, Qt.AlignmentFlag.AlignCenter, text)
        if self._multi and self._last_picked is not None:
            sw = QRect(bg.right() - pad_x - 18, bg.center().y() - 8, 16, 16)
            p.fillRect(sw, self._last_picked)
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sw)

    def _draw_cursor_marker(self, p: QPainter, pos: QPoint):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.CURSOR_RADIUS
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 220), 2))
        p.drawEllipse(pos, r, r)
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.drawEllipse(pos, r, r)
        # tiny center dot marking the exact sampled pixel
        p.setPen(QPen(Qt.GlobalColor.white, 1))
        p.setBrush(QColor(0, 0, 0, 220))
        p.drawRect(QRect(pos.x() - 1, pos.y() - 1, 2, 2))


class ScreenPicker(QObject):
    """Coordinates picker overlays across all attached screens."""

    colorPicked = pyqtSignal(QColor)
    cursorPreview = pyqtSignal(QPixmap, int)
    cancelled = pyqtSignal()

    def __init__(self, parent=None, multi: bool = False):
        super().__init__(parent)
        self._overlays = []
        self._multi = multi

    def start(self):
        screens = QGuiApplication.screens()
        if not screens:
            self.cancelled.emit()
            return
        for screen in screens:
            pixmap = screen.grabWindow(0)
            overlay = _PickerOverlay(screen, pixmap, multi=self._multi)
            overlay.colorPicked.connect(self._on_picked)
            overlay.cursorPreview.connect(self.cursorPreview)
            overlay.cancelled.connect(self._on_cancelled)
            overlay.showFullScreen()
            overlay.raise_()
            overlay.activateWindow()
            overlay.setFocus()
            self._overlays.append(overlay)

    def _on_picked(self, color: QColor):
        self.colorPicked.emit(color)
        if not self._multi:
            self._close_all()

    def _on_cancelled(self):
        self._close_all()
        self.cancelled.emit()

    def stop(self):
        if not self._overlays:
            return
        self._close_all()
        self.cancelled.emit()

    def is_active(self) -> bool:
        return bool(self._overlays)

    def _close_all(self):
        for o in self._overlays:
            o.close()
        self._overlays.clear()


class _MiniSwatch(QFrame):
    """Tiny solid swatch (over a checkerboard so alpha shows) for list rows."""

    def __init__(self, color: QColor, size: int = 22, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._color = QColor(color)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        rect = self.contentsRect()
        tile = 6
        for y in range(rect.top(), rect.bottom() + 1, tile):
            for x in range(rect.left(), rect.right() + 1, tile):
                light = ((x // tile) + (y // tile)) % 2 == 0
                p.fillRect(
                    QRect(x, y, tile, tile),
                    QColor(220, 220, 220) if light else QColor(170, 170, 170),
                )
        p.fillRect(rect, self._color)


class _RecentColorRow(QWidget):
    """One row in the recent-colors list: checkbox, #RRGGBBAA hex, swatch.

    Clicking anywhere outside the checkbox activates the color.
    """

    clicked = pyqtSignal(QColor)

    def __init__(self, color: QColor, mode: str = "RGBA", parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self._mode = mode
        # Enable QSS background/border rendering on this custom QWidget so
        # set_selected() can draw a border around the row.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Start with a transparent border that reserves space — toggling to
        # selected just swaps the colour, so the layout doesn't shift.
        self.setStyleSheet(self._row_style(selected=False))

        h = QHBoxLayout(self)
        # Small margins so the border doesn't crowd the checkbox/label.
        h.setContentsMargins(2, 1, 2, 1)
        h.setSpacing(8)

        self.check = QCheckBox()

        self._label = QLabel(self._hex_for_mode(mode))
        self._label.setFont(QFont("Menlo"))

        h.addWidget(self.check)
        h.addWidget(self._label)
        h.addStretch(1)
        h.addWidget(_MiniSwatch(self.color))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _hex_for_mode(self, mode: str) -> str:
        c = self.color
        if mode == "ARGB":
            return f"#{c.alpha():02X}{c.red():02X}{c.green():02X}{c.blue():02X}"
        return f"#{c.red():02X}{c.green():02X}{c.blue():02X}{c.alpha():02X}"

    def set_mode(self, mode: str):
        self._mode = mode
        self._label.setText(self._hex_for_mode(mode))

    def set_selected(self, on: bool):
        self.setStyleSheet(self._row_style(selected=on))

    @staticmethod
    def _row_style(selected: bool) -> str:
        # Type selector restricts the style to the row itself — child widgets
        # (checkbox, hex label, swatch) keep their native rendering, so the
        # checkbox's check-mark stays plainly visible.
        colour = "#666" if selected else "transparent"
        return (
            "_RecentColorRow { "
            f"border: 1px solid {colour}; border-radius: 3px; "
            "}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.color)
        super().mousePressEvent(event)


class RecentColors(QFrame):
    """Scrollable list of recently picked colors, most recent on top.

    Each row has three columns: a checkbox, the #RRGGBBAA hex value, and a
    small color swatch. Clicking a row activates that color; the "- Del"
    button removes any checked rows. At most ``MAX`` colors are retained.
    """

    MAX = 256

    colorActivated = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self._selected: _RecentColorRow | None = None
        self._mode = "RGBA"
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._list = QVBoxLayout(container)
        self._list.setContentsMargins(4, 4, 4, 4)
        self._list.setSpacing(4)
        self._list.addStretch(1)  # keeps rows packed to the top
        scroll.setWidget(container)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        self._header = QLabel()
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        self._update_header()
        save_btn = QPushButton("Save")
        save_btn.setToolTip(
            "Save all colors in the Recent list to a CSV file "
            "(#RRGGBBAA,R,G,B,A per row)"
        )
        save_btn.clicked.connect(self._save_to_csv)
        header_row.addWidget(save_btn)
        del_btn = QPushButton("- Del")
        del_btn.setToolTip("Delete the checked colors from the Recent list")
        del_btn.clicked.connect(self._delete_checked)
        header_row.addWidget(del_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.addLayout(header_row)
        # stretch=1 lets the scroll area absorb vertical growth when the
        # main window is resized taller.
        outer.addWidget(scroll, 1)

    def add(self, color: QColor):
        row = _RecentColorRow(color, mode=self._mode)
        row.clicked.connect(lambda c, r=row: self._activate(r, c))
        self._list.insertWidget(0, row)
        # trim oldest rows (the stretch always sits last in the layout)
        while self._list.count() - 1 > self.MAX:
            item = self._list.takeAt(self._list.count() - 2)
            w = item.widget()
            if w is not None:
                if w is self._selected:
                    self._selected = None
                w.deleteLater()
        self._update_header()

    def _activate(self, row: "_RecentColorRow", color: QColor):
        if self._selected is not None and self._selected is not row:
            self._selected.set_selected(False)
        row.set_selected(True)
        self._selected = row
        self.colorActivated.emit(color)

    def _delete_checked(self):
        for i in reversed(range(self._list.count())):
            row = self._list.itemAt(i).widget()
            if isinstance(row, _RecentColorRow) and row.check.isChecked():
                if row is self._selected:
                    self._selected = None
                self._list.takeAt(i)
                row.deleteLater()
        self._update_header()

    def clear_all(self):
        """Remove every color row (preserves the trailing stretch item)."""
        self._selected = None
        # Rows sit at indices 0..N-1 and the stretch is the last item.
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._update_header()

    def _update_header(self):
        # count() includes the trailing stretch item.
        self._header.setText(f"Recent ({self._list.count() - 1})")

    def set_mode(self, mode: str):
        self._mode = mode
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                w.set_mode(mode)

    def _save_to_csv(self):
        # Collect colors top-to-bottom (most recent first).
        colors: list[QColor] = []
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                colors.append(w.color)
        if not colors:
            QMessageBox.information(
                self, "Save Recent Colors", "The Recent list is empty."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Recent Colors",
            "recent_colors.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                if self._mode == "ARGB":
                    f.write("aarrggbb,alpha,red,green,blue\n")
                    for c in colors:
                        f.write(
                            f"#{c.alpha():02X}{c.red():02X}"
                            f"{c.green():02X}{c.blue():02X},"
                            f"{c.alpha()},{c.red()},{c.green()},{c.blue()}\n"
                        )
                else:
                    f.write("rrggbba,red,green,blue,alpha\n")
                    for c in colors:
                        f.write(
                            f"#{c.red():02X}{c.green():02X}"
                            f"{c.blue():02X}{c.alpha():02X},"
                            f"{c.red()},{c.green()},{c.blue()},{c.alpha()}\n"
                        )
        except OSError as exc:
            QMessageBox.warning(
                self, "Save Recent Colors", f"Could not write file:\n{exc}"
            )


def _build_date() -> str:
    try:
        return datetime.fromtimestamp(
            os.path.getmtime(Path(__file__))
        ).strftime("%Y-%m-%d")
    except OSError:
        return "unknown"


def _bold_label(text: str) -> QLabel:
    lbl = QLabel(text)
    f = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    return lbl


_DIALOG_WIDTH = 420
_ANIM_MAX_W = _DIALOG_WIDTH - 32


def _animation_path() -> Path:
    return Path(__file__).parent / "screens" / "landenlabs_400.webp"


def _animation_display_size(path: Path) -> QSize:
    """Return display size that preserves the animation's native aspect ratio."""
    native = QImageReader(str(path)).size()
    if not native.isValid() or native.width() == 0:
        return QSize(_ANIM_MAX_W, _ANIM_MAX_W)
    scale = min(1.0, _ANIM_MAX_W / native.width())
    return QSize(int(native.width() * scale), int(native.height() * scale))


class AboutDialog(QDialog):
    """About box for the Color Picker (modeled on the adb-log-viewer one)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Color Picker")
        self.setModal(True)
        self.setFixedWidth(_DIALOG_WIDTH)

        self._movie: QMovie | None = None
        self._final_pixmap: QPixmap | None = None
        self._last_frame_num: int = -1

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # Animated logo (plays once, then freezes on the last frame).
        self._anim_label = QLabel()
        self._anim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        anim_path = _animation_path()
        if anim_path.exists():
            display_size = _animation_display_size(anim_path)
            self._anim_label.setFixedSize(display_size)
            self._movie = QMovie(str(anim_path))
            self._movie.setScaledSize(display_size)
            self._anim_label.setMovie(self._movie)
            self._movie.frameChanged.connect(self._on_frame_changed)
            root.addWidget(
                self._anim_label, alignment=Qt.AlignmentFlag.AlignCenter
            )

        name_font = QFont()
        name_font.setPointSize(15)
        name_font.setBold(True)
        name_lbl = QLabel("Color Picker")
        name_lbl.setFont(name_font)
        root.addWidget(name_lbl)

        desc = QLabel(
            f"v{__version__}  —  Color picker with a color wheel, "
            "R/G/B/A sliders, hex entry, screen-pixel sampling, and a "
            "recent colors list."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addSpacing(4)

        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow(_bold_label("Author:"), QLabel("Dennis Lang"))
        form.addRow(_bold_label("Built:"), QLabel(_build_date()))
        form.addRow(QLabel(""), QLabel("Created by LanDen Labs (2026)"))

        link = QLabel(
            '<a href="https://landenlabs.com">https://landenlabs.com</a>'
        )
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.TextFormat.RichText)
        form.addRow(_bold_label("Web:"), link)

        root.addLayout(form)
        root.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def showEvent(self, event):
        super().showEvent(event)
        if self._movie is not None:
            self._last_frame_num = -1
            self._final_pixmap = None
            self._movie.start()

    def _on_frame_changed(self, frame_num: int):
        # QMovie doesn't expose a reliable "play once" flag for animated WebP,
        # and frameCount() returns 0 for some encoders. Detect the wrap from
        # the last frame back to frame 0 and freeze on the previously cached
        # final frame.
        if self._movie is None:
            return
        if frame_num == 0 and self._last_frame_num > 0:
            self._movie.stop()
            if self._final_pixmap is not None:
                self._anim_label.setMovie(None)
                self._anim_label.setPixmap(self._final_pixmap)
            return
        self._final_pixmap = self._movie.currentPixmap()
        self._last_frame_num = frame_num


def _extract_palette(image: QImage, max_colors: int = 256) -> list[QColor]:
    """Return up to ``max_colors`` representative colors from ``image``.

    Uses Qt's built-in quantization via Format_Indexed8, which produces a
    palette of at most 256 entries — exactly the cap requested for this
    feature.
    """
    indexed = image.convertToFormat(QImage.Format.Format_Indexed8)
    seen: set[int] = set()
    colors: list[QColor] = []
    for rgba in indexed.colorTable():
        if rgba in seen:
            continue
        seen.add(rgba)
        colors.append(QColor.fromRgba(rgba))
        if len(colors) >= max_colors:
            break
    return colors


class MainWindow(QMainWindow):
    _windows: list = []  # keep duplicated windows alive

    def __init__(self, initial_color: QColor | None = None):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self._guard = False
        self._color = QColor(initial_color) if initial_color else QColor(255, 0, 0, 255)

        title = QLabel("Color Picker")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        self.help_btn = QPushButton("?")
        self.help_btn.setFixedSize(28, 28)
        self.help_btn.setToolTip("Show the About dialog (version and credits)")
        self.help_btn.clicked.connect(self._show_about)

        title_row = QHBoxLayout()
        title_row.addSpacing(28)  # balance the right-side button so title centers
        title_row.addStretch(1)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.help_btn)

        self.wheel = ColorWheel()
        self.box = ColorBox()

        self.dup_btn = QPushButton("Dup Picker")
        self.dup_btn.setToolTip(
            "Open another color-picker window initialized to the current color."
        )
        self.dup_btn.clicked.connect(self._duplicate_window)
        self.dup_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.pick_btn = QPushButton("Pick from Screen")
        self.pick_btn.setToolTip(
            "Click, then click anywhere on screen to sample pixels.\n"
            "Default: multiple picks allowed; press Esc to finish.\n"
            "macOS: requires Screen Recording permission to sample other apps."
        )
        self.pick_btn.clicked.connect(self._start_screen_pick)
        self.pick_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._screen_picker = None
        self._auto_hide_mode = False
        self._pick_saved_geom = None  # QByteArray from saveGeometry()

        self.auto_hide_cb = QCheckBox("Hide")
        self.auto_hide_cb.setToolTip(
            "Hide color picker app while picking color from screen"
        )

        self.mode_btn = QPushButton("RGBA")
        self.mode_btn.setToolTip(
            "Toggle color component order between RGBA and ARGB.\n"
            "Affects the slider order, the hex field format, the Recent\n"
            "list hex labels, and the CSV export."
        )
        self.mode_btn.clicked.connect(self._toggle_color_mode)
        self.mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Stretch ratios 1:2:1 centre the wheel in the left half of the
        # window and the box in the right half as the window widens.
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.wheel, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(2)
        top.addWidget(self.box, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.mode_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.dup_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.pick_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.auto_hide_cb)
        buttons_row.addStretch(1)

        self.r_row = ChannelRow("R")
        self.g_row = ChannelRow("G")
        self.b_row = ChannelRow("B")
        self.a_row = ChannelRow("A")

        # combined hex (RRGGBBAA)
        hex_label = QLabel("#")
        self.hex_all = QLineEdit()
        self.hex_all.setMaxLength(8)
        self.hex_all.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,8}"))
        )
        self.hex_all.setFixedWidth(110)
        self.hex_all.setPlaceholderText("RRGGBBAA")
        self.add_btn = QPushButton("+ Add")
        self.add_btn.setToolTip(
            "Add the current color to the top of the Recent list "
            "(shortcut: Ctrl+Space)"
        )
        self.add_btn.clicked.connect(self._add_current_to_recent)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Ctrl+Space adds the current color to Recent regardless of which
        # widget has keyboard focus (plain Space gets eaten by whichever
        # button was last clicked, e.g. the "- Del" button).
        add_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        add_shortcut.activated.connect(self._add_current_to_recent)

        hex_row = QHBoxLayout()
        hex_row.addStretch(1)
        hex_row.addWidget(self.add_btn)
        hex_row.addSpacing(12)
        hex_row.addWidget(hex_label)
        hex_row.addWidget(self.hex_all)
        hex_row.addStretch(1)

        # left half: R/G/B/A sliders + numeric/hex entry, wrapped in a
        # bordered frame so it reads as a single group. The channel rows
        # are reordered in-place when the RGBA/ARGB toggle is pressed —
        # we keep a reference to the layout for that.
        channels_frame = QFrame()
        channels_frame.setFrameShape(QFrame.Shape.Box)
        channels_frame.setFrameShadow(QFrame.Shadow.Plain)
        self._channels_layout = QVBoxLayout(channels_frame)
        self._channels_layout.setContentsMargins(8, 8, 8, 8)
        self._channels_layout.addWidget(self.r_row)
        self._channels_layout.addWidget(self.g_row)
        self._channels_layout.addWidget(self.b_row)
        self._channels_layout.addWidget(self.a_row)
        self._channels_layout.addSpacing(4)
        self._channels_layout.addLayout(hex_row)
        self._channels_layout.addStretch(1)
        self._color_mode = "RGBA"

        # right half: scrollable list of recently picked colors (RecentColors
        # is itself a QFrame with a thin border).
        self.recent = RecentColors()
        self.recent.colorActivated.connect(self._on_recent_activated)

        lower = QHBoxLayout()
        lower.addWidget(channels_frame, 1)
        lower.addSpacing(12)
        lower.addWidget(self.recent, 1)

        central = QWidget()
        v = QVBoxLayout(central)
        v.addLayout(title_row)
        v.addLayout(top)
        v.addSpacing(8)
        v.addLayout(buttons_row)
        v.addSpacing(8)
        # Stretch=1 hands extra vertical height to the lower row so the
        # Recent list grows when the user resizes the window taller.
        v.addLayout(lower, 1)
        self.setCentralWidget(central)

        self.r_row.valueChanged.connect(self._from_channels)
        self.g_row.valueChanged.connect(self._from_channels)
        self.b_row.valueChanged.connect(self._from_channels)
        self.a_row.valueChanged.connect(self._from_channels)
        self.wheel.colorPicked.connect(self._from_wheel)
        self.hex_all.editingFinished.connect(self._from_hex_all)

        # Accept dropped images and provide a Ctrl+V paste shortcut. Text
        # fields keep their own widget-scope Ctrl+V (more specific context
        # wins), so pasting into the hex field still inserts text.
        self.setAcceptDrops(True)
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.activated.connect(self._paste_image)

        self._apply_color(self._color, source="init")

    def _apply_color(self, color: QColor, source: str):
        self._color = QColor(color)
        self._guard = True
        if source != "channels":
            self.r_row.setValue(self._color.red())
            self.g_row.setValue(self._color.green())
            self.b_row.setValue(self._color.blue())
            self.a_row.setValue(self._color.alpha())
        if source != "wheel":
            self.wheel.setColor(self._color)
        if source != "hex_all":
            self.hex_all.setText(self._format_hex(self._color))
        self.box.setColor(self._color)
        self._guard = False

    def _format_hex(self, color: QColor) -> str:
        r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
        if self._color_mode == "ARGB":
            return f"{a:02X}{r:02X}{g:02X}{b:02X}"
        return f"{r:02X}{g:02X}{b:02X}{a:02X}"

    def _from_channels(self, _):
        if self._guard:
            return
        c = QColor(
            self.r_row.spin.value(),
            self.g_row.spin.value(),
            self.b_row.spin.value(),
            self.a_row.spin.value(),
        )
        self._apply_color(c, source="channels")

    def _from_wheel(self, c: QColor):
        if self._guard:
            return
        # preserve current alpha
        c.setAlpha(self._color.alpha())
        self._apply_color(c, source="wheel")

    def _start_screen_pick(self):
        self._auto_hide_mode = self.auto_hide_cb.isChecked()
        # capture size/position so we can restore exactly after hide/show or
        # after flag changes (which can drop geometry on macOS)
        self._pick_saved_geom = self.saveGeometry()
        # always hide before the screenshot so our window pixels aren't
        # captured into the overlay's snapshot, AND so the subsequent
        # WindowStaysOnTopHint flag toggle (which recreates the native HWND
        # on Windows) happens invisibly. Without the hide, the picker stays
        # stuck under the overlay on Windows.
        self.hide()
        QTimer.singleShot(200, self._launch_screen_picker)

    def _launch_screen_picker(self):
        multi = not self._auto_hide_mode
        self._screen_picker = ScreenPicker(self, multi=multi)
        self._screen_picker.colorPicked.connect(self._on_screen_picked)
        self._screen_picker.cursorPreview.connect(self.box.setPreview)
        self._screen_picker.cancelled.connect(self._on_screen_cancelled)
        self._screen_picker.start()
        if multi:
            self.setWindowTitle(PICKING_TITLE)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self._show_during_pick()

    def _restore_pick_geometry(self):
        if self._pick_saved_geom is not None:
            self.restoreGeometry(self._pick_saved_geom)

    def _show_during_pick(self):
        self._restore_pick_geometry()
        self.show()
        self._restore_pick_geometry()
        self.raise_()

    def _set_always_on_top(self, on: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self._restore_pick_geometry()
        self.show()
        self._restore_pick_geometry()
        if on:
            self.raise_()
            self.activateWindow()

    def _add_current_to_recent(self):
        self.recent.add(self._color)

    def _toggle_color_mode(self):
        new_mode = "ARGB" if self._color_mode == "RGBA" else "RGBA"
        self._color_mode = new_mode
        # Reorder the four channel widgets without touching the trailing
        # spacing / hex_row / stretch items that follow them.
        rows = [self.r_row, self.g_row, self.b_row, self.a_row]
        for row in rows:
            self._channels_layout.removeWidget(row)
        if new_mode == "ARGB":
            ordered = [self.a_row, self.r_row, self.g_row, self.b_row]
        else:
            ordered = [self.r_row, self.g_row, self.b_row, self.a_row]
        for i, row in enumerate(ordered):
            self._channels_layout.insertWidget(i, row)
        self.hex_all.setPlaceholderText(
            "AARRGGBB" if new_mode == "ARGB" else "RRGGBBAA"
        )
        # Re-render the hex_all field in the new format.
        self.hex_all.setText(self._format_hex(self._color))
        # Update recent rows and remember the mode for new adds & CSV export.
        self.recent.set_mode(new_mode)
        self.mode_btn.setText(new_mode)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasImage() or md.hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        image = self._image_from_mime(event.mimeData())
        if image is not None and not image.isNull():
            self._process_image(image)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _paste_image(self):
        cb = QApplication.clipboard()
        # Image data first, then fall back to a file URL on the clipboard.
        img = cb.image()
        if img.isNull():
            img = self._image_from_mime(cb.mimeData())
        if img is not None and not img.isNull():
            self._process_image(img)

    @staticmethod
    def _image_from_mime(md) -> QImage | None:
        if md.hasImage():
            data = md.imageData()
            if isinstance(data, QImage):
                return data
            if isinstance(data, QPixmap):
                return data.toImage()
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    img = QImage(url.toLocalFile())
                    if not img.isNull():
                        return img
        return None

    def _process_image(self, image: QImage):
        # Show the image stretched into the swatch as a visual confirmation.
        self.box.setImage(QPixmap.fromImage(image))
        # Replace Recent with up to 256 unique colors quantized from the image.
        self.recent.clear_all()
        for color in _extract_palette(image, max_colors=256):
            self.recent.add(color)

    def _on_recent_activated(self, color: QColor):
        self._apply_color(color, source="recent")

    def _show_about(self):
        AboutDialog(self).exec()

    def _duplicate_window(self):
        child = MainWindow(initial_color=self._color)
        MainWindow._windows.append(child)
        # offset slightly so the new window isn't directly on top of this one
        geo = self.frameGeometry()
        child.move(geo.x() + 40, geo.y() + 40)
        child.show()

    def _on_screen_picked(self, color: QColor):
        color.setAlpha(self._color.alpha())
        self._apply_color(color, source="screen")
        self.recent.add(self._color)
        if self._auto_hide_mode:
            self.box.clearPreview()
            self._restore_window()
            return
        # multi mode: leave overlays up, await further picks or Esc.
        # Clicking the overlay activated it on Windows, which (since both
        # windows are topmost) pushed the overlay above the picker. Re-raise
        # the picker so its updates remain visible.
        self.raise_()
        self.activateWindow()

    def _on_screen_cancelled(self):
        self.box.clearPreview()
        if self._auto_hide_mode:
            self._restore_window()
        else:
            self.setWindowTitle(WINDOW_TITLE)
            self._set_always_on_top(False)
            self._pick_saved_geom = None
            self._screen_picker = None

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Escape
            and self._screen_picker is not None
            and self._screen_picker.is_active()
        ):
            self._screen_picker.stop()
            return
        super().keyPressEvent(event)

    def _restore_window(self):
        self._restore_pick_geometry()
        self.show()
        self._restore_pick_geometry()
        self.raise_()
        self.activateWindow()
        self._pick_saved_geom = None
        self._screen_picker = None

    def _from_hex_all(self):
        if self._guard:
            return
        text = self.hex_all.text().strip()
        if not text:
            return
        text = text.ljust(8, "F") if len(text) < 8 else text[:8]
        try:
            b0 = int(text[0:2], 16)
            b1 = int(text[2:4], 16)
            b2 = int(text[4:6], 16)
            b3 = int(text[6:8], 16)
        except ValueError:
            return
        if self._color_mode == "ARGB":
            a, r, g, b = b0, b1, b2, b3
        else:
            r, g, b, a = b0, b1, b2, b3
        self._apply_color(QColor(r, g, b, a), source="hex_all")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
