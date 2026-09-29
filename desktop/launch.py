"""First-run launcher: installs Qt into this project's private virtual environment."""
from pathlib import Path
import os
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("MKV Profile Converter requires Python 3.10 or newer. Get it from https://www.python.org/downloads/")
    root = Path(__file__).resolve().parent
    env = root / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirement = (root / "requirements.txt").read_text("utf-8")
    marker = env / ".dovi-requirements"
    if not python.exists():
        print("Preparing MKV Profile Converter's private Python environment…", flush=True)
        venv.create(env, with_pip=True)
    if not marker.exists() or marker.read_text("utf-8") != requirement:
        print("Installing the desktop interface (first launch only)…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(root / "requirements.txt")], check=True)
        marker.write_text(requirement, "utf-8")
    return subprocess.call([str(python), str(root / "run.py"), *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Could not launch MKV Profile Converter: {error}", file=sys.stderr)
        print("See README.md for manual setup and troubleshooting.", file=sys.stderr)
        raise SystemExit(1)
