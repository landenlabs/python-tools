#!/usr/bin/python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Qt color picker with hue/saturation wheel and R/G/B/A inputs (decimal + hex)."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QObject, QPoint, QRect, QSettings, QSize, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QImageReader,
    QIntValidator,
    QKeySequence,
    QMovie,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
    QShortcut,
)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
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

SETTINGS_ORG = "LanDenLabs"
SETTINGS_APP = "ColorPicker"
DEFAULT_THEME = "Light"


def _apply_theme(theme: str) -> None:
    """Apply ``theme`` ("Light" or "Dark") to the running QApplication."""
    app = QApplication.instance()
    if app is None:
        return
    app.setStyle("Fusion")
    if theme == "Dark":
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        p.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        p.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        p.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text, QColor(127, 127, 127),
        )
        p.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText, QColor(127, 127, 127),
        )
        app.setPalette(p)
    else:
        app.setPalette(app.style().standardPalette())


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
    """One row in the recent-colors list: checkbox, #RRGGBBAA hex, optional
    gradient-stop value, and a small color swatch.

    Clicking anywhere outside the checkbox activates the color.
    """

    clicked = pyqtSignal(QColor)

    def __init__(
        self,
        color: QColor,
        mode: str = "RGBA",
        stop_value: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.color = QColor(color)
        self.stop_value = stop_value
        self._mode = mode
        # Painted directly in paintEvent so we don't apply a row-level QSS
        # rule — using WA_StyledBackground+setStyleSheet here was caching
        # the palette text colour and making the hex labels lag one theme
        # toggle behind.
        self._selected = False

        h = QHBoxLayout(self)
        # Leave a small inset so the painted border doesn't crowd children.
        h.setContentsMargins(2, 1, 2, 1)
        h.setSpacing(8)

        self.check = QCheckBox()

        self._label = QLabel(self._hex_for_mode(mode))
        self._label.setFont(QFont("Menlo"))

        # Gradient stop value column (hidden until the panel enables it).
        stop_text = f"{stop_value:.3f}" if stop_value is not None else ""
        self._stop_label = QLabel(stop_text)
        self._stop_label.setFont(QFont("Menlo"))
        self._stop_label.setFixedWidth(80)
        self._stop_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._stop_label.setVisible(False)

        h.addWidget(self.check)
        h.addWidget(self._label)
        h.addWidget(self._stop_label)
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

    def set_stop_visible(self, visible: bool):
        """Show or hide the gradient-stop value column for this row."""
        self._stop_label.setVisible(visible)

    def set_stop_value(self, value: "float | None"):
        """Update the gradient-stop value and its displayed label."""
        self.stop_value = value
        self._stop_label.setText(f"{value:.3f}" if value is not None else "")

    def set_selected(self, on: bool):
        if self._selected == on:
            return
        self._selected = on
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._selected:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Medium grey reads OK against both Light and Dark palettes.
        p.setPen(QPen(QColor("#888"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.drawRoundedRect(r, 3, 3)

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
    listChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self._selected: _RecentColorRow | None = None
        self._mode = "RGBA"
        self._stop_visible = False
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
        self._master_check = QCheckBox()
        self._master_check.setToolTip(
            "Check or uncheck every row in the Recent list"
        )
        self._master_check.toggled.connect(self._set_all_checked)
        header_row.addWidget(self._master_check)
        self._header = QLabel()
        header_row.addWidget(self._header)
        self._stop_cb = QCheckBox("Stop")
        self._stop_cb.setToolTip(
            "Show/hide the gradient stop value column.\n"
            "Stop values are provided by SSDS and Pangea palette processing."
        )
        self._stop_cb.toggled.connect(self._set_stop_visible)
        header_row.addWidget(self._stop_cb)
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

    def add(self, color: QColor, stop_value: float | None = None):
        row = _RecentColorRow(color, mode=self._mode, stop_value=stop_value)
        row.set_stop_visible(self._stop_visible)
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
        self.listChanged.emit()

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
        self.listChanged.emit()

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
        self.listChanged.emit()

    def _update_header(self):
        # count() includes the trailing stretch item.
        self._header.setText(f"Recent ({self._list.count() - 1})")

    def set_mode(self, mode: str):
        self._mode = mode
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                w.set_mode(mode)

    def show_stop_column(self):
        """Ensure the gradient stop column is visible (checks the header toggle)."""
        self._stop_cb.setChecked(True)

    def stop_data(self) -> "list[tuple[QColor, float]]":
        """Return (color, stop_value) pairs for stop-bearing rows, oldest first."""
        rows: list[_RecentColorRow] = []
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow) and w.stop_value is not None:
                rows.append(w)
        rows.reverse()  # layout stores newest at index 0; reverse for oldest-first
        return [(r.color, r.stop_value) for r in rows]

    def selected_stop_index(self) -> "int | None":
        """Index (oldest-first) of the selected row among stop-bearing rows.

        Matches the indexing used by :meth:`stop_data`, so the StopGraph can
        line up its data points with the current selection. Returns None when
        nothing is selected or the selected row has no stop value.
        """
        if self._selected is None or self._selected.stop_value is None:
            return None
        rows: list[_RecentColorRow] = []
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow) and w.stop_value is not None:
                rows.append(w)
        rows.reverse()  # oldest-first, matching stop_data()
        try:
            return rows.index(self._selected)
        except ValueError:
            return None

    def apply_stop_transform(self, fn) -> int:
        """Map every row's stop value through ``fn``; return rows converted.

        Rows without a stop value are left untouched. Emits ``listChanged`` so
        the stop graph refreshes. ``fn`` errors on a given value skip that row.
        """
        count = 0
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow) and w.stop_value is not None:
                try:
                    w.set_stop_value(float(fn(w.stop_value)))
                except (ValueError, ZeroDivisionError, TypeError):
                    continue
                count += 1
        if count:
            self.listChanged.emit()
        return count

    def _set_stop_visible(self, visible: bool):
        self._stop_visible = visible
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                w.set_stop_visible(visible)

    def _set_all_checked(self, on: bool):
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                w.check.setChecked(on)

    def _save_to_csv(self):
        # Collect (color, stop_value) pairs top-to-bottom (most recent first).
        rows: list[tuple[QColor, float | None]] = []
        for i in range(self._list.count()):
            w = self._list.itemAt(i).widget()
            if isinstance(w, _RecentColorRow):
                rows.append((w.color, w.stop_value))
        if not rows:
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
        has_stop = any(sv is not None for _, sv in rows)
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                if self._mode == "ARGB":
                    header = "aarrggbb,alpha,red,green,blue"
                    if has_stop:
                        header += ",stop"
                    f.write(header + "\n")
                    for c, sv in rows:
                        line = (
                            f"#{c.alpha():02X}{c.red():02X}"
                            f"{c.green():02X}{c.blue():02X},"
                            f"{c.alpha()},{c.red()},{c.green()},{c.blue()}"
                        )
                        if has_stop:
                            line += f",{sv:.3f}" if sv is not None else ","
                        f.write(line + "\n")
                else:
                    header = "rrggbbaa,red,green,blue,alpha"
                    if has_stop:
                        header += ",stop"
                    f.write(header + "\n")
                    for c, sv in rows:
                        line = (
                            f"#{c.red():02X}{c.green():02X}"
                            f"{c.blue():02X}{c.alpha():02X},"
                            f"{c.red()},{c.green()},{c.blue()},{c.alpha()}"
                        )
                        if has_stop:
                            line += f",{sv:.3f}" if sv is not None else ","
                        f.write(line + "\n")
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


def _extract_palette_histogram(
    image: QImage,
    max_colors: int = 64,
    merge_threshold: float = 30.0,
) -> list[QColor]:
    """Histogram palette extraction with greedy fuzzy-merge clustering.

    Scales the image down for speed, tallies per-pixel RGB frequencies,
    then greedily merges colors within ``merge_threshold`` Euclidean RGB
    distance, returning the ``max_colors`` highest-population groups.
    Fully-transparent pixels are skipped.
    """
    MAX_DIM = 200
    if image.width() > MAX_DIM or image.height() > MAX_DIM:
        image = image.scaled(
            MAX_DIM, MAX_DIM,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    image = image.convertToFormat(QImage.Format.Format_ARGB32)

    counts: dict[tuple[int, int, int], int] = {}
    for y in range(image.height()):
        for x in range(image.width()):
            px = image.pixel(x, y)
            if ((px >> 24) & 0xFF) < 10:
                continue
            key = ((px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF)
            counts[key] = counts.get(key, 0) + 1

    # Sort most-frequent first so dominant colors seed the clusters early.
    sorted_colors = sorted(counts.items(), key=lambda kv: -kv[1])
    threshold_sq = merge_threshold ** 2

    # Each cluster: [r, g, b, total_count]  (floats for weighted average)
    clusters: list[list[float]] = []

    for (r, g, b), count in sorted_colors:
        best_idx, best_d = -1, threshold_sq
        for i, (cr, cg, cb, cc) in enumerate(clusters):
            d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if d < best_d:
                best_d, best_idx = d, i
        if best_idx >= 0:
            cr, cg, cb, cc = clusters[best_idx]
            nc = cc + count
            clusters[best_idx] = [
                (cr * cc + r * count) / nc,
                (cg * cc + g * count) / nc,
                (cb * cc + b * count) / nc,
                nc,
            ]
        else:
            clusters.append([float(r), float(g), float(b), float(count)])

    clusters.sort(key=lambda c: -c[3])
    return [
        QColor(int(round(r)), int(round(g)), int(round(b)))
        for r, g, b, _ in clusters[:max_colors]
    ]


def _ocr_qimage(image: QImage, psm: int = 6) -> str:
    """Run Tesseract OCR on a QImage and return the extracted text.

    Mirrors the approach used by img2txt.py: saves to a temp PNG, upscales
    small images so Tesseract handles small fonts reliably, auto-detects
    dark backgrounds (light text on dark) and inverts + sharpens before OCR,
    then discards the temp file.  Raises ImportError if Pillow or pytesseract
    is missing.
    """
    from PIL import Image as PilImage, ImageEnhance, ImageFilter, ImageOps, ImageStat
    import pytesseract

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        if not image.save(tmp.name):
            raise RuntimeError("Could not write image to temporary file for OCR")
        with PilImage.open(tmp.name) as pil_img:
            if pil_img.mode not in ("RGB", "L"):
                pil_img = pil_img.convert("RGB")
            short = min(pil_img.width, pil_img.height)
            if short < 1200:
                factor = 1200.0 / short
                pil_img = pil_img.resize(
                    (int(pil_img.width * factor), int(pil_img.height * factor)),
                    PilImage.LANCZOS,
                )
            # Auto-preprocess: invert dark-background images so Tesseract sees
            # dark text on a light background, then boost contrast and sharpen.
            if ImageStat.Stat(pil_img.convert("L")).mean[0] < 128:
                pil_img = ImageOps.invert(pil_img.convert("RGB"))
                pil_img = ImageEnhance.Contrast(pil_img).enhance(3.0)
                pil_img = pil_img.filter(ImageFilter.SHARPEN)
                pil_img = pil_img.filter(ImageFilter.SHARPEN)
            return pytesseract.image_to_string(pil_img, config=f"--psm {psm}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# Matches "Step:", "A:", "R:", "G:", "B:" tokens produced by SSDS palette images.
# Negative lookbehind (?<![A-Za-z]) prevents matching a letter inside a longer word.
_SSDS_TOKEN_RE = re.compile(
    r'(?<![A-Za-z])(Step|[ARGB])\s*:\s*(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)


def _parse_ssds_text(text: str) -> list[tuple[QColor, float]]:
    """Parse OCR text from an SSDS palette screenshot into (QColor, stop) pairs.

    The text contains repeating groups of Step/A/R/G/B rows laid out as
    horizontal columns.  We collect each key type in document order then zip
    them — since Step values always precede A/R/G/B values within each screen
    row, document order preserves the correct pairing across multiple rows.
    """
    buckets: dict[str, list] = {k: [] for k in ("step", "a", "r", "g", "b")}
    for key, val in _SSDS_TOKEN_RE.findall(text):
        k = key.lower()
        try:
            buckets[k].append(float(val) if k == "step" else int(float(val)))
        except ValueError:
            pass

    n = min(len(v) for v in buckets.values())
    if n == 0:
        return []

    results: list[tuple[QColor, float]] = []
    for i in range(n):
        step = buckets["step"][i]
        a = max(0, min(255, buckets["a"][i]))
        r = max(0, min(255, buckets["r"][i]))
        g = max(0, min(255, buckets["g"][i]))
        b = max(0, min(255, buckets["b"][i]))
        results.append((QColor(r, g, b, a), step))
    return results


# Matches the first float on a line, including OCR-truncated forms like "222."
_PANGEA_STEP_RE = re.compile(r'[0-9.-]+')
# Matches R,G,B,A quads — four integers 0-255 separated by commas (spaces allowed)
_PANGEA_COLOR_RE = re.compile(
    r'(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})'
)


def _parse_pangea_text(text: str) -> list[tuple[QColor, float]]:
    """Parse OCR text from a Pangea palette screenshot into (QColor, stop) pairs.

    Each data row (one color per line) has the format:
        [ocr noise]  <step_float>  <description>  <R>,<G>,<B>,<A>

    Strategy:
    - Anchor on the rightmost R,G,B,A quad per line (most reliable signal).
    - The step is the first float appearing before that quad.
    - Lines with no float or no color quad are skipped.
    - "222." (decimal truncated by OCR) is accepted by Python's float().
    """
    results: list[tuple[QColor, float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Use rightmost R,G,B,A match so description text can't shadow the color.
        color_matches = list(_PANGEA_COLOR_RE.finditer(line))
        if not color_matches:
            continue
        cm = color_matches[-1]

        # First float in the text before the color quad is the step value.
        sm = _PANGEA_STEP_RE.search(line[: cm.start()])
        if not sm:
            continue

        try:
            step = float(sm.group(0))
        except ValueError:
            continue

        try:
            r = max(0, min(255, int(cm.group(1))))
            g = max(0, min(255, int(cm.group(2))))
            b = max(0, min(255, int(cm.group(3))))
            a = max(0, min(255, int(cm.group(4))))
        except ValueError:
            continue

        results.append((QColor(r, g, b, a), step))

    return results


def _parse_json_palette(text: str) -> list[tuple[QColor, float]]:
    """Parse an SSDS JSON palette into (QColor, stop) pairs.

    Expected structure:
        Palettes.Palette.ColorList.ColorStep[]
    Each entry has a numeric "Step" and an "ARGB" string of four
    comma-separated decimal values in Alpha, Red, Green, Blue order
    (0–255 each), e.g. ``"255,0,204,255"``.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    try:
        steps = data["Palettes"]["Palette"]["ColorList"]["ColorStep"]
    except (KeyError, TypeError):
        return []
    if not isinstance(steps, list):
        steps = [steps]
    results: list[tuple[QColor, float]] = []
    for entry in steps:
        try:
            step = float(entry["Step"])
            a, r, g, b = [
                max(0, min(255, int(v.strip())))
                for v in entry["ARGB"].split(",")
            ]
            results.append((QColor(r, g, b, a), step))
        except (KeyError, ValueError, AttributeError, TypeError):
            continue
    return results


def _split_fields(line: str) -> list[str]:
    """Split a CSV-ish line into trimmed, non-empty fields.

    Prefers comma separation, but falls back to whitespace when the line has
    no commas — pasting from a Google Sheet drops the commas from the
    clipboard, leaving the columns separated only by tabs/spaces.
    """
    parts = line.split(",") if "," in line else line.split()
    return [t.strip() for t in parts if t.strip()]


def _parse_csv_dec_rgba(text: str) -> list[QColor]:
    """Parse rows of decimal ``red,green,blue,alpha`` channels into QColors.

    Each non-blank line holds four decimal values in the range 0-255, comma
    separated, with an optional trailing comma.  When a line has no commas the
    fields are split on whitespace instead (e.g. a Google Sheet paste).  Lines
    that don't yield exactly four valid channels are skipped.
    """
    results: list[QColor] = []
    for line in text.splitlines():
        tokens = _split_fields(line)
        if len(tokens) != 4:
            continue
        try:
            r, g, b, a = (max(0, min(255, int(float(t)))) for t in tokens)
        except ValueError:
            continue
        results.append(QColor(r, g, b, a))
    return results


def _parse_csv_dec_rgba_step(text: str) -> list[tuple[QColor, float]]:
    """Parse rows of ``red,green,blue,alpha,step`` into (QColor, stop) pairs.

    Like :func:`_parse_csv_dec_rgba` but each row carries a fifth value: a
    floating-point gradient step that may be suffixed with ``f`` (e.g.
    ``1,2,3,4,5.0f``).  A trailing comma is permitted.  When a line has no
    commas the fields are split on whitespace instead (e.g. a Google Sheet
    paste).
    """
    results: list[tuple[QColor, float]] = []
    for line in text.splitlines():
        tokens = _split_fields(line)
        if len(tokens) != 5:
            continue
        try:
            r, g, b, a = (max(0, min(255, int(float(t)))) for t in tokens[:4])
            step = float(tokens[4].rstrip("fF"))
        except ValueError:
            continue
        results.append((QColor(r, g, b, a), step))
    return results


# Matches a single hex color token, with or without a leading '#', anywhere on
# a line (3/4/6/8 hex digits).  Used by the Hex:ARGB text format.
_HEX_TOKEN_RE = re.compile(r'#?\b([0-9A-Fa-f]{3,8})\b')


def _parse_hex_argb(text: str) -> list[QColor]:
    """Parse rows of alpha-first hex colors (e.g. ``#FF3B0A8A``) into QColors.

    Each non-blank line holds one hex color, optionally prefixed with ``#``.
    The alpha-bearing 4- and 8-digit forms are Alpha, Red, Green, Blue order;
    3- and 6-digit forms have no alpha and are treated as fully opaque (see
    :func:`_parse_android_color_hex`).  Lines without a valid hex color are
    skipped.
    """
    results: list[QColor] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _HEX_TOKEN_RE.search(line)
        if not m:
            continue
        color = _parse_android_color_hex(m.group(1))
        if color is None:
            continue
        results.append(color)
    return results


# Matches a single Android gradient <item ...> element (attributes in any order).
_ANDROID_GRADIENT_ITEM_RE = re.compile(r'<item\b[^>]*?/?>', re.IGNORECASE)
_ANDROID_OFFSET_RE = re.compile(
    r'android:offset\s*=\s*"\s*([0-9.]+)\s*"', re.IGNORECASE
)
_ANDROID_COLOR_RE = re.compile(
    r'android:color\s*=\s*"\s*#([0-9A-Fa-f]{3,8})\s*"', re.IGNORECASE
)


def _parse_android_color_hex(hex_digits: str) -> "QColor | None":
    """Parse a 3/4/6/8-digit Android gradient color hex into a QColor.

    Android puts alpha first, so the alpha-bearing forms are in
    Alpha, Red, Green, Blue order: 4-digit ``#ARGB`` and 8-digit
    ``#AARRGGBB``.  The 3-digit ``#RGB`` and 6-digit ``#RRGGBB`` forms have
    no alpha channel, so alpha is assumed fully opaque (``FF``).  3- and
    4-digit forms use single hex digits expanded by duplication (CSS
    shorthand style, so ``F`` -> ``0xFF``).  Returns None for any other
    length.
    """
    n = len(hex_digits)
    if n in (3, 4):
        vals = [int(d * 2, 16) for d in hex_digits]
    elif n in (6, 8):
        vals = [int(hex_digits[i:i + 2], 16) for i in range(0, n, 2)]
    else:
        return None
    if n in (4, 8):  # alpha-first (Android ARGB): A, R, G, B
        a, r, g, b = vals
    else:  # 3/6-digit: R, G, B with no alpha channel -> fully opaque
        r, g, b = vals
        a = 255
    return QColor(r, g, b, a)


def _parse_android_gradient(text: str) -> list[tuple[QColor, float]]:
    """Parse Android gradient ``<item>`` tags into (QColor, stop) pairs.

    Each item carries an ``android:offset`` (the gradient stop position as a
    fraction of the total gradient, 0.0-1.0) and an ``android:color`` hex of
    3, 4, 6, or 8 digits (see :func:`_parse_android_color_hex`).  Items
    missing either attribute, or with an unparseable color, are skipped.
    """
    results: list[tuple[QColor, float]] = []
    for item in _ANDROID_GRADIENT_ITEM_RE.finditer(text):
        frag = item.group(0)
        om = _ANDROID_OFFSET_RE.search(frag)
        cm = _ANDROID_COLOR_RE.search(frag)
        if not om or not cm:
            continue
        try:
            stop = float(om.group(1))
        except ValueError:
            continue
        color = _parse_android_color_hex(cm.group(1))
        if color is None:
            continue
        results.append((color, stop))
    return results


class TextFormatDialog(QDialog):
    """Format-choice dialog shown when plain text is dropped or pasted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Text Color Format")
        self.setModal(True)
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        root.addWidget(QLabel("Choose how to interpret the dropped/pasted text:"))
        root.addSpacing(4)

        self._group = QButtonGroup(self)

        self._rb_rgba = QRadioButton(
            "CSV-DEC-RGBA  —  rows of  red,green,blue,alpha  (0-255)"
        )
        self._rb_rgba.setChecked(True)
        self._group.addButton(self._rb_rgba, 0)
        root.addWidget(self._rb_rgba)

        self._rb_rgba_step = QRadioButton(
            "CSV-DEC-RGBA-step  —  rows of  red,green,blue,alpha,step  "
            "(step may end in 'f')"
        )
        self._group.addButton(self._rb_rgba_step, 1)
        root.addWidget(self._rb_rgba_step)

        self._rb_android = QRadioButton(
            "Android:Gradient1  —  <item android:offset .. android:color .. /> "
            "tags  (3/4/6/8-digit hex, alpha-first; offset is the stop position)"
        )
        self._group.addButton(self._rb_android, 2)
        root.addWidget(self._rb_android)

        self._rb_hex_argb = QRadioButton(
            "Hex:ARGB  —  rows of  #AARRGGBB  hex (alpha-first; e.g. #FF3B0A8A)"
        )
        self._group.addButton(self._rb_hex_argb, 3)
        root.addWidget(self._rb_hex_argb)

        root.addSpacing(8)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def fmt(self) -> str:
        """Return 'csv_rgba', 'csv_rgba_step', 'android_gradient1', or 'hex_argb'."""
        return ("csv_rgba", "csv_rgba_step", "android_gradient1", "hex_argb")[
            self._group.checkedId()
        ]


class ImageProcessingDialog(QDialog):
    """Method-choice dialog shown when an image is dropped or pasted."""

    def __init__(self, parent=None, input_type: str = "image"):
        super().__init__(parent)
        self.setWindowTitle("Color Processing Method")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        root.addWidget(QLabel("Choose how to extract colors from the image:"))
        root.addSpacing(4)

        self._method_group = QButtonGroup(self)

        # 1. Qt Index Image
        self._rb_qt = QRadioButton(
            "Qt Index Image  —  256 colors via Qt quantization"
        )
        self._rb_qt.setChecked(True)
        self._method_group.addButton(self._rb_qt, 0)
        root.addWidget(self._rb_qt)

        # 2. Histogram
        self._rb_hist = QRadioButton(
            "Histogram  —  N most popular colors with fuzzy shade merging"
        )
        self._method_group.addButton(self._rb_hist, 1)
        root.addWidget(self._rb_hist)

        # Sub-row: color count radios (indented under histogram option)
        self._hist_sub = QWidget()
        sub = QHBoxLayout(self._hist_sub)
        sub.setContentsMargins(28, 0, 0, 4)
        sub.addWidget(QLabel("Colors:"))
        self._n_group = QButtonGroup(self._hist_sub)
        for n in (16, 64, 256):
            rb = QRadioButton(str(n))
            if n == 64:
                rb.setChecked(True)
            self._n_group.addButton(rb, n)
            sub.addWidget(rb)
        sub.addStretch(1)
        self._hist_sub.setEnabled(False)
        root.addWidget(self._hist_sub)

        # 3. SSDS — OCR extracts Step/A/R/G/B values and builds gradient stops
        self._rb_ssds = QRadioButton(
            "SSDS Color Palette  —  OCR extracts Step / A / R / G / B values"
        )
        self._method_group.addButton(self._rb_ssds, 2)
        root.addWidget(self._rb_ssds)

        # 4. Pangea (not yet implemented)
        # 4. Pangea — OCR extracts step and R,G,B,A from one-row-per-color layout
        self._rb_pangea = QRadioButton(
            "Pangea Color Palette  —  OCR extracts step and R,G,B,A per row"
        )
        self._method_group.addButton(self._rb_pangea, 3)
        root.addWidget(self._rb_pangea)

        # 5. SSDS-JSON — parse Step/ARGB from a dropped or pasted .json file
        self._rb_ssds_json = QRadioButton(
            "SSDS-JSON Palette  —  Parse Step / ARGB from a .json palette file"
        )
        self._method_group.addButton(self._rb_ssds_json, 4)
        root.addWidget(self._rb_ssds_json)

        root.addSpacing(8)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Enable/disable the color-count sub-row to match histogram selection.
        self._rb_hist.toggled.connect(self._hist_sub.setEnabled)

        # Lock options to what makes sense for the input type.
        if input_type == "json":
            self._rb_ssds_json.setChecked(True)
            for rb in (self._rb_qt, self._rb_hist, self._rb_ssds, self._rb_pangea):
                rb.setEnabled(False)
            self._hist_sub.setEnabled(False)
        else:
            self._rb_ssds_json.setEnabled(False)

    def method(self) -> str:
        """Return 'qt_index', 'histogram', 'ssds', 'pangea', or 'ssds_json'."""
        return ("qt_index", "histogram", "ssds", "pangea", "ssds_json")[
            self._method_group.checkedId()
        ]

    def n_colors(self) -> int:
        """Return the chosen histogram color count (16, 64, or 256)."""
        n = self._n_group.checkedId()
        return n if n > 0 else 64


class StopGraphWidget(QWidget):
    """Line graph: Y = gradient-stop value, X = color index (oldest → newest)."""

    _ML = 52   # left margin  — Y-axis labels
    _MR = 10   # right margin
    _MT = 10   # top margin
    _MB = 30   # bottom margin — X-axis labels

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[int, float, QColor]] = []
        self._selected_index: int | None = None
        self.setMinimumSize(200, 160)

    def set_data(self, data: "list[tuple[int, float, QColor]]"):
        self._data = list(data)
        self.update()

    def set_selected_index(self, index: int | None):
        """Highlight the data point at ``index`` with a crosshair, or clear it."""
        self._selected_index = index
        self.update()

    def _plot_rect(self) -> QRect:
        r = self.rect()
        return QRect(
            r.left() + self._ML,
            r.top() + self._MT,
            r.width() - self._ML - self._MR,
            r.height() - self._MT - self._MB,
        )

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text_c = pal.color(QPalette.ColorRole.Text)
        base_c = pal.color(QPalette.ColorRole.Base)
        mid_c  = pal.color(QPalette.ColorRole.Mid)
        hi_c   = pal.color(QPalette.ColorRole.Highlight)
        pr = self._plot_rect()

        if len(self._data) < 2:
            p.setPen(text_c)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No stop data")
            return

        if pr.width() <= 0 or pr.height() <= 0:
            return

        stops = [sv for _, sv, _ in self._data]
        min_s, max_s = min(stops), max(stops)
        if max_s == min_s:
            max_s = min_s + 1.0
        n = len(self._data)

        def gx(k: int) -> int:
            return pr.left() + int(k / max(n - 1, 1) * pr.width())

        def gy(sv: float) -> int:
            return pr.bottom() - int((sv - min_s) / (max_s - min_s) * pr.height())

        # Plot area background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base_c)
        p.drawRect(pr)

        # Horizontal grid lines + Y-axis labels
        n_grid = 5
        font = QFont("Menlo")
        font.setPointSize(8)
        p.setFont(font)
        for i in range(n_grid + 1):
            sv = min_s + i * (max_s - min_s) / n_grid
            y = gy(sv)
            p.setPen(QPen(mid_c, 1, Qt.PenStyle.DotLine))
            p.drawLine(pr.left(), y, pr.right(), y)
            p.setPen(text_c)
            p.drawText(
                0, y - 8, self._ML - 4, 16,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{sv:.2f}",
            )

        # Axes
        p.setPen(QPen(text_c, 1))
        p.drawLine(pr.left(), pr.top(), pr.left(), pr.bottom())
        p.drawLine(pr.left(), pr.bottom(), pr.right(), pr.bottom())

        # X-axis ticks + labels
        tick_step = max(1, n // 8)
        for k in range(0, n, tick_step):
            x = gx(k)
            p.setPen(QPen(text_c, 1))
            p.drawLine(x, pr.bottom(), x, pr.bottom() + 4)
            p.drawText(x - 15, pr.bottom() + 6, 30, 14,
                       Qt.AlignmentFlag.AlignCenter, str(k))

        # Crosshair at the selected stop: thin horizontal + vertical lines in
        # the selected color, intersecting at that data point. Drawn before the
        # connecting line and dots so the highlighted point stays on top.
        if self._selected_index is not None and 0 <= self._selected_index < n:
            sk = self._selected_index
            _, ssv, scolor = self._data[sk]
            sx, sy = gx(sk), gy(ssv)
            p.setPen(QPen(scolor, 1, Qt.PenStyle.SolidLine))
            p.drawLine(pr.left(), sy, pr.right(), sy)
            p.drawLine(sx, pr.top(), sx, pr.bottom())

        # Connecting line
        pts = [QPoint(gx(k), gy(sv)) for k, (_, sv, _) in enumerate(self._data)]
        p.setPen(QPen(hi_c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

        # Colored dot at each data point
        for k, (_, _sv, color) in enumerate(self._data):
            pt = pts[k]
            p.setBrush(color)
            p.setPen(QPen(text_c, 1))
            p.drawEllipse(pt, 5, 5)


class StopGraphPanel(QFrame):
    """Collapsible right-side panel that plots gradient stop values as a line graph.

    The graph auto-expands when the Recent list contains ≥2 entries with stop
    values; the user can collapse it with the ▼/▶ button in the panel header.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setMinimumWidth(220)
        self._expanded = True

        self._title_lbl = QLabel("Stop Graph")
        f = self._title_lbl.font()
        f.setBold(True)
        self._title_lbl.setFont(f)

        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setFixedSize(22, 22)
        self._toggle_btn.setToolTip("Collapse the graph")
        self._toggle_btn.clicked.connect(self._on_toggle)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(6, 2, 4, 2)
        hdr.addWidget(self._title_lbl)
        hdr.addStretch(1)
        hdr.addWidget(self._toggle_btn)

        self._graph = StopGraphWidget()

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addLayout(hdr)
        root.addWidget(self._graph, 1)

    def _on_toggle(self):
        self._expanded = not self._expanded
        self._graph.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")
        self._toggle_btn.setToolTip(
            "Collapse the graph" if self._expanded else "Expand the graph"
        )

    def expand(self):
        if not self._expanded:
            self._on_toggle()

    def is_expanded(self) -> bool:
        return self._expanded

    def has_data(self) -> bool:
        return len(self._graph._data) >= 2

    @staticmethod
    def _step_stats(data: "list[tuple[int, float, QColor]]") -> "tuple[float, float] | None":
        """Return (most_common_delta, pct_of_all_steps) or None if < 2 points."""
        if len(data) < 2:
            return None
        stops = [sv for _, sv, _ in data]
        deltas = [round(stops[i + 1] - stops[i], 4) for i in range(len(stops) - 1)]
        counts: dict[float, int] = {}
        for d in deltas:
            counts[d] = counts.get(d, 0) + 1
        best = max(counts, key=lambda k: counts[k])
        pct = 100.0 * counts[best] / len(deltas)
        return best, pct

    def set_selected_index(self, index: int | None):
        self._graph.set_selected_index(index)

    def update_from_recent(self, recent: "RecentColors"):
        pairs = recent.stop_data()
        data = [(k, sv, c) for k, (c, sv) in enumerate(pairs)]
        self._graph.set_data(data)
        self._graph.set_selected_index(recent.selected_stop_index())
        stats = self._step_stats(data)
        if stats is not None:
            delta, pct = stats
            self._title_lbl.setText(f"Stop Graph  Δ={delta:.3f}  {pct:.0f}%")
        else:
            self._title_lbl.setText("Stop Graph")


# --- Unit conversions ----------------------------------------------------
#
# Rather than hand-code one function per A->B pair (which grows quadratically),
# each unit is defined once relative to a canonical base unit for its physical
# dimension, as a (to_base, from_base) pair of functions. Any conversion is
# then the composition  from_base_to(to_base_from(x)) — so adding a new unit
# only requires one entry, and every pairing with existing units comes for
# free. This handles affine temperature scales (offset + factor) as cleanly as
# the purely multiplicative length/speed scales.
_UNIT_DIMENSIONS: "dict[str, dict[str, tuple]]" = {
    "temperature": {  # base: Kelvin
        "Kelvin":     (lambda k: k, lambda k: k),
        "Celsius":    (lambda c: c + 273.15, lambda k: k - 273.15),
        "Fahrenheit": (lambda f: (f - 32.0) * 5.0 / 9.0 + 273.15,
                       lambda k: (k - 273.15) * 9.0 / 5.0 + 32.0),
    },
    "length": {  # base: meter
        "Meters":      (lambda m: m, lambda m: m),
        "Feet":        (lambda ft: ft * 0.3048, lambda m: m / 0.3048),
        "Centimeters": (lambda cm: cm / 100.0, lambda m: m * 100.0),
    },
    "speed": {  # base: meters per second
        "Meters per second":   (lambda v: v, lambda v: v),
        "Kilometers per hour": (lambda v: v / 3.6, lambda v: v * 3.6),
        "Miles per hour":      (lambda v: v * 0.44704, lambda v: v / 0.44704),
        "Knots":               (lambda v: v * 0.514444, lambda v: v / 0.514444),
    },
}


def _make_unit_converter(dim: str, from_unit: str, to_unit: str):
    """Return a function converting ``from_unit`` -> ``to_unit`` within ``dim``."""
    to_base, _ = _UNIT_DIMENSIONS[dim][from_unit]
    _, from_base = _UNIT_DIMENSIONS[dim][to_unit]
    return lambda x: from_base(to_base(x))


def _simplify_gradient_stops(
    pairs: "list[tuple[QColor, float]]", tolerance: float
) -> "list[tuple[QColor, float]]":
    """Reduce a gradient to its main color inflection points.

    Treats the gradient as a piecewise-linear curve through RGBA space
    parametrized by the stop position, then applies Ramer-Douglas-Peucker
    simplification: a stop is dropped when its actual color lies within
    ``tolerance`` (Euclidean RGBA distance, 0-510) of the color that linear
    interpolation between the retained neighbours would produce at that
    stop. The first and last stops are always kept. Input order doesn't
    matter — the stops are sorted by position first.
    """
    if len(pairs) <= 2:
        return list(pairs)
    pts = sorted(pairs, key=lambda cs: cs[1])  # ascending by stop position
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True

    def deviation(i: int, i0: int, i1: int) -> float:
        """Color distance at point ``i`` from the i0->i1 interpolation line."""
        s0, s1 = pts[i0][1], pts[i1][1]
        f = 0.0 if s1 == s0 else (pts[i][1] - s0) / (s1 - s0)
        c0, c1, c = pts[i0][0], pts[i1][0], pts[i][0]
        dr = c.red()   - (c0.red()   + f * (c1.red()   - c0.red()))
        dg = c.green() - (c0.green() + f * (c1.green() - c0.green()))
        db = c.blue()  - (c0.blue()  + f * (c1.blue()  - c0.blue()))
        da = c.alpha() - (c0.alpha() + f * (c1.alpha() - c0.alpha()))
        return math.sqrt(dr * dr + dg * dg + db * db + da * da)

    # Iterative RDP (an explicit stack avoids recursion limits on long
    # gradients): split each span at its largest deviation while it exceeds
    # the tolerance.
    stack = [(0, len(pts) - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        max_d, max_i = -1.0, -1
        for i in range(i0 + 1, i1):
            d = deviation(i, i0, i1)
            if d > max_d:
                max_d, max_i = d, i
        if max_d > tolerance:
            keep[max_i] = True
            stack.append((i0, max_i))
            stack.append((max_i, i1))

    return [pts[i] for i in range(len(pts)) if keep[i]]


# Conversions surfaced in the "Unit" button menu, grouped by category. Each
# entry is (menu_label, dimension, from_unit, to_unit). Add a row here to
# expose any pairing the dimension tables above already support.
_STOP_CONVERSIONS: "list[tuple[str, list[tuple[str, str, str, str]]]]" = [
    ("Temperature", [
        ("Kelvin → Celsius",      "temperature", "Kelvin", "Celsius"),
        ("Celsius → Fahrenheit",  "temperature", "Celsius", "Fahrenheit"),
        ("Fahrenheit → Celsius",  "temperature", "Fahrenheit", "Celsius"),
        ("Celsius → Kelvin",      "temperature", "Celsius", "Kelvin"),
    ]),
    ("Length", [
        ("Feet → Meters",         "length", "Feet", "Meters"),
        ("Meters → Centimeters",  "length", "Meters", "Centimeters"),
        ("Centimeters → Meters",  "length", "Centimeters", "Meters"),
        ("Meters → Feet",         "length", "Meters", "Feet"),
    ]),
    ("Speed", [
        ("Knots → Miles per hour",          "speed", "Knots", "Miles per hour"),
        ("Miles per hour → Km per hour",    "speed", "Miles per hour", "Kilometers per hour"),
        ("Km per hour → Meters per second", "speed", "Kilometers per hour", "Meters per second"),
        ("Meters per second → Km per hour", "speed", "Meters per second", "Kilometers per hour"),
        ("Km per hour → Miles per hour",    "speed", "Kilometers per hour", "Miles per hour"),
        ("Miles per hour → Knots",          "speed", "Miles per hour", "Knots"),
    ]),
]


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

        self.graph_btn = QPushButton("Graph")
        self.graph_btn.setCheckable(True)
        self.graph_btn.setToolTip("Show / hide the stop-value line graph panel")
        self.graph_btn.clicked.connect(self._on_graph_btn_toggled)
        self.graph_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._graph_panel_user_hidden = False

        self.unit_btn = QPushButton("Unit")
        self.unit_btn.setToolTip(
            "Convert the gradient stop values in the Recent list between units"
        )
        self.unit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        unit_menu = QMenu(self.unit_btn)
        for cat_name, conversions in _STOP_CONVERSIONS:
            sub = unit_menu.addMenu(cat_name)
            for label, dim, frm, to in conversions:
                act = sub.addAction(label)
                act.triggered.connect(
                    lambda _checked=False, d=dim, f=frm, t=to:
                    self._apply_unit_conversion(d, f, t)
                )
        self.unit_btn.setMenu(unit_menu)

        self.simplify_btn = QPushButton("Simplify")
        self.simplify_btn.setToolTip(
            "Reduce the gradient to its main color inflection points by "
            "removing\nintermediate stops that fall on a straight color "
            "interpolation between\ntheir neighbours (Ramer-Douglas-Peucker)."
        )
        self.simplify_btn.clicked.connect(self._simplify_gradient)
        self.simplify_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.mode_btn = QPushButton("RGBA")
        self.mode_btn.setToolTip(
            "Toggle color component order between RGBA and ARGB.\n"
            "Affects the slider order, the hex field format, the Recent\n"
            "list hex labels, and the CSV export."
        )
        self.mode_btn.clicked.connect(self._toggle_color_mode)
        self.mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Theme defaults to Light; persisted across sessions via QSettings.
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._theme = settings.value("theme", DEFAULT_THEME, type=str)
        if self._theme not in ("Light", "Dark"):
            self._theme = DEFAULT_THEME
        _apply_theme(self._theme)
        self.theme_btn = QPushButton(self._theme)
        self.theme_btn.setToolTip("Toggle between Light and Dark theme")
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.theme_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

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
        buttons_row.addWidget(self.theme_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.mode_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.dup_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.pick_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.auto_hide_cb)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.graph_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.unit_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.simplify_btn)
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
            "(shortcut: Ctrl+A)"
        )
        self.add_btn.clicked.connect(self._add_current_to_recent)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Ctrl+A adds the current color to Recent regardless of which widget
        # has focus. Ctrl+Space was intercepted by macOS for input switching.
        add_shortcut = QShortcut(QKeySequence("Ctrl+A"), self)
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
        self.recent.listChanged.connect(self._on_recent_list_changed)

        self._graph_panel = StopGraphPanel()
        self._graph_panel.setVisible(False)

        lower = QHBoxLayout()
        lower.addWidget(channels_frame, 1)
        lower.addSpacing(12)
        lower.addWidget(self.recent, 1)
        lower.addSpacing(8)
        lower.addWidget(self._graph_panel, 2)

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

    def _toggle_theme(self):
        self._theme = "Dark" if self._theme == "Light" else "Light"
        _apply_theme(self._theme)
        self.theme_btn.setText(self._theme)
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("theme", self._theme)

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
        md = event.mimeData()
        json_text = self._json_text_from_mime(md)
        if json_text is not None:
            self._show_json_processing_dialog(json_text)
            event.acceptProposedAction()
            return
        image = self._image_from_mime(md)
        if image is not None and not image.isNull():
            self._show_image_processing_dialog(image)
            event.acceptProposedAction()
            return
        csv_text = self._csv_text_from_mime(md)
        if csv_text is not None:
            self._show_text_format_dialog(csv_text)
            event.acceptProposedAction()
            return
        event.ignore()

    def _paste_image(self):
        cb = QApplication.clipboard()
        # JSON file URL on clipboard takes priority.
        json_text = self._json_text_from_mime(cb.mimeData())
        if json_text is not None:
            self._show_json_processing_dialog(json_text)
            return
        # Plain JSON text on clipboard (e.g. copied from an editor).
        clip_text = cb.text().strip()
        if clip_text.startswith("{"):
            self._show_json_processing_dialog(clip_text)
            return
        # Image data takes priority over CSV-style text.
        img = cb.image()
        if img.isNull():
            img = self._image_from_mime(cb.mimeData())
        if img is not None and not img.isNull():
            self._show_image_processing_dialog(img)
            return
        # Fall back to plain CSV-style text: prompt for the channel format.
        if clip_text:
            self._show_text_format_dialog(clip_text)

    @staticmethod
    def _json_text_from_mime(md) -> str | None:
        """Return the text of the first .json file URL in ``md``, or None."""
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".json"):
                    try:
                        with open(url.toLocalFile(), encoding="utf-8") as fh:
                            return fh.read()
                    except OSError:
                        pass
        return None

    @staticmethod
    def _csv_text_from_mime(md) -> str | None:
        """Return plain text from a dropped/pasted text file or text payload."""
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(
                    (".txt", ".csv", ".tsv")
                ):
                    try:
                        with open(url.toLocalFile(), encoding="utf-8") as fh:
                            return fh.read()
                    except OSError:
                        pass
        if md.hasText():
            text = md.text().strip()
            if text:
                return text
        return None

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

    def _show_image_processing_dialog(self, image: QImage):
        """Show method-choice dialog, then process with the selected method."""
        dlg = ImageProcessingDialog(self, input_type="image")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._process_image(image, method=dlg.method(), n_colors=dlg.n_colors())

    def _show_json_processing_dialog(self, text: str):
        """Show method-choice dialog pre-set to SSDS-JSON, then parse."""
        dlg = ImageProcessingDialog(self, input_type="json")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._process_json_palette(text)

    def _show_text_format_dialog(self, text: str):
        """Prompt for the CSV text format, then load the colors into recent."""
        dlg = TextFormatDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fmt = dlg.fmt()
        if fmt == "csv_rgba_step":
            pairs = _parse_csv_dec_rgba_step(text)
            if not pairs:
                QMessageBox.information(
                    self, "CSV-DEC-RGBA-step — No Data Found",
                    "No color rows were found.\n\n"
                    "Expected one color per line:\n"
                    "  red,green,blue,alpha,step\n\n"
                    "Channels are decimal 0-255; step is a float that may end\n"
                    "in 'f'.  A trailing comma is allowed, e.g.  1,2,3,4,5.0f,",
                )
                return
            self.recent.clear_all()
            for color, stop in pairs:
                self.recent.add(color, stop_value=stop)
            self.recent.show_stop_column()
        elif fmt == "android_gradient1":
            pairs = _parse_android_gradient(text)
            if not pairs:
                QMessageBox.information(
                    self, "Android:Gradient1 — No Data Found",
                    "No gradient items were found.\n\n"
                    "Expected one item per line, e.g.:\n"
                    '  <item android:offset="0.0" android:color="#FF63EB63"/>\n\n'
                    "The color hex may be 3, 4, 6, or 8 digits (Android is\n"
                    "alpha-first: A,R,G,B for 4/8-digit; 3/6-digit have no\n"
                    "alpha).  Offset is the stop position from 0.0 to 1.0.",
                )
                return
            self.recent.clear_all()
            for color, stop in pairs:
                self.recent.add(color, stop_value=stop)
            self.recent.show_stop_column()
        elif fmt == "hex_argb":
            colors = _parse_hex_argb(text)
            if not colors:
                QMessageBox.information(
                    self, "Hex:ARGB — No Data Found",
                    "No color rows were found.\n\n"
                    "Expected one hex color per line, alpha-first:\n"
                    "  #AARRGGBB\n\n"
                    "The leading '#' is optional and the hex may be 3, 4, 6,\n"
                    "or 8 digits (4/8-digit are A,R,G,B; 3/6-digit have no\n"
                    "alpha).  Example:  #FF3B0A8A",
                )
                return
            self.recent.clear_all()
            for color in colors:
                self.recent.add(color)
        else:  # csv_rgba
            colors = _parse_csv_dec_rgba(text)
            if not colors:
                QMessageBox.information(
                    self, "CSV-DEC-RGBA — No Data Found",
                    "No color rows were found.\n\n"
                    "Expected one color per line:\n"
                    "  red,green,blue,alpha\n\n"
                    "Channels are decimal 0-255.  A trailing comma is allowed,\n"
                    "e.g.  255,128,0,255,",
                )
                return
            self.recent.clear_all()
            for color in colors:
                self.recent.add(color)

    def _process_json_palette(self, text: str):
        pairs = _parse_json_palette(text)
        if not pairs:
            QMessageBox.information(
                self, "SSDS-JSON Palette — No Data Found",
                "No color steps were found in the JSON.\n\n"
                "Expected path:  Palettes → Palette → ColorList → ColorStep[]\n"
                "Each entry needs a \"Step\" field and an \"ARGB\" field\n"
                "containing four comma-separated decimal values (A,R,G,B).",
            )
            return
        self.recent.clear_all()
        for color, stop in pairs:
            self.recent.add(color, stop_value=stop)
        self.recent.show_stop_column()

    def _ocr_with_error_dialog(self, image: QImage) -> str | None:
        """Run OCR on image; show appropriate error dialogs and return None on failure."""
        try:
            return _ocr_qimage(image)
        except ImportError:
            QMessageBox.warning(
                self, "Missing OCR Dependencies",
                "OCR palette processing requires Pillow and pytesseract.\n\n"
                "Install with:\n  pip install pillow pytesseract\n\n"
                "Also ensure Tesseract is installed on your system:\n"
                "  macOS:   brew install tesseract\n"
                "  Linux:   apt install tesseract-ocr",
            )
            return None
        except Exception as exc:
            QMessageBox.warning(
                self, "OCR Failed",
                f"Could not extract text from the image:\n\n{exc}",
            )
            return None

    def _process_image(self, image: QImage, method: str = "qt_index", n_colors: int = 256):
        self.box.setImage(QPixmap.fromImage(image))
        self.recent.clear_all()

        if method == "histogram":
            for color in _extract_palette_histogram(image, max_colors=n_colors):
                self.recent.add(color)

        elif method == "ssds":
            text = self._ocr_with_error_dialog(image)
            if text is None:
                return
            pairs = _parse_ssds_text(text)
            if not pairs:
                QMessageBox.information(
                    self, "SSDS Palette — No Data Found",
                    "No gradient stop entries were found in the image.\n\n"
                    "Expected keywords: Step:  A:  R:  G:  B:\n\n"
                    "Raw OCR text:\n" + text[:600],
                )
                return
            for color, stop in pairs:
                self.recent.add(color, stop_value=stop)
            self.recent.show_stop_column()

        elif method == "pangea":
            text = self._ocr_with_error_dialog(image)
            if text is None:
                return
            pairs = _parse_pangea_text(text)
            if not pairs:
                QMessageBox.information(
                    self, "Pangea Palette — No Data Found",
                    "No color rows were found in the image.\n\n"
                    "Expected row format:  <step>  <description>  <R>,<G>,<B>,<A>\n\n"
                    "Raw OCR text:\n" + text[:600],
                )
                return
            for color, stop in pairs:
                self.recent.add(color, stop_value=stop)
            self.recent.show_stop_column()

        else:  # "qt_index" (default)
            for color in _extract_palette(image, max_colors=256):
                self.recent.add(color)

    def _on_recent_activated(self, color: QColor):
        self._apply_color(color, source="recent")
        # Highlight the selected stop on the graph with a colored crosshair.
        self._graph_panel.set_selected_index(self.recent.selected_stop_index())

    def _apply_unit_conversion(self, dim: str, from_unit: str, to_unit: str):
        """Convert every Recent-list stop value from ``from_unit`` to ``to_unit``."""
        fn = _make_unit_converter(dim, from_unit, to_unit)
        converted = self.recent.apply_stop_transform(fn)
        if converted == 0:
            QMessageBox.information(
                self, "Unit Conversion — No Stop Values",
                "There are no gradient stop values in the Recent list to "
                "convert.\n\nStop values come from SSDS / Pangea / JSON palette "
                "processing or the CSV-DEC-RGBA-step paste format.",
            )
            return
        # Make sure the converted values are visible (apply_stop_transform
        # already emitted listChanged, refreshing the graph).
        self.recent.show_stop_column()

    def _simplify_gradient(self):
        """Drop intermediate gradient stops, keeping the color inflections."""
        pairs = self.recent.stop_data()
        if len(pairs) < 3:
            QMessageBox.information(
                self, "Simplify Gradient — Not Enough Stops",
                "Simplifying needs at least 3 gradient stops in the Recent "
                "list.\n\nStop values come from SSDS / Pangea / JSON / Android "
                "gradient palette processing or the CSV-DEC-RGBA-step paste "
                "format.",
            )
            return
        tol, ok = QInputDialog.getDouble(
            self, "Simplify Gradient",
            f"Gradient has {len(pairs)} stops.\n\n"
            "Color tolerance (0-510 Euclidean RGBA distance; higher removes "
            "more stops):",
            12.0, 0.0, 510.0, 1,
        )
        if not ok:
            return
        simplified = _simplify_gradient_stops(pairs, tol)
        self.recent.clear_all()
        for color, stop in simplified:
            self.recent.add(color, stop_value=stop)
        self.recent.show_stop_column()
        removed = len(pairs) - len(simplified)
        QMessageBox.information(
            self, "Simplify Gradient",
            f"Kept {len(simplified)} of {len(pairs)} stops "
            f"({removed} removed).",
        )

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

    def _on_recent_list_changed(self):
        self._graph_panel.update_from_recent(self.recent)
        has = self._graph_panel.has_data()
        if has and not self._graph_panel_user_hidden:
            if not self._graph_panel.isVisible():
                self._graph_panel.setVisible(True)
                self.graph_btn.setChecked(True)
            if not self._graph_panel.is_expanded():
                self._graph_panel.expand()
        elif not has and self._graph_panel.isVisible():
            self._graph_panel.setVisible(False)
            self.graph_btn.setChecked(False)

    def _on_graph_btn_toggled(self, checked: bool):
        self._graph_panel_user_hidden = not checked
        self._graph_panel.setVisible(checked)


def main():
    app = QApplication(sys.argv)
    QApplication.setOrganizationName(SETTINGS_ORG)
    QApplication.setApplicationName(SETTINGS_APP)
    # Apply persisted theme before any windows are created so there's no
    # flash of the default style.
    theme = QSettings(SETTINGS_ORG, SETTINGS_APP).value(
        "theme", DEFAULT_THEME, type=str
    )
    if theme not in ("Light", "Dark"):
        theme = DEFAULT_THEME
    _apply_theme(theme)
    icon_path = Path(__file__).parent / "color-icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
