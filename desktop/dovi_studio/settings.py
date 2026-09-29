import json
import os
import sys
import tempfile
from pathlib import Path

from .models import Options


def settings_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "DoVi Studio"


def load() -> Options:
    try:
        return Options.from_dict(json.loads((settings_dir() / "settings.json").read_text("utf-8")))
    except (OSError, ValueError, TypeError):
        return Options()


def save(options: Options) -> None:
    folder = settings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="settings-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(options.to_dict(), stream, indent=2)
        os.replace(name, folder / "settings.json")
    finally:
        Path(name).unlink(missing_ok=True)
