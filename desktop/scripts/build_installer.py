"""Build a native installer on Windows or macOS after scripts/build.py."""
import os
import platform
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
        output = ROOT / 'dist' / f'MKV-Profile-Converter-macOS-{platform.machine()}-Installer.pkg'
        subprocess.run(['pkgbuild', '--component', str(app), '--install-location', '/Applications',
                        '--identifier', 'org.mkv-profile-converter.desktop', '--version', __version__, str(output)], check=True)
        print(output)
    else:
        print('Linux: distribute the TAR.GZ created by scripts/build.py --archive. Media Tools Setup runs inside the app.')


if __name__ == '__main__':
    main()
