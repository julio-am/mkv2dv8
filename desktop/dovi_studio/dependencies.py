from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import OperationError
from .platform_tools import popen_external


@dataclass
class Tool:
    name: str
    path: str = ""
    version: str = ""
    ok: bool = False
    message: str = "Not found"


SPECS = {
    "dovi_tool": ((2, 3, 4), "https://github.com/quietvoid/dovi_tool/releases"),
    "mkvmerge": ((67, 0, 0), "https://mkvtoolnix.download/downloads.html"),
    "mkvextract": ((67, 0, 0), "https://mkvtoolnix.download/downloads.html"),
    "ffmpeg": ((5, 0, 0), "https://ffmpeg.org/download.html"),
    "ffprobe": ((5, 0, 0), "https://ffmpeg.org/download.html"),
    "mediainfo": ((22, 0, 0), "https://mediaarea.net/en/MediaInfo/Download"),
}


def version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(?:v|version\s+)?(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x or 0) for x in match.groups()) if match else ()


def bundled_tool_dirs() -> list[Path]:
    """PyInstaller keeps executables under _MEIPASS, including macOS bundles."""
    if not getattr(sys, "frozen", False):
        return []
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return [root / "media-tools", Path(sys.executable).parent / "tools"]


def candidate_dirs() -> list[Path]:
    app_root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    dirs = [app_root / "tools", Path.home() / ".local/bin", Path.home() / ".cargo/bin"]
    if sys.platform == "darwin":
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/local/bin"),
                 Path("/Applications/MKVToolNix.app/Contents/MacOS")]
    elif sys.platform == "win32":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(key):
                root = Path(os.environ[key])
                dirs += [root / "MKVToolNix", root / "MediaInfo", root / "ffmpeg/bin", root / "Microsoft/WinGet/Links"]
        dirs += [Path.home() / "scoop/shims", Path("C:/ffmpeg/bin")]
    else:
        dirs += [Path("/usr/local/bin"), Path("/usr/bin"), Path("/snap/bin")]
    return dirs


def discover(overrides: dict[str, str] | None = None) -> dict[str, Tool]:
    overrides = overrides or {}
    result = {}
    directories = candidate_dirs()
    # Picking mkvmerge or ffmpeg also makes its companion executable discoverable.
    directories = [Path(p).expanduser().parent for p in overrides.values() if p] + directories
    for name, (minimum, _) in SPECS.items():
        configured = overrides.get(name, "").strip()
        suffix = ".exe" if sys.platform == "win32" else ""
        # A complete distribution must not accidentally use an older program
        # from Homebrew/PATH. Explicit user overrides still take precedence.
        bundled = next((str(p / (name + suffix)) for p in bundled_tool_dirs()
                        if (p / (name + suffix)).is_file()), "")
        executable = str(Path(configured).expanduser()) if configured else bundled or shutil.which(name)
        if not executable:
            executable = next((str(p / (name + suffix)) for p in directories if (p / (name + suffix)).is_file()), "")
        tool = Tool(name=name, path=executable or "")
        if executable:
            try:
                flag = "-version" if name in {"ffmpeg", "ffprobe"} else "--Version" if name == "mediainfo" else "--version"
                with popen_external([executable, flag], stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                    try:
                        stdout, stderr = proc.communicate(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate()
                        raise
                output = (stdout + stderr).decode("utf-8", "replace").strip()
                parsed = version_tuple(output)
                tool.version = ".".join(map(str, parsed)) if parsed else "Unknown"
                tool.ok = proc.returncode == 0 and bool(parsed) and parsed >= minimum
                tool.message = "Ready" if tool.ok else f"Requires {'.'.join(map(str, minimum))}+; {output[:180]}"
            except (OSError, subprocess.TimeoutExpired) as error:
                tool.message = str(error)
        result[name] = tool
    return result


def require(tools: dict[str, Tool], method: str = "disk") -> None:
    needed = ["dovi_tool", "mkvmerge", "mkvextract"]
    if method == "stream":
        needed.append("ffmpeg")
    missing = [name for name in needed if not tools[name].ok]
    if not (tools["ffprobe"].ok or tools["mediainfo"].ok):
        missing.append("ffprobe or MediaInfo")
    if missing:
        raise OperationError("Set up these tools in Tools → Media Tools Setup: " + ", ".join(missing))


def install_guide() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install dovi_tool mkvtoolnix ffmpeg media-info\n\nApple Silicon and Intel Homebrew locations are both detected."
    if system == "Windows":
        return ("winget install --id MoritzBunkus.MKVToolNix -e\n"
                "winget install --id Gyan.FFmpeg -e\n"
                "winget install --id MediaArea.MediaInfo -e\n\n"
                "Download dovi_tool from its official Releases page. Choose x86_64 or ARM64 for your PC. "
                "Extract the ZIP, then select dovi_tool.exe on the next page. Portable executables and Scoop are supported. No WSL needed.")
    return ("Debian / Ubuntu:\nsudo apt install mkvtoolnix ffmpeg mediainfo\n\n"
            "Fedora: install mkvtoolnix and mediainfo using dnf; FFmpeg availability depends on your enabled repositories.\n"
            "Arch: sudo pacman -S mkvtoolnix-cli ffmpeg mediainfo\n\n"
            "Download dovi_tool's Linux release for x86_64 or ARM64 and select the extracted executable. "
            "The file must have executable permission (chmod +x dovi_tool).")
