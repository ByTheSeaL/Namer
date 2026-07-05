"""Per-user config/data directory, platform-appropriate.

- Windows:  %APPDATA%\\Namer          (e.g. C:\\Users\\you\\AppData\\Roaming\\Namer)
- macOS:    ~/Library/Application Support/Namer
- Linux:    ~/.config/namer

Holds openrouter_key and words.sqlite3. If a legacy ~/.config/namer
directory already exists (created by versions <= 0.4.0 on any OS), it keeps
being used so nothing is orphaned.
"""

import os
import sys
from pathlib import Path

_LEGACY = Path.home() / ".config" / "namer"


def config_dir() -> Path:
    if _LEGACY.is_dir():
        return _LEGACY
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "Namer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Namer"
    return _LEGACY
