"""Build on each target OS; PyInstaller does not cross-compile."""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true", help="Also create a platform-named distribution archive")
    args = parser.parse_args()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--name", "MKVProfileConverter", "--paths", str(root),
               "--add-data", f"{root / 'LICENSE'}{os.pathsep}.",
               "--add-data", f"{root / 'NOTICE.md'}{os.pathsep}.",
               "--add-data", f"{root / 'licenses'}{os.pathsep}licenses"]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "org.mkv-profile-converter.desktop"]
    command += [str(root / "run.py")]
    subprocess.run(command, cwd=root, check=True)
    target = root / "dist" / ("MKVProfileConverter.app" if sys.platform == "darwin" else "MKVProfileConverter")
    print(f"Built: {target}")
    if args.archive:
        name = f"MKV-Profile-Converter-{platform.system()}-{platform.machine()}"
        if sys.platform == "darwin":
            archive = root / "dist" / f"{name}.zip"
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(target), str(archive)], check=True)
        elif sys.platform == "win32":
            archive = shutil.make_archive(str(root / "dist" / name), "zip", root_dir=target.parent, base_dir=target.name)
        else:
            # Qt and PyInstaller use symbolic links; tar preserves those links.
            archive = shutil.make_archive(str(root / "dist" / name), "gztar", root_dir=target.parent, base_dir=target.name)
        print(f"Archive: {archive}")


if __name__ == "__main__":
    main()
