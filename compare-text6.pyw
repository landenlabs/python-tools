#!/usr/bin/env python3
"""
compare_tool.py — Side-by-side text comparison with LCS alignment.

Usage:
    python compare_tool.py [left_file] [right_file]

Features:
  • LCS-based auto-alignment (ignores whitespace & non-alphanumeric chars)
  • Manual shift (↑/↓) for left or right panel independently
  • Multi-select rows: Ctrl+click toggle, Shift+click range
  • Right-click: delete block (selected blank rows), insert N blanks for N selected rows
  • Right-click (cross-panel): Compare — word-level diff highlight on two selected rows
  • Right-click (cross-panel): Sync — insert blanks so both selected rows align vertically
  • Toolbar +/- blank row buttons act on the selected row
  • Synchronized vertical scrolling
  • Color-coded rows: green=match, yellow=different, red=left-only, blue=right-only
  • Jump to next/previous difference
  • Paste text directly (no file required)
  • Match statistics in status bar
"""

from __future__ import annotations
import os
import sys
import re

# Hide the console window on Windows when launched with python.exe
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

import argparse
import difflib
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QToolBar, QFileDialog, QScrollArea,
    QSizePolicy, QLabel, QMenu, QMessageBox, QDialog,
    QPlainTextEdit, QDialogButtonBox, QLineEdit, QPushButton, QCheckBox,
    QTabWidget, QFormLayout, QSpinBox, QFontComboBox,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRect, QPoint, QSettings
from PyQt6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QImageReader, QKeySequence,
    QMovie, QPainter, QPixmap,
)


# ── Application metadata (shown in Settings ▸ About) ───────────────────────────

APP_NAME    = "CompareTool"
APP_ORG     = "compare-tool"
VERSION     = "6.0"
AUTHOR      = "Dennis Lang"
GITHUB_URL  = "https://github.com/landenlabs/compare-tool"
LICENSE     = "MIT"
ATTRIBUTION = "Built with PyQt6.  Alignment uses Python's difflib (LCS)."


# ── Layout constants ──────────────────────────────────────────────────────────

BASE_ROW_H      = 16   # pixels per row at 100% zoom (tight vertical padding)
BASE_LINE_NUM_W = 52   # line-number gutter width at 100% zoom
BASE_FONT_SIZE  = 9    # font point size at 100% zoom
TEXT_PAD        = 6    # horizontal padding for text (does not scale)

FONT_FAMILY_DEFAULT = "Courier New"
FONT_BOLD_DEFAULT   = True

ZOOM_LEVELS = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200]


# ── Appearance settings (persisted via QSettings) ──────────────────────────────

@dataclass
class Appearance:
    """User-tunable viewer appearance; persisted across runs."""
    font_family: str  = FONT_FAMILY_DEFAULT
    font_bold:   bool = FONT_BOLD_DEFAULT
    font_size:   int  = BASE_FONT_SIZE   # base point size at 100% zoom
    row_height:  int  = BASE_ROW_H       # base row pixels at 100% zoom


def load_appearance() -> Appearance:
    s = QSettings(APP_ORG, APP_NAME)
    d = Appearance()
    return Appearance(
        font_family=s.value("appearance/font_family", d.font_family, type=str),
        font_bold=  s.value("appearance/font_bold",   d.font_bold,   type=bool),
        font_size=  s.value("appearance/font_size",   d.font_size,   type=int),
        row_height= s.value("appearance/row_height",  d.row_height,  type=int),
    )


def save_appearance(a: Appearance) -> None:
    s = QSettings(APP_ORG, APP_NAME)
    s.setValue("appearance/font_family", a.font_family)
    s.setValue("appearance/font_bold",   a.font_bold)
    s.setValue("appearance/font_size",   a.font_size)
    s.setValue("appearance/row_height",  a.row_height)

# Background colours per status
BG: dict[str, QColor] = {
    'equal':   QColor(210, 245, 210),  # green  – lines match
    'replace': QColor(255, 253, 180),  # yellow – both present but differ
    'delete':  QColor(255, 208, 208),  # red    – left side only
    'insert':  QColor(208, 208, 255),  # blue   – right side only
    'blank':   QColor(245, 245, 245),  # grey   – both sides blank
}
GUTTER_DIM        = 112                       # QColor.darker() arg for gutter
WORD_DIFF_BG      = QColor(255, 140, 0, 210)  # orange overlay for non-matching words
PARTIAL_MATCH_BG  = QColor( 80, 200,  80, 170) # green overlay for partial-match spans


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()


def make_key_fn(pattern_str: str):
    if not pattern_str.strip():
        return None
    try:
        pat = re.compile(pattern_str)
    except re.error:
        return None
    if pat.groups == 0:
        return None
    def _key(line: str) -> str:
        m = pat.match(line)
        if not m:
            return normalize(line)
        return ''.join(g for g in m.groups() if g is not None)
    return _key


def lcs_align(left_lines: list[str], right_lines: list[str],
              left_key=None, right_key=None):
    lk = [left_key(l)  if left_key  else normalize(l) for l in left_lines]
    rk = [right_key(r) if right_key else normalize(r) for r in right_lines]
    sm = difflib.SequenceMatcher(None, lk, rk, autojunk=False)
    left_out: list = []
    right_out: list = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        lc = left_lines[i1:i2]
        rc = right_lines[j1:j2]
        for i in range(max(len(lc), len(rc))):
            left_out.append(lc[i] if i < len(lc) else None)
            right_out.append(rc[i] if i < len(rc) else None)
    return left_out, right_out


def row_status(l, r, left_key=None, right_key=None) -> str:
    if l is None and r is None:
        return 'blank'
    if l is None:
        return 'insert'
    if r is None:
        return 'delete'
    lk = left_key(l)  if left_key  else normalize(l)
    rk = right_key(r) if right_key else normalize(r)
    return 'equal' if lk == rk else 'replace'


