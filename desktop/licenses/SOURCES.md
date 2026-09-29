# Runtime licensing and corresponding source

MKV Profile Converter is GPL-3.0-or-later. Its complete application source and rebuild
instructions are supplied in the source distribution.

The unmodified Qt/PySide runtime is dynamically linked. It can be replaced by
installing another compatible PySide6 release and rebuilding, or by replacing
compatible dynamic libraries in the application bundle. No technical restriction
on debugging or modification is added by MKV Profile Converter.

- Qt/PySide and Shiboken, version 6.11.2 in the validated build:
  https://download.qt.io/archive/qt/6.11/6.11.2/single/
  https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2
- Qt module licenses and third-party notices:
  https://doc.qt.io/qt-6/licensing.html
  https://doc.qt.io/qt-6/licenses-used-in-qt.html
- PyInstaller 6.22.3 bootloader (GPL with the bundling exception):
  https://github.com/pyinstaller/pyinstaller/tree/v6.22.3
- CPython 3.12.14 in the validated Linux bundle (PSF license):
  https://www.python.org/downloads/release/python-31214/

LGPLv3, GPLv3 and the Qt GPL exception text are included in this folder.
Third-party components retain their original licenses; refer to the matching
Qt source distribution for per-component notices. When making modified runtime
builds or distributing a different platform bundle, include its corresponding
notices and source access alongside the application source.

The complete macOS distribution additionally contains `media-tools/sources.json`,
exact Homebrew formula metadata, build recipes/receipts, and installed component
licenses for its native media executables and library dependencies. The source
URLs and checksums identify the upstream sources used by those formulas.
