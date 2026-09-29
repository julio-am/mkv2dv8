"""Relocate media tools into their own library directory, separate from Qt GUI.

MKVToolNix links Homebrew's QtCore. Combining its dependency graph with
PySide6's graph can load an incompatible QtCore into the GUI process. Use
PyInstaller's Mach-O processing separately, with media-tools as its root.
"""
import os
from pathlib import Path
import platform
import shutil


def bundle(binaries, destination):
    from PyInstaller.building.datastruct import normalize_toc
    from PyInstaller.building.utils import process_collected_binary
    from PyInstaller.config import CONF
    from PyInstaller.configure import get_config
    from PyInstaller.depend.bindepend import binary_dependency_analysis
    from PyInstaller.utils.osx import collect_files_from_framework_bundles

    CONF.update(get_config())
    entries = [(binary.name, str(binary.resolve()), "BINARY") for binary in binaries]
    entries = binary_dependency_analysis(entries, symlink_suppression_patterns=())
    entries = normalize_toc(collect_files_from_framework_bundles(entries))
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name, source, kind in entries:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid media dependency destination: {name}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "SYMLINK":
            target.symlink_to(source)
            continue
        if kind == "BINARY":
            source = process_collected_binary(source, name,
                                              target_arch=platform.machine(),
                                              strict_arch_validation=True)
        elif kind != "DATA":
            raise ValueError(f"Unexpected media dependency type: {kind}")
        shutil.copyfile(source, target)
        if kind == "BINARY" or os.access(source, os.X_OK):
            target.chmod(0o755)
    print(f"Bundled {len(entries)} media files in an isolated library directory.")
