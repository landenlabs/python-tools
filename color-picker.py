#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Qt color picker with hue/saturation wheel and R/G/B/A inputs (decimal + hex)."""

from __future__ import annotations

import math
import sys

from PyQt6.QtCore import Qt, QPoint, QRect, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QIntValidator,
    QPainter,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


WHEEL_SIZE = 260
SWATCH_SIZE = 260
WINDOW_TITLE = "Color Picker"
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

    def setColor(self, color: QColor):
        self._color = QColor(color)
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
    cursorMoved = pyqtSignal(QPoint)
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
        self.cursorMoved.emit(event.globalPosition().toPoint())
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
    cursorMoved = pyqtSignal(QPoint)
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
            overlay.cursorMoved.connect(self.cursorMoved)
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

        self.wheel = ColorWheel()
        self.box = ColorBox()

        self.dup_btn = QPushButton("Dup Picker")
        self.dup_btn.setToolTip(
            "Open another color-picker window initialized to the current color."
        )
        self.dup_btn.clicked.connect(self._duplicate_window)

        self.pick_btn = QPushButton("Pick from Screen")
        self.pick_btn.setToolTip(
            "Click, then click anywhere on screen to sample pixels.\n"
            "Default: multiple picks allowed; press Esc to finish.\n"
            "macOS: requires Screen Recording permission to sample other apps."
        )
        self.pick_btn.clicked.connect(self._start_screen_pick)
        self._screen_picker = None
        self._auto_hide_mode = False
        self._pick_app_rect: QRect | None = None
        self._pick_saved_geom = None  # QByteArray from saveGeometry()

        self.auto_hide_cb = QCheckBox("Auto-hide app while picking")
        self.auto_hide_cb.setToolTip(
            "When checked: hide this window during pick, sample a single "
            "color, then restore the window."
        )

        self.cursor_hide_cb = QCheckBox("Hide when cursor is over app")
        self.cursor_hide_cb.setToolTip(
            "During multi-pick, automatically hide this window whenever "
            "the cursor moves over its area, and re-show it when the cursor "
            "leaves. Off by default."
        )

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.wheel, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addSpacing(16)
        top.addWidget(self.box, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.dup_btn)
        buttons_row.addSpacing(8)
        buttons_row.addWidget(self.pick_btn)
        buttons_row.addStretch(1)

        options_row = QHBoxLayout()
        options_row.addStretch(1)
        options_row.addWidget(self.auto_hide_cb)
        options_row.addSpacing(12)
        options_row.addWidget(self.cursor_hide_cb)
        options_row.addStretch(1)

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
        hex_row = QHBoxLayout()
        hex_row.addStretch(1)
        hex_row.addWidget(hex_label)
        hex_row.addWidget(self.hex_all)
        hex_row.addStretch(1)

        central = QWidget()
        v = QVBoxLayout(central)
        v.addWidget(title)
        v.addLayout(top)
        v.addSpacing(8)
        v.addLayout(buttons_row)
        v.addSpacing(4)
        v.addLayout(options_row)
        v.addSpacing(8)
        v.addWidget(self.r_row)
        v.addWidget(self.g_row)
        v.addWidget(self.b_row)
        v.addWidget(self.a_row)
        v.addSpacing(4)
        v.addLayout(hex_row)
        v.addStretch(1)
        self.setCentralWidget(central)

        self.r_row.valueChanged.connect(self._from_channels)
        self.g_row.valueChanged.connect(self._from_channels)
        self.b_row.valueChanged.connect(self._from_channels)
        self.a_row.valueChanged.connect(self._from_channels)
        self.wheel.colorPicked.connect(self._from_wheel)
        self.hex_all.editingFinished.connect(self._from_hex_all)

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
            self.hex_all.setText(
                f"{self._color.red():02X}{self._color.green():02X}"
                f"{self._color.blue():02X}{self._color.alpha():02X}"
            )
        self.box.setColor(self._color)
        self._guard = False

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
        if not self._auto_hide_mode:
            self._pick_app_rect = self.frameGeometry()
        # always hide before the screenshot so our window pixels aren't
        # captured into the overlay's snapshot
        self.hide()
        QTimer.singleShot(200, self._launch_screen_picker)

    def _launch_screen_picker(self):
        multi = not self._auto_hide_mode
        self._screen_picker = ScreenPicker(self, multi=multi)
        self._screen_picker.colorPicked.connect(self._on_screen_picked)
        self._screen_picker.cursorPreview.connect(self.box.setPreview)
        self._screen_picker.cursorMoved.connect(self._on_overlay_cursor_move)
        self._screen_picker.cancelled.connect(self._on_screen_cancelled)
        self._screen_picker.start()
        if multi:
            self.setWindowTitle(PICKING_TITLE)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            cursor_hide = self.cursor_hide_cb.isChecked()
            if not cursor_hide or not self._pick_app_rect.contains(QCursor.pos()):
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

    def _on_overlay_cursor_move(self, global_pos: QPoint):
        if self._pick_app_rect is None or not self.cursor_hide_cb.isChecked():
            return
        over_app = self._pick_app_rect.contains(global_pos)
        if over_app and self.isVisible():
            self.hide()
        elif not over_app and not self.isVisible():
            self._show_during_pick()

    def enterEvent(self, event):
        if (self._pick_app_rect is not None
            and self.cursor_hide_cb.isChecked()
            and self.isVisible()):
            self.hide()
        super().enterEvent(event)

    def _duplicate_window(self):
        child = MainWindow(initial_color=self._color)
        MainWindow._windows.append(child)
        # offset slightly so the new window isn't directly on top of this one
        geo = self.frameGeometry()
        child.move(geo.x() + 40, geo.y() + 40)
        child.show()

    def moveEvent(self, event):
        if self._pick_app_rect is not None and self.isVisible():
            self._pick_app_rect = self.frameGeometry()
        super().moveEvent(event)

    def resizeEvent(self, event):
        if self._pick_app_rect is not None and self.isVisible():
            self._pick_app_rect = self.frameGeometry()
        super().resizeEvent(event)

    def _on_screen_picked(self, color: QColor):
        color.setAlpha(self._color.alpha())
        self._apply_color(color, source="screen")
        if self._auto_hide_mode:
            self.box.clearPreview()
            self._restore_window()
        # multi mode: leave overlays up, await further picks or Esc

    def _on_screen_cancelled(self):
        self.box.clearPreview()
        if self._auto_hide_mode:
            self._restore_window()
        else:
            self.setWindowTitle(WINDOW_TITLE)
            self._pick_app_rect = None
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
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
            a = int(text[6:8], 16)
        except ValueError:
            return
        self._apply_color(QColor(r, g, b, a), source="hex_all")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
