"""Check an installed macOS bundle and exercise its native Cocoa startup."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("This check must run on macOS.")
    executable = args.app / "Contents/MacOS/MKVProfileConverter"
    subprocess.run(["lipo", str(executable), "-verify_arch", platform.machine()], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(args.app)], check=True)
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    # Use macOS's Cocoa plugin, not the offscreen test plugin. Runner settings
    # are disposable; no user settings are involved in this build-time check.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(executable)], env=env, stdout=log, stderr=log)
        try:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                print("Installed app remained running through native Cocoa startup.")
            else:
                raise RuntimeError(f"Installed app exited during startup: {process.returncode}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            log.seek(0)
            output = log.read().decode("utf-8", errors="replace")
            if output:
                print(output)
    if "Traceback (most recent call last)" in output:
        raise SystemExit("Python reported an error during installed-app startup.")


if __name__ == "__main__":
    main()
