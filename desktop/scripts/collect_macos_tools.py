"""Collect Homebrew media binaries; PyInstaller relocates their dylib closure.

Homebrew is used only on the build machine. The installed app never installs,
updates or invokes Homebrew. Record exact keg metadata, build recipes, licenses,
and source URLs alongside the runtime for redistribution and reproducibility.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from fetch_dovi_tool import fetch, URL, SHA256, VERSION

PROGRAMS = {"mkvmerge": "mkvtoolnix",
            "mkvextract": "mkvtoolnix", "ffmpeg": "ffmpeg",
            "ffprobe": "ffmpeg", "mediainfo": "media-info"}


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def collect(root):
    brew = shutil.which("brew")
    if not brew:
        raise SystemExit("Build machine needs Homebrew: brew install mkvtoolnix ffmpeg media-info")
    notices = root / "build/media-tool-notices"
    if notices.exists():
        shutil.rmtree(notices)
    notices.mkdir(parents=True)
    formulas = set(PROGRAMS.values())
    for formula in tuple(formulas):
        formulas.update(output(brew, "deps", "--formula", "--installed", formula).splitlines())
    metadata = json.loads(output(brew, "info", "--json=v2", *sorted(formulas)))
    (notices / "homebrew-formulas.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows = [{"name": "dovi_tool", "installed_version": VERSION, "license": "MIT",
             "binary_url": URL, "binary_sha256": SHA256,
             "source": {"url": "https://github.com/quietvoid/dovi_tool/archive/refs/tags/2.3.4.tar.gz",
                        "checksum": "15b5cb68b3598e51ca968316443c9fb9597b6230e9d692cb4e641d54505a97ec"}}]
    for formula in metadata["formulae"]:
        name = formula["name"]
        prefix = Path(output(brew, "--prefix", name)).resolve()
        destination = notices / name
        destination.mkdir()
        for item in prefix.rglob("*"):
            if item.is_file() and (item.name.lower().startswith(("license", "licence", "copying", "notice", "copyright"))
                                   or item.parent.name == ".brew" or item.name == "INSTALL_RECEIPT.json"):
                relative = item.relative_to(prefix)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, target)
        rows.append({"name": name, "installed_version": prefix.name,
                     "license": formula.get("license"), "homepage": formula.get("homepage"),
                     "source": formula.get("urls", {}).get("stable"),
                     "recipe": formula.get("ruby_source_path"),
                     "recipe_sha256": formula.get("ruby_source_checksum")})
    (notices / "sources.json").write_text(json.dumps(rows, indent=2) + "\n")
    (notices / "README.txt").write_text(
        "Bundled native media tools and libraries retain their upstream licenses.\n"
        "sources.json identifies exact upstream source archives and checksums.\n"
        "Each component folder includes installed notices and the Homebrew build\n"
        "recipe/receipt. homebrew-formulas.json records the bottle metadata.\n"
        "PyInstaller relocates dylib references and applies ad-hoc signatures;\n"
        "the media-tool source code is otherwise unmodified.\n"
        "Rebuild on macOS with the recorded recipes, then run:\n"
        "python scripts/build.py --bundle-media --archive\n"
        "python scripts/build_installer.py\n")
    binaries = [fetch(root)]
    for program, formula in PROGRAMS.items():
        binary = Path(output(brew, "--prefix", formula)) / "bin" / program
        if not binary.is_file():
            raise SystemExit(f"Missing build dependency: {binary}")
        binaries.append(binary)
    sys.path.insert(0, str(root))
    from dovi_studio.dependencies import discover
    checked = discover({binary.name: str(binary) for binary in binaries})
    failures = [f"{name}: {tool.message}" for name, tool in checked.items() if not tool.ok]
    if failures:
        raise SystemExit("Build-time media verification failed: " + "; ".join(failures))
    return binaries, notices
