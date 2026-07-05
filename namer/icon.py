"""The app icon, drawn in code — a white N on a rounded blue tile.

Drawing at runtime keeps the titlebar/taskbar icon working on every
platform without bundling image assets into the binary. The same drawing
is exported to assets/icon.ico / .icns (see tools/make_icons.py) for the
executable's own file icon.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

ACCENT = "#4a6cf7"


def pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(ACCENT))
    painter.setPen(Qt.NoPen)
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    font = QFont("Arial")
    font.setBold(True)
    font.setPixelSize(int(size * 0.62))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, -size * 0.03, size, size), Qt.AlignCenter, "N")
    painter.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(pixmap(size))
    return icon
