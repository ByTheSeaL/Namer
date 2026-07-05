"""Regenerate assets/icon.ico, icon.icns, and icon.png from namer/icon.py.

Run whenever the icon drawing changes:
    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/make_icons.py
Requires Pillow (build-time only, not a runtime dependency).
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PySide6.QtCore import QBuffer
from PySide6.QtWidgets import QApplication

from namer.icon import pixmap

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def to_pil(size: int) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QBuffer.ReadWrite)
    pixmap(size).save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data())))


def main():
    QApplication([])
    ASSETS.mkdir(exist_ok=True)

    to_pil(256).save(ASSETS / "icon.png")
    to_pil(256).save(ASSETS / "icon.ico",
                     sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    to_pil(1024).save(ASSETS / "icon.icns")
    print("wrote", *(p.name for p in sorted(ASSETS.iterdir())))


if __name__ == "__main__":
    main()
