"""Build a native installer on Windows or macOS after scripts/build.py."""
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dovi_studio import __version__


def main():
    if sys.platform == 'win32':
        if platform.machine().lower() not in ('amd64', 'x86_64'):
            raise SystemExit('The Windows installer currently targets x86_64. Use the portable build on other architectures.')
        compiler = shutil.which('ISCC') or shutil.which('iscc')
        if not compiler:
            candidates = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe',
                          Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Inno Setup 6/ISCC.exe']
            compiler = next((str(path) for path in candidates if path.is_file()), None)
        if not compiler:
            raise SystemExit('Install Inno Setup 6, then run this command again. https://jrsoftware.org/isinfo.php')
        if not (ROOT / 'dist/MKVProfileConverter/MKVProfileConverter.exe').is_file():
            raise SystemExit('Build the Windows app first: python scripts/build.py --archive')
        subprocess.run([compiler, f'/DAppVersion={__version__}', f'/DSourceRoot={ROOT}', str(ROOT / 'packaging/windows.iss')], check=True)
    elif sys.platform == 'darwin':
        app = ROOT / 'dist/MKVProfileConverter.app'
        if not app.is_dir():
            raise SystemExit('Build the macOS app first: python3 scripts/build.py --archive')
        tools = app / 'Contents/Frameworks/media-tools'
        for name in ('dovi_tool', 'mkvmerge', 'mkvextract', 'ffmpeg', 'ffprobe', 'mediainfo'):
            if not (tools / name).is_file():
                raise SystemExit('The Mac installer requires all media tools. Build with scripts/build.py --bundle-media --archive')
        stage = ROOT / 'build/installer-root'
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        shutil.copytree(app, stage / app.name, symlinks=True)
        components = ROOT / 'build/installer-components.plist'
        subprocess.run(['pkgbuild', '--analyze', '--root', str(stage), '--component-plist', str(components)], check=True)
        definitions = plistlib.loads(components.read_bytes())
        for definition in definitions:
            definition['BundleIsRelocatable'] = False
            definition['BundleOverwriteAction'] = 'upgrade'
        components.write_bytes(plistlib.dumps(definitions))
        output = ROOT / 'dist' / f'MKV-Profile-Converter-macOS-{platform.machine()}-Installer.pkg'
        subprocess.run(['pkgbuild', '--root', str(stage), '--component-plist', str(components),
                        '--scripts', str(ROOT / 'packaging/macos-scripts'), '--install-location', '/Applications',
                        '--identifier', 'org.mkv-profile-converter.desktop', '--version', __version__, str(output)], check=True)
        print(output)
    else:
        print('Linux: distribute the TAR.GZ created by scripts/build.py --archive. Media Tools Setup runs inside the app.')


if __name__ == '__main__':
    main()
