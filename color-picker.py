#!/usr/bin/env python3
"""Qt color picker with hue/saturation wheel and R/G/B/A inputs (decimal + hex)."""

import math
import sys

from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import (
    QColor,
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
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


WHEEL_SIZE = 260
SWATCH_SIZE = 260


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
    """Solid swatch of the current color, drawn over a checkerboard for alpha."""

    def __init__(self, size=SWATCH_SIZE, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._color = QColor(255, 0, 0, 255)

    def setColor(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        rect = self.contentsRect()
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Color Picker")
        self._guard = False
        self._color = QColor(255, 0, 0, 255)

        title = QLabel("Color Picker")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)

        self.wheel = ColorWheel()
        self.box = ColorBox()

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.wheel)
        top.addSpacing(16)
        top.addWidget(self.box)
        top.addStretch(1)

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