def compute_word_diff(left_text: str, right_text: str
                      ) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Word-level diff; returns (left_diff, right_diff) as lists of (word, is_match)."""
    lw = left_text.split()
    rw = right_text.split()
    sm = difflib.SequenceMatcher(None, lw, rw, autojunk=False)
    l_diff: list[tuple[str, bool]] = []
    r_diff: list[tuple[str, bool]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        eq = (tag == 'equal')
        for w in lw[i1:i2]:
            l_diff.append((w, eq))
        for w in rw[j1:j2]:
            r_diff.append((w, eq))
    return l_diff, r_diff


def find_partial_matches(
    s1: str, s2: str, min_len: int = 3
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """
    Iteratively find the longest common substrings between s1 and s2, greedy
    from longest to shortest, never re-using already-matched character positions.

    Returns (spans1, spans2) where each entry is a (start, end_exclusive) range
    of character indices in the respective string.  Only spans with
    len >= min_len are returned.
    """
    n, m = len(s1), len(s2)
    if n == 0 or m == 0:
        return [], []

    used1 = [False] * n
    used2 = [False] * m
    spans1: list[tuple[int, int]] = []
    spans2: list[tuple[int, int]] = []

    while True:
        best_len = min_len - 1
        best_ei = best_ej = 0          # 1-based end positions of current best

        # Two-row rolling DP for longest common substring, ignoring used positions.
        # curr[j+1] = length of common substring ending at s1[i], s2[j].
        prev = [0] * (m + 1)
        for i in range(n):
            curr = [0] * (m + 1)
            if not used1[i]:
                for j in range(m):
                    if not used2[j] and s1[i] == s2[j]:
                        v = prev[j] + 1   # extend diagonal
                        curr[j + 1] = v
                        if v > best_len:
                            best_len = v
                            best_ei  = i + 1
                            best_ej  = j + 1
            prev = curr

        if best_len < min_len:
            break

        s1_start = best_ei - best_len
        s2_start = best_ej - best_len
        spans1.append((s1_start, best_ei))
        spans2.append((s2_start, best_ej))
        for k in range(best_len):
            used1[s1_start + k] = True
            used2[s2_start + k] = True

    return spans1, spans2


# ── Panel widget ──────────────────────────────────────────────────────────────

class PanelWidget(QWidget):
    """
    Custom-painted list of text rows for one side of the comparison.

    Row tuples are (text_or_None, status) or (text_or_None, status, word_diff)
    where word_diff is a list of (word, is_match) injected by the compare action.

    Multi-select: Ctrl+click toggles, Shift+click extends range.
    selected       — anchor / primary row (used by toolbar ops and cross-panel actions)
    selected_rows  — full set of selected row indices
    """

    rowClicked           = pyqtSignal(int)
    contextMenuRequested = pyqtSignal(int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple] = []
        self.selected      = -1
        self.selected_rows: set[int] = set()
        self.hovered       = -1
        # appearance (overridable via apply_appearance)
        self._family         = FONT_FAMILY_DEFAULT
        self._bold           = FONT_BOLD_DEFAULT
        self._base_font_size = BASE_FONT_SIZE
        self._base_row_h     = BASE_ROW_H
        self._scale          = 1.0
        self._row_h      = self._base_row_h
        self._line_num_w = BASE_LINE_NUM_W
        self._font = self._make_font(self._base_font_size)
        self._fm   = QFontMetrics(self._font)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _make_font(self, size: int) -> QFont:
        f = QFont(self._family, max(6, size))
        f.setBold(self._bold)
        return f

    # ── Public API ────────────────────────────────────────────────────────────

    def set_rows(self, rows: list[tuple]):
        self.rows = rows
        self.selected = -1
        self.selected_rows = set()
        self.setFixedHeight(max(len(rows) * self._row_h, 1))
        self.update()

    def set_font_scale(self, scale: float):
        self._scale      = scale
        size             = max(6, round(self._base_font_size * scale))
        self._font       = self._make_font(size)
        self._fm         = QFontMetrics(self._font)
        self._row_h      = max(10, round(self._base_row_h * scale))
        self._line_num_w = max(30, round(BASE_LINE_NUM_W * scale))
        self.setFixedHeight(max(len(self.rows) * self._row_h, 1))
        self.update()

    def apply_appearance(self, a: Appearance):
        self._family         = a.font_family
        self._bold           = a.font_bold
        self._base_font_size = a.font_size
        self._base_row_h     = a.row_height
        self.set_font_scale(self._scale)

    # ── Painting ──────────────────────────────────────────────────────────────

    def sizeHint(self):
        return QSize(400, max(len(self.rows) * self._row_h, 1))

    def paintEvent(self, event):
        if not self.rows:
            return
        p = QPainter(self)
        p.setFont(self._font)

        clip = event.rect()
        r0 = max(0, clip.top() // self._row_h)
        r1 = min(len(self.rows), clip.bottom() // self._row_h + 2)

        lnums: list = []
        n = 0
        for row_data in self.rows:
            if row_data[0] is not None:
                n += 1
                lnums.append(n)
            else:
                lnums.append(None)

        W = self.width()

        for i in range(r0, r1):
            row_data      = self.rows[i]
            txt           = row_data[0]
            status        = row_data[1]
            diff_words    = row_data[2] if len(row_data) > 2 else None
            partial_spans = row_data[3] if len(row_data) > 3 else None
            y   = i * self._row_h
            rh  = self._row_h
            lnw = self._line_num_w

            base = BG.get(status, QColor(255, 255, 255))
            if i == self.selected:
                bg = base.darker(130)      # primary / anchor
            elif i in self.selected_rows:
                bg = base.darker(122)      # rest of multi-selection
            elif i == self.hovered:
                bg = base.darker(108)
            else:
                bg = base

            p.fillRect(0, y, W, rh, bg)
            p.fillRect(0, y, lnw, rh, bg.darker(GUTTER_DIM))

            if lnums[i] is not None:
                p.setPen(QColor(105, 105, 130))
                p.drawText(
                    QRect(2, y, lnw - 4, rh),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(lnums[i]),
                )

            p.setPen(QColor(170, 170, 200))
            p.drawLine(lnw, y, lnw, y + rh)

            if txt is not None:
                if diff_words:
                    # word-level diff overlay (from right-click Compare action)
                    x = lnw + TEXT_PAD
                    for word, is_match in diff_words:
                        w_str = word + ' '
                        w_w   = self._fm.horizontalAdvance(w_str)
                        if not is_match:
                            p.fillRect(x, y + 2, w_w - 2, rh - 4, WORD_DIFF_BG)
                        p.setPen(QColor(15, 15, 15))
                        p.drawText(
                            QRect(x, y, w_w, rh),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            w_str,
                        )
                        x += w_w
                elif partial_spans:
                    # character-span partial-match highlighting
                    matched = [False] * len(txt)
                    for s, e in partial_spans:
                        matched[s:e] = [True] * (e - s)
                    x = lnw + TEXT_PAD
                    ci = 0
                    while ci < len(txt):
                        is_hit = matched[ci]
                        cj = ci + 1
                        while cj < len(txt) and matched[cj] == is_hit:
                            cj += 1
                        chunk  = txt[ci:cj]
                        cw     = self._fm.horizontalAdvance(chunk)
                        if is_hit:
                            p.fillRect(x, y + 1, cw, rh - 2, PARTIAL_MATCH_BG)
                        p.setPen(QColor(15, 15, 15))
                        p.drawText(
                            QRect(x, y, cw, rh),
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            chunk,
                        )
                        x  += cw
                        ci  = cj
                else:
                    p.setPen(QColor(15, 15, 15))
                    p.drawText(
                        QRect(lnw + TEXT_PAD, y,
                              W - lnw - TEXT_PAD * 2, rh),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        txt,
                    )

            p.setPen(QColor(205, 205, 205))
            p.drawLine(0, y + rh - 1, W, y + rh - 1)

        p.end()

    # ── Mouse & keyboard ──────────────────────────────────────────────────────

    def _row_at(self, pos) -> int:
        r = pos.y() // self._row_h
        return r if 0 <= r < len(self.rows) else -1

    def mouseMoveEvent(self, event):
        r = self._row_at(event.pos())
        if r != self.hovered:
            self.hovered = r
            self.update()

    def leaveEvent(self, event):
        if self.hovered != -1:
            self.hovered = -1
            self.update()

    def mousePressEvent(self, event):
        r = self._row_at(event.pos())
        if r < 0:
            return
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if r in self.selected_rows:
                self.selected_rows.discard(r)
                if self.selected == r:
                    self.selected = max(self.selected_rows) if self.selected_rows else -1
            else:
                self.selected_rows.add(r)
                self.selected = r
        elif mods & Qt.KeyboardModifier.ShiftModifier and self.selected >= 0:
            lo, hi = sorted([self.selected, r])
            self.selected_rows = set(range(lo, hi + 1))
            # keep self.selected as the anchor
        else:
            self.selected_rows = {r}
            self.selected = r
        self.rowClicked.emit(r)
        self.setFocus()
        self.update()

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Up and self.selected > 0:
            new_r = self.selected - 1
            if mods & Qt.KeyboardModifier.ShiftModifier:
                if new_r in self.selected_rows:
                    self.selected_rows.discard(self.selected)
                else:
                    self.selected_rows.add(new_r)
            else:
                self.selected_rows = {new_r}
            self.selected = new_r
            self.rowClicked.emit(self.selected)
            self.update()
        elif key == Qt.Key.Key_Down and self.selected < len(self.rows) - 1:
            new_r = self.selected + 1
            if mods & Qt.KeyboardModifier.ShiftModifier:
                if new_r in self.selected_rows:
                    self.selected_rows.discard(self.selected)
                else:
                    self.selected_rows.add(new_r)
            else:
                self.selected_rows = {new_r}
            self.selected = new_r
            self.rowClicked.emit(self.selected)
            self.update()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        r = self._row_at(event.pos())
        if r < 0:
            return
        if r not in self.selected_rows:
            self.selected_rows = {r}
            self.selected = r
            self.rowClicked.emit(r)
            self.update()
        self.contextMenuRequested.emit(r, event.globalPos())


# ── Synchronised scroll area ──────────────────────────────────────────────────

class SyncScrollArea(QScrollArea):
    def __init__(self, panel: PanelWidget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.panel = panel
        self.setWidget(panel)
        self._partner: 'SyncScrollArea | None' = None
        self._busy = False
        self.verticalScrollBar().valueChanged.connect(self._on_vscroll)

    def set_partner(self, other: 'SyncScrollArea'):
        self._partner = other

    def _on_vscroll(self, val: int):
        if self._partner and not self._busy:
            self._busy = True
            self._partner.verticalScrollBar().setValue(val)
            self._busy = False


# ── Clickable panel-title (pulldown menu) ──────────────────────────────────────

TITLE_STYLE = (
    "QLabel {"
    "  color:#dde6f0; padding:0 10px;"
    "  font-weight:bold; font-size:11px;"
    "}"
    "QLabel:hover { background:#2c5288; }"
    "QToolTip {"
    "  color:#ffffff; background-color:#2c4a70;"
    "  border:1px solid #1e3a5f; padding:3px;"
    "}"
)


class TitleLabel(QLabel):
    """Panel title that behaves like a pulldown menu button.

    Displays ``<name>  ▾``; the tooltip shows the full path.  Either mouse
    button pops a menu anchored beneath the label (handled by the caller via
    the ``menuRequested`` signal).  When no file is loaded it shows ``prompt``.
    """

    menuRequested = pyqtSignal(QPoint)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_file("", "")

    def set_file(self, name: str, full_path: str):
        display = name if name else self._prompt
        self.setText(f"{display}  ▾")
        self.setToolTip(full_path if full_path else "No file loaded — click to open")

    def mousePressEvent(self, event):
        self.menuRequested.emit(self.mapToGlobal(QPoint(0, self.height())))
        event.accept()


# ── Paste-text dialog ─────────────────────────────────────────────────────────

class PasteDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 500)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Courier New", 9))
        self.edit.setPlaceholderText("Paste or type text here …")
        lay.addWidget(QLabel("Enter text (one item per line):"))
        lay.addWidget(self.edit)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def lines(self) -> list[str]:
        return self.edit.toPlainText().splitlines()


# ── About dialog helpers ──────────────────────────────────────────────────────

_ABOUT_DIALOG_WIDTH = 420
_ANIM_MAX_W = _ABOUT_DIALOG_WIDTH - 32


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


def _animation_path() -> Path:
    return Path(__file__).parent / "screens" / "landenlabs_400.webp"


def _animation_display_size(path: Path) -> QSize:
    """Return display size that preserves the animation's native aspect ratio."""
    native = QImageReader(str(path)).size()
    if not native.isValid() or native.width() == 0:
        return QSize(_ANIM_MAX_W, _ANIM_MAX_W)
    scale = min(1.0, _ANIM_MAX_W / native.width())
    return QSize(int(native.width() * scale), int(native.height() * scale))


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Tabbed settings: viewer Appearance (live-previewed) and About info.

    Emits ``appearanceChanged`` whenever a control changes so the caller can
    preview live; the final value is read via ``current_appearance()`` on accept.
    """

    appearanceChanged = pyqtSignal(object)   # emits an Appearance

    def __init__(self, appearance: Appearance, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(460, 380)

        # Animation state (used by About tab)
        self._movie: QMovie | None = None
        self._anim_label: QLabel | None = None
        self._anim_final_pixmap: QPixmap | None = None
        self._last_anim_frame: int = -1

        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_appearance_tab(appearance), "Appearance")
        tabs.addTab(self._build_about_tab(), "About")
        tabs.currentChanged.connect(self._on_tab_changed)
        lay.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults)
        lay.addWidget(btns)

    # ── Appearance tab ──────────────────────────────────────────────────────────

    def _build_appearance_tab(self, a: Appearance) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._family_combo = QFontComboBox()
        self._family_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self._family_combo.setCurrentFont(QFont(a.font_family))

        self._bold_cb = QCheckBox("Bold")
        self._bold_cb.setChecked(a.font_bold)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 32)
        self._size_spin.setSuffix(" pt")
        self._size_spin.setValue(a.font_size)

        self._row_spin = QSpinBox()
        self._row_spin.setRange(10, 48)
        self._row_spin.setSuffix(" px")
        self._row_spin.setValue(a.row_height)

        form.addRow("Font family:", self._family_combo)
        form.addRow("",            self._bold_cb)
        form.addRow("Font size:",  self._size_spin)
        form.addRow("Row height:", self._row_spin)

        self._family_combo.currentFontChanged.connect(self._on_changed)
        self._bold_cb.toggled.connect(self._on_changed)
        self._size_spin.valueChanged.connect(self._on_changed)
        self._row_spin.valueChanged.connect(self._on_changed)
        return w

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # Animated logo (plays once, then freezes on the last frame).
        anim_path = _animation_path()
        if anim_path.exists():
            display_size = _animation_display_size(anim_path)
            self._anim_label = QLabel()
            self._anim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._anim_label.setFixedSize(display_size)
            self._movie = QMovie(str(anim_path))
            self._movie.setScaledSize(display_size)
            self._anim_label.setMovie(self._movie)
            self._movie.frameChanged.connect(self._on_anim_frame_changed)
            root.addWidget(self._anim_label, alignment=Qt.AlignmentFlag.AlignCenter)

        name_font = QFont()
        name_font.setPointSize(15)
        name_font.setBold(True)
        name_lbl = QLabel("Compare Tool")
        name_lbl.setFont(name_font)
        root.addWidget(name_lbl)

        desc = QLabel(
            f"v{VERSION}  —  Side-by-side text comparison with LCS alignment."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addSpacing(4)

        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow(_bold_label("Author:"), QLabel(AUTHOR))
        form.addRow(_bold_label("Built:"),  QLabel(_build_date()))
        form.addRow(QLabel(""), QLabel("Created by LanDen Labs (2026)"))

        link = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.TextFormat.RichText)
        form.addRow(_bold_label("GitHub:"), link)

        form.addRow(_bold_label("License:"), QLabel(LICENSE))

        root.addLayout(form)
        root.addStretch()
        return w

    def _on_tab_changed(self, index: int):
        """Restart the animation whenever the About tab is shown."""
        if self._movie is None or self._anim_label is None:
            return
        # About tab is always index 1
        if index == 1:
            self._last_anim_frame = -1
            self._anim_final_pixmap = None
            # Re-attach movie in case it was replaced with a static pixmap
            self._anim_label.setMovie(self._movie)
            self._movie.start()
        else:
            self._movie.stop()

    def _on_anim_frame_changed(self, frame_num: int):
        """Play the animation once then freeze on the last frame."""
        if self._movie is None:
            return
        if frame_num == 0 and self._last_anim_frame > 0:
            self._movie.stop()
            if self._anim_final_pixmap is not None and self._anim_label is not None:
                self._anim_label.setMovie(None)
                self._anim_label.setPixmap(self._anim_final_pixmap)
            return
        self._anim_final_pixmap = self._movie.currentPixmap()
        self._last_anim_frame = frame_num

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _on_changed(self, *_):
        self.appearanceChanged.emit(self.current_appearance())

    def _restore_defaults(self):
        d = Appearance()
        self._family_combo.setCurrentFont(QFont(d.font_family))
        self._bold_cb.setChecked(d.font_bold)
        self._size_spin.setValue(d.font_size)
        self._row_spin.setValue(d.row_height)
        self._on_changed()

    def current_appearance(self) -> Appearance:
        return Appearance(
            font_family=self._family_combo.currentFont().family(),
            font_bold=self._bold_cb.isChecked(),
            font_size=self._size_spin.value(),
            row_height=self._row_spin.value(),
        )


# ── Main window ───────────────────────────────────────────────────────────────

class CompareWindow(QMainWindow):

    def __init__(self, left_path: str | None = None, right_path: str | None = None,
                 sort: bool = False):
        super().__init__()
        self.setWindowTitle("Side-by-Side Comparison")
        self.resize(1400, 900)

        self._left_source:  list[str] = []
        self._right_source: list[str] = []
        self._left_rows:  list = []
        self._right_rows: list = []
        self._zoom_idx = ZOOM_LEVELS.index(100)
        self._appearance = load_appearance()

        self._build_ui()
        self._build_toolbar()
        self._apply_appearance(self._appearance)

        if left_path:
            self._load_file('left',  left_path)
        if right_path:
            self._load_file('right', right_path)
        if sort:
            self._sort_panels()
        if left_path and right_path:
            self._auto_align()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet("background:#1e3a5f;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(1)
        self._left_title  = TitleLabel("Open Left")
        self._right_title = TitleLabel("Open Right")
        for lbl in (self._left_title, self._right_title):
            lbl.setStyleSheet(TITLE_STYLE)
            lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            hl.addWidget(lbl, 1)
        self._left_title.menuRequested.connect(
            lambda pos: self._on_title_menu('left', pos))
        self._right_title.menuRequested.connect(
            lambda pos: self._on_title_menu('right', pos))
        vbox.addWidget(hdr)

        self._left_panel  = PanelWidget()
        self._right_panel = PanelWidget()
        self._left_scroll  = SyncScrollArea(self._left_panel)
        self._right_scroll = SyncScrollArea(self._right_panel)
        self._left_scroll.set_partner(self._right_scroll)
        self._right_scroll.set_partner(self._left_scroll)

        self._left_regex_edit,  self._left_filter_btn  = self._make_regex_edit('left')
        self._right_regex_edit, self._right_filter_btn = self._make_regex_edit('right')

        left_container  = self._wrap_panel(
            self._left_regex_edit,  self._left_filter_btn,  self._left_scroll)
        right_container = self._wrap_panel(
            self._right_regex_edit, self._right_filter_btn, self._right_scroll)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(left_container)
        self._splitter.addWidget(right_container)
        self._splitter.setSizes([700, 700])
        vbox.addWidget(self._splitter, 1)

        self._left_panel.contextMenuRequested.connect(
            lambda r, pos: self._on_context_menu('left', r, pos))
        self._right_panel.contextMenuRequested.connect(
            lambda r, pos: self._on_context_menu('right', r, pos))

        bottom = QWidget()
        bottom.setFixedHeight(26)
        bottom.setStyleSheet("background:#f0f0f0; border-top:1px solid #ccc;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(8, 0, 8, 0)
        bl.setSpacing(12)
        for key, label in [
            ('equal',   'Match'),
            ('replace', 'Different'),
            ('delete',  'Left only'),
            ('insert',  'Right only'),
            ('blank',   'Blank'),
        ]:
            dot = QLabel()
            dot.setFixedSize(14, 14)
            dot.setStyleSheet(
                f"background:{BG[key].name()};"
                "border:1px solid #aaa; border-radius:2px;"
            )
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size:10px; color:#444;")
            bl.addWidget(dot)
            bl.addWidget(lbl)
        bl.addStretch()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("font-size:10px; color:#444;")
        bl.addWidget(self._status_lbl)

        # ── Partial-match checkbox ───────────────────────────────────────────
        bl.addSpacing(10)
        self._partial_match_cb = QCheckBox("Partial Match")
        self._partial_match_cb.setStyleSheet("font-size:10px; color:#444;")
        self._partial_match_cb.setToolTip(
            "On differing rows, highlight common substrings (length ≥ 3) "
            "shared between left and right text"
        )
        self._partial_match_cb.toggled.connect(self._refresh)
        bl.addWidget(self._partial_match_cb)

        # ── Font zoom control [ − 100% + ] ──────────────────────────────────
        bl.addSpacing(16)
        _zoom_btn_style = (
            "QPushButton {"
            "  font-size:14px; font-weight:bold;"
            "  padding:0 3px; min-width:20px; max-height:20px;"
            "  border:1px solid #bbb; border-radius:2px;"
            "  background:#e8e8e8; color:#333;"
            "}"
            "QPushButton:hover { background:#d0d0d0; }"
            "QPushButton:pressed { background:#b8b8b8; }"
            "QPushButton:disabled { color:#bbb; }"
        )
        zoom_minus = QPushButton("−")
        zoom_minus.setToolTip("Decrease font size")
        zoom_minus.setStyleSheet(_zoom_btn_style)
        zoom_minus.setFixedWidth(22)
        zoom_minus.clicked.connect(self._zoom_out)
        bl.addWidget(zoom_minus)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(40)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet("font-size:10px; color:#444; padding:0 2px;")
        bl.addWidget(self._zoom_label)

        zoom_plus = QPushButton("+")
        zoom_plus.setToolTip("Increase font size")
        zoom_plus.setStyleSheet(_zoom_btn_style)
        zoom_plus.setFixedWidth(22)
        zoom_plus.clicked.connect(self._zoom_in)
        bl.addWidget(zoom_plus)

        self._zoom_minus_btn = zoom_minus
        self._zoom_plus_btn  = zoom_plus

        vbox.addWidget(bottom)

    def _make_regex_edit(self, side: str) -> tuple:
        edit = QLineEdit()
        edit.setPlaceholderText('regex with capture groups, e.g.  " *[0-9]+: *(.*)"')
        edit.setFont(QFont("Courier New", 9))
        edit.textChanged.connect(lambda: self._on_regex_changed(side, edit))

        btn = QPushButton("Filter")
        btn.setCheckable(True)
        btn.setFixedWidth(54)
        btn.setStyleSheet("""
            QPushButton {
                padding: 1px 6px; font-size: 10px;
                border: 1px solid #aaa; border-radius: 3px;
                background: #e0e0e0; color: #333;
            }
            QPushButton:checked {
                background: #3a9; color: white; border: 1px solid #2a8;
                font-weight: bold;
            }
        """)
        btn.toggled.connect(lambda: self._refresh())
        return edit, btn

    def _wrap_panel(self, regex_edit: QLineEdit, filter_btn: QPushButton,
                    scroll: QScrollArea) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(30)
        bar.setStyleSheet("background:#f0f0f8; border-bottom:1px solid #bbb;")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(6, 2, 6, 2)
        hl.setSpacing(6)
        lbl = QLabel("Regex:")
        lbl.setStyleSheet("font-size:10px; color:#555;")
        hl.addWidget(lbl)
        hl.addWidget(regex_edit)
        hl.addWidget(filter_btn)

        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(bar)
        vl.addWidget(scroll, 1)
        return container

    def _on_regex_changed(self, side: str, edit: QLineEdit):
        txt = edit.text()
        if not txt.strip():
            edit.setStyleSheet("")
        else:
            try:
                pat = re.compile(txt)
                if pat.groups >= 1:
                    edit.setStyleSheet("border: 1px solid #3a3; background:#f0fff0;")
                else:
                    edit.setStyleSheet("border: 1px solid #c80; background:#fffbe0;")
            except re.error:
                edit.setStyleSheet("border: 1px solid #c00; background:#fff0f0;")
        self._refresh()

    def _get_key_fns(self):
        return (
            make_key_fn(self._left_regex_edit.text()),
            make_key_fn(self._right_regex_edit.text()),
        )

    def _build_toolbar(self):
        tb = self.addToolBar("Tools")
        tb.setMovable(False)

        def act(label: str, tip: str, fn, shortcut: str | None = None):
            a = QAction(label, self)
            a.setToolTip(tip)
            a.triggered.connect(fn)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            tb.addAction(a)

        # File actions (Open / Paste / Save) live in the per-panel title menus.
        # Keep Open shortcuts available without cluttering the toolbar.
        for key, side in (("Ctrl+L", 'left'), ("Ctrl+R", 'right')):
            sc = QAction(self)
            sc.setShortcut(QKeySequence(key))
            sc.triggered.connect(lambda _checked=False, s=side: self._browse(s))
            self.addAction(sc)

        act("Auto-Align", "Align panels using LCS  (Ctrl+A)",    self._auto_align, "Ctrl+A")
        act("Sort",       "Sort both panels' lines  (Ctrl+S)",    self._sort_panels, "Ctrl+S")
        act("Reset",      "Remove all blank padding rows",        self._reset)
        tb.addSeparator()

        act("L ↑", "Shift left panel up   (remove top blank)",   lambda: self._shift('left',  'up'),   "Ctrl+Up")
        act("L ↓", "Shift left panel down (insert blank at top)", lambda: self._shift('left',  'down'), "Ctrl+Down")
        tb.addSeparator()

        act("R ↑", "Shift right panel up",   lambda: self._shift('right', 'up'),   "Alt+Up")
        act("R ↓", "Shift right panel down", lambda: self._shift('right', 'down'), "Alt+Down")
        tb.addSeparator()

        act("+ L", "Insert blank in left panel at selected row",  lambda: self._insert_blank_at_sel('left'))
        act("+ R", "Insert blank in right panel at selected row", lambda: self._insert_blank_at_sel('right'))
        act("- L", "Delete blank row in left panel at selection", lambda: self._delete_blank_at_sel('left'))
        act("- R", "Delete blank row in right panel at selection",lambda: self._delete_blank_at_sel('right'))
        tb.addSeparator()

        act("Next Diff", "Jump to next difference  (Ctrl+N)",     self._next_diff, "Ctrl+N")
        act("Prev Diff", "Jump to previous difference  (Ctrl+P)", self._prev_diff, "Ctrl+Shift+N")

        # Push the settings gear to the far right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        act("⚙", "Settings  (Ctrl+,)", self._open_settings, "Ctrl+,")

    # ── File / text loading ───────────────────────────────────────────────────

    def _on_title_menu(self, side: str, global_pos: QPoint):
        menu = QMenu(self)
        a_open  = menu.addAction("Open File…")
        a_paste = menu.addAction("Paste Text…")
        menu.addSeparator()
        a_save  = menu.addAction("Save As…")
        src = self._left_source if side == 'left' else self._right_source
        a_save.setEnabled(bool(src))
        chosen = menu.exec(global_pos)
        if chosen == a_open:
            self._browse(side)
        elif chosen == a_paste:
            self._paste(side)
        elif chosen == a_save:
            self._save(side)

    def _save(self, side: str):
        lines = self._left_source if side == 'left' else self._right_source
        if not lines:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {side.capitalize()} As", "", "All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        except OSError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        title = self._left_title if side == 'left' else self._right_title
        title.set_file(os.path.basename(path), path)

    def _browse(self, side: str):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Open {side.capitalize()} File", "", "All Files (*)"
        )
        if path:
            self._load_file(side, path)

    def _load_file(self, side: str, path: str):
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = [ln.rstrip('\n') for ln in f]
        except OSError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self._set_source(side, lines, os.path.basename(path), path)

    def _paste(self, side: str):
        dlg = PasteDialog(f"Paste {side.capitalize()} Text", self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lines = dlg.lines()
            self._set_source(side, lines, f"<pasted {side}>", "")

    def _set_source(self, side: str, lines: list[str], name: str, path: str = ""):
        if side == 'left':
            self._left_source = lines
            self._left_rows   = list(lines)
            self._left_title.set_file(name, path)
        else:
            self._right_source = lines
            self._right_rows   = list(lines)
            self._right_title.set_file(name, path)
        self._refresh()

    # ── Alignment ─────────────────────────────────────────────────────────────

    def _auto_align(self):
        if not self._left_source or not self._right_source:
            return
        lk, rk = self._get_key_fns()
        self._left_rows, self._right_rows = lcs_align(
            self._left_source, self._right_source, lk, rk
        )
        self._refresh()

    def _sort_panels(self):
        """Sort both panels' source lines in place, using each side's regex
        key (if a valid pattern is set) else the normalized text, then refresh.
        Sorting mutates the underlying source so a subsequent Auto-Align /
        Reset operates on the sorted order."""
        lk, rk = self._get_key_fns()

        def sort_key(key_fn):
            def _k(line: str):
                return (key_fn(line) if key_fn else normalize(line)), line
            return _k

        if self._left_source:
            self._left_source.sort(key=sort_key(lk))
        if self._right_source:
            self._right_source.sort(key=sort_key(rk))

        self._left_rows  = list(self._left_source)
        self._right_rows = list(self._right_source)
        self._refresh()

    def _reset(self):
        self._left_rows  = list(self._left_source)
        self._right_rows = list(self._right_source)
        self._refresh()

    # ── Manual adjustments ────────────────────────────────────────────────────

    def _shift(self, side: str, direction: str):
        rows = self._left_rows if side == 'left' else self._right_rows
        if direction == 'down':
            rows.insert(0, None)
        else:
            if rows and rows[0] is None:
                rows.pop(0)
        if side == 'left':
            self._left_rows = rows
        else:
            self._right_rows = rows
        self._refresh()

    def _insert_blank(self, side: str, row: int):
        rows = self._left_rows if side == 'left' else self._right_rows
        rows.insert(row, None)
        self._refresh()

    def _delete_blank(self, side: str, row: int):
        rows = self._left_rows if side == 'left' else self._right_rows
        if 0 <= row < len(rows) and rows[row] is None:
            rows.pop(row)
        self._refresh()

    def _insert_blank_at_sel(self, side: str):
        panel = self._left_panel if side == 'left' else self._right_panel
        r = panel.selected if panel.selected >= 0 else 0
        self._insert_blank(side, r)

    def _delete_blank_at_sel(self, side: str):
        panel = self._left_panel if side == 'left' else self._right_panel
        if panel.selected >= 0:
            self._delete_blank(side, panel.selected)

    def _insert_n_blanks(self, side: str, at_row: int, n: int):
        rows = self._left_rows if side == 'left' else self._right_rows
        for _ in range(n):
            rows.insert(at_row, None)
        self._refresh()

    def _delete_selected_blanks(self, side: str):
        panel = self._left_panel  if side == 'left' else self._right_panel
        rows  = self._left_rows   if side == 'left' else self._right_rows
        to_delete = sorted(
            [r for r in panel.selected_rows
             if 0 <= r < len(rows) and rows[r] is None],
            reverse=True,
        )
        for r in to_delete:
            rows.pop(r)
        self._refresh()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_context_menu(self, side: str, row: int, global_pos: QPoint):
        panel = self._left_panel  if side == 'left' else self._right_panel
        sel   = panel.selected_rows
        n_sel = len(sel)

        menu = QMenu(self)

        # ── Single-row insert / delete ──
        a_before = menu.addAction(f"Insert blank before row {row + 1}")
        a_after  = menu.addAction(f"Insert blank after row {row + 1}")
        a_del = None
        if row < len(panel.rows) and panel.rows[row][0] is None:
            a_del = menu.addAction("Delete this blank row")

        # ── Multi-select block ops ──
        a_del_block        = None
        a_ins_block_before = None
        a_ins_block_after  = None
        if n_sel > 1:
            menu.addSeparator()
            blank_count = sum(
                1 for r in sel
                if 0 <= r < len(panel.rows) and panel.rows[r][0] is None
            )
            if blank_count > 0:
                s = 's' if blank_count != 1 else ''
                a_del_block = menu.addAction(
                    f"Delete {blank_count} selected blank row{s}")
            a_ins_block_before = menu.addAction(
                f"Insert {n_sel} blank rows before selection")
            a_ins_block_after  = menu.addAction(
                f"Insert {n_sel} blank rows after selection")

        # ── Cross-panel compare / sync ──
        a_compare = None
        a_sync    = None
        ls = self._left_panel.selected
        rs = self._right_panel.selected
        if ls >= 0 and rs >= 0:
            menu.addSeparator()
            l_txt = (self._left_panel.rows[ls][0]
                     if ls < len(self._left_panel.rows) else None)
            r_txt = (self._right_panel.rows[rs][0]
                     if rs < len(self._right_panel.rows) else None)
            if l_txt is not None and r_txt is not None:
                a_compare = menu.addAction(f"Compare  (L:{ls+1} ↔ R:{rs+1})")
            if ls != rs:
                a_sync = menu.addAction(f"Sync  (L:{ls+1} ↔ R:{rs+1})")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        if chosen == a_before:
            self._insert_blank(side, row)
        elif chosen == a_after:
            self._insert_blank(side, row + 1)
        elif a_del and chosen == a_del:
            self._delete_blank(side, row)
        elif a_del_block and chosen == a_del_block:
            self._delete_selected_blanks(side)
        elif a_ins_block_before and chosen == a_ins_block_before:
            self._insert_n_blanks(side, min(sel), n_sel)
        elif a_ins_block_after and chosen == a_ins_block_after:
            self._insert_n_blanks(side, max(sel) + 1, n_sel)
        elif a_compare and chosen == a_compare:
            self._compare_selected()
        elif a_sync and chosen == a_sync:
            self._sync_selected()

    # ── Cross-panel operations ────────────────────────────────────────────────

    def _compare_selected(self):
        """Word-level diff highlight on the two primary selected rows."""
        ls = self._left_panel.selected
        rs = self._right_panel.selected
        if ls < 0 or rs < 0:
            return
        if ls >= len(self._left_panel.rows) or rs >= len(self._right_panel.rows):
            return
        l_txt = self._left_panel.rows[ls][0]
        r_txt = self._right_panel.rows[rs][0]
        if l_txt is None or r_txt is None:
            return

        l_diff, r_diff = compute_word_diff(l_txt, r_txt)

        # Inject diff tuples directly into panel.rows (bypasses set_rows so it persists
        # until the next full refresh).  Preserve partial-match spans at [3] if present.
        rows_l = list(self._left_panel.rows)
        old = rows_l[ls]
        rows_l[ls] = (old[0], old[1], l_diff, old[3] if len(old) > 3 else None)
        self._left_panel.rows = rows_l
        self._left_panel.update()

        rows_r = list(self._right_panel.rows)
        old = rows_r[rs]
        rows_r[rs] = (old[0], old[1], r_diff, old[3] if len(old) > 3 else None)
        self._right_panel.rows = rows_r
        self._right_panel.update()

    def _sync_selected(self):
        """Insert blanks above the side with the lower row index so both align."""
        ls = self._left_panel.selected
        rs = self._right_panel.selected
        if ls < 0 or rs < 0 or ls == rs:
            return
        if ls > rs:
            # Right is higher up — insert blanks above its selection
            n = ls - rs
            for _ in range(n):
                self._right_rows.insert(rs, None)
        else:
            # Left is higher up — insert blanks above its selection
            n = rs - ls
            for _ in range(n):
                self._left_rows.insert(ls, None)
        self._refresh()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _next_diff(self):
        panel = self._left_panel
        start = panel.selected + 1 if panel.selected >= 0 else 0
        for i in range(start, len(panel.rows)):
            if panel.rows[i][1] not in ('equal', 'blank'):
                panel.selected = i
                panel.selected_rows = {i}
                panel.update()
                self._scroll_to_row(i)
                return
        for i in range(0, start):
            if panel.rows[i][1] not in ('equal', 'blank'):
                panel.selected = i
                panel.selected_rows = {i}
                panel.update()
                self._scroll_to_row(i)
                return

    def _prev_diff(self):
        panel = self._left_panel
        start = (panel.selected - 1) if panel.selected > 0 else len(panel.rows) - 1
        for i in range(start, -1, -1):
            if panel.rows[i][1] not in ('equal', 'blank'):
                panel.selected = i
                panel.selected_rows = {i}
                panel.update()
                self._scroll_to_row(i)
                return
        for i in range(len(panel.rows) - 1, start, -1):
            if panel.rows[i][1] not in ('equal', 'blank'):
                panel.selected = i
                panel.selected_rows = {i}
                panel.update()
                self._scroll_to_row(i)
                return

    def _scroll_to_row(self, row: int):
        y = row * self._left_panel._row_h
        vbar = self._left_scroll.verticalScrollBar()
        viewport_h = self._left_scroll.viewport().height()
        vbar.setValue(max(0, y - viewport_h // 2))

    # ── Settings / appearance ──────────────────────────────────────────────────

    def _apply_appearance(self, a: Appearance):
        self._appearance = a
        self._left_panel.apply_appearance(a)
        self._right_panel.apply_appearance(a)

    def _open_settings(self):
        original = replace(self._appearance)          # snapshot for Cancel
        dlg = SettingsDialog(self._appearance, self)
        dlg.appearanceChanged.connect(self._apply_appearance)   # live preview
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_appearance(dlg.current_appearance())
            save_appearance(self._appearance)
        else:
            self._apply_appearance(original)          # revert preview

    # ── Font zoom ─────────────────────────────────────────────────────────────

    def _zoom_out(self):
        if self._zoom_idx > 0:
            self._zoom_idx -= 1
            self._apply_zoom()

    def _zoom_in(self):
        if self._zoom_idx < len(ZOOM_LEVELS) - 1:
            self._zoom_idx += 1
            self._apply_zoom()

    def _apply_zoom(self):
        pct   = ZOOM_LEVELS[self._zoom_idx]
        scale = pct / 100.0
        self._zoom_label.setText(f"{pct}%")
        self._zoom_minus_btn.setEnabled(self._zoom_idx > 0)
        self._zoom_plus_btn.setEnabled(self._zoom_idx < len(ZOOM_LEVELS) - 1)
        self._left_panel.set_font_scale(scale)
        self._right_panel.set_font_scale(scale)
        row = self._left_panel.selected if self._left_panel.selected >= 0 else 0
        self._scroll_to_row(row)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self):
        l = self._left_rows
        r = self._right_rows
        n = max(len(l), len(r))

        ld: list[tuple] = []
        rd: list[tuple] = []
        counts = {k: 0 for k in BG}

        lk, rk = self._get_key_fns()
        l_filter      = self._left_filter_btn.isChecked()  and lk is not None
        r_filter      = self._right_filter_btn.isChecked() and rk is not None
        partial_mode  = self._partial_match_cb.isChecked()

        for i in range(n):
            lt = l[i] if i < len(l) else None
            rt = r[i] if i < len(r) else None
            s  = row_status(lt, rt, lk, rk)
            counts[s] = counts.get(s, 0) + 1
            lt_d = lk(lt) if l_filter and lt is not None else lt
            rt_d = rk(rt) if r_filter and rt is not None else rt
            if partial_mode and s == 'replace' and lt_d is not None and rt_d is not None:
                l_spans, r_spans = find_partial_matches(lt_d, rt_d)
                ld.append((lt_d, s, None, l_spans if l_spans else None))
                rd.append((rt_d, s, None, r_spans if r_spans else None))
            else:
                ld.append((lt_d, s))
                rd.append((rt_d, s))

        self._left_panel.set_rows(ld)
        self._right_panel.set_rows(rd)

        total   = n
        matched = counts['equal']
        pct     = int(100 * matched / total) if total else 0
        self._status_lbl.setText(
            f"{matched}/{total} rows matched ({pct}%)"
            f"  |  diff: {counts['replace']}"
            f"  |  left-only: {counts['delete']}"
            f"  |  right-only: {counts['insert']}"
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Side-by-side text comparison with LCS alignment."
    )
    parser.add_argument("left",  nargs="?", help="left file to compare")
    parser.add_argument("right", nargs="?", help="right file to compare")
    parser.add_argument(
        "-s", "--sort", action="store_true",
        help="sort both panels' lines on startup (before auto-align)",
    )
    args, qt_args = parser.parse_known_args()

    app = QApplication(sys.argv[:1] + qt_args)
    app.setStyle("Fusion")

    win = CompareWindow(args.left, args.right, sort=args.sort)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
