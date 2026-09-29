"""Build on each target OS; PyInstaller does not cross-compile."""
import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true", help="Also create a platform-named distribution archive")
    parser.add_argument("--bundle-media", action="store_true", help="macOS: include all six native media tools and their libraries")
    args = parser.parse_args()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--name", "MKVProfileConverter", "--paths", str(root),
               "--add-data", f"{root / 'LICENSE'}{os.pathsep}.",
               "--add-data", f"{root / 'NOTICE.md'}{os.pathsep}.",
               "--add-data", f"{root / 'licenses'}{os.pathsep}licenses"]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "org.mkv-profile-converter.desktop"]
    if args.bundle_media:
        if sys.platform != "darwin":
            parser.error("--bundle-media currently supports native macOS builds")
        from collect_macos_tools import collect
        binaries, notices = collect(root)
        command += ["--add-data", f"{notices}{os.pathsep}licenses/media-tools"]
    command += [str(root / "run.py")]
    subprocess.run(command, cwd=root, check=True)
    target = root / "dist" / ("MKVProfileConverter.app" if sys.platform == "darwin" else "MKVProfileConverter")
    if sys.platform == "darwin":
        if args.bundle_media:
            from bundle_macos_tools import bundle
            bundle(binaries, target / "Contents/Frameworks/media-tools")
        sys.path.insert(0, str(root))
        from dovi_studio import __version__
        info = target / "Contents/Info.plist"
        metadata = plistlib.loads(info.read_bytes())
        metadata.update(CFBundleName="MKV Profile Converter", CFBundleDisplayName="MKV Profile Converter",
                        CFBundleVersion=__version__, CFBundleShortVersionString=__version__)
        if args.bundle_media:
            metadata["LSMinimumSystemVersion"] = "15.0"
        info.write_bytes(plistlib.dumps(metadata))
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(target)], check=True)
    print(f"Built: {target}")
    if args.archive:
        system = "macOS" if sys.platform == "darwin" else platform.system()
        name = f"MKV-Profile-Converter-{system}-{platform.machine()}"
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
