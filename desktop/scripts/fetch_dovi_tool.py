"""Fetch a checksum-pinned official dovi_tool binary for a macOS build."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

VERSION = "2.3.4"
URL = "https://github.com/quietvoid/dovi_tool/releases/download/2.3.4/dovi_tool-2.3.4-universal-macOS.zip"
SHA256 = "30d4f512eb67b7f1632cd28be5c62989bedad23f4710578aafc20c384b48ece6"


def fetch(root):
    folder = root / "build/media-vendor"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "dovi_tool.zip"
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        with urllib.request.urlopen(URL, timeout=90) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("Official dovi_tool download checksum does not match")
        archive.write_bytes(data)
    with zipfile.ZipFile(archive) as bundle:
        matches = [name for name in bundle.namelist() if Path(name).name == "dovi_tool"]
        if len(matches) != 1:
            raise RuntimeError("Unexpected official dovi_tool archive layout")
        binary = folder / "dovi_tool"
        binary.write_bytes(bundle.read(matches[0]))
    binary.chmod(0o755)
    return binary


if __name__ == "__main__":
    print(fetch(Path(__file__).resolve().parents[1]))
