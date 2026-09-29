"""Check an installed macOS bundle and exercise its native Cocoa startup."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("dist/installed-app-check.json"))
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("This check must run on macOS.")
    executable = args.app / "Contents/MacOS/MKVProfileConverter"
    subprocess.run(["lipo", str(executable), "-verify_arch", platform.machine()], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(args.app)], check=True)
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    for key in tuple(env):
        if key.startswith(("DYLD_", "QT_PLUGIN")):
            env.pop(key)
    # Require the installer itself to have opened the ordinary application.
    running = []
    for _ in range(20):
        probe = subprocess.run(["/usr/bin/pgrep", "-f", "^" + re.escape(str(executable)) + "( |$)"],
                               text=True, stdout=subprocess.PIPE)
        running = probe.stdout.split()
        if running:
            break
        time.sleep(.25)
    auto_launched = bool(running)
    if not running:
        print("Launch diagnostics:", flush=True)
        subprocess.run(["/usr/bin/stat", "-f", "console user: %Su (%u)", "/dev/console"])
        processes = subprocess.check_output(["/bin/ps", "-axww", "-o", "pid=,uid=,comm="], text=True)
        print("\n".join(line for line in processes.splitlines() if "MKVProfileConverter" in line), flush=True)
        subprocess.run(["/usr/bin/tail", "-n", "65", "/var/log/install.log"])
    for pid in running:
        owner = subprocess.check_output(["/bin/ps", "-o", "uid=", "-p", pid], text=True).strip()
        assert owner != "0", "Installer must never launch the app as root"
        os.kill(int(pid), signal.SIGTERM)
    if auto_launched:
        print("Installer automatically launched the app as the console user.")
    # Reject unresolved absolute build-machine references, including in nested
    # libraries that a --version-only check might not exercise.
    for binary in (args.app / "Contents/Frameworks").rglob("*"):
        if not binary.is_file() or binary.is_symlink():
            continue
        with binary.open("rb") as stream:
            magic = stream.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
            continue
        linked = subprocess.check_output(["otool", "-L", str(binary)], text=True).splitlines()[1:]
        for line in linked:
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(("/System/Library/", "/usr/lib/")):
                # A dylib's own install ID is not a dependency.
                identity = subprocess.check_output(["otool", "-D", str(binary)], text=True).splitlines()[1:]
                if dependency not in identity:
                    raise RuntimeError(f"External library remains: {binary}: {dependency}")
    # Use macOS's Cocoa plugin, not the offscreen test plugin. Runner settings
    # are disposable; no user settings are involved in this build-time check.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(executable), "--verify-installation", str(args.report.resolve()),
                                    str(args.fixture.resolve())], env=env, stdout=log, stderr=log)
        try:
            try:
                process.wait(timeout=100)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Installed-app conversion check timed out.")
            else:
                if process.returncode != 0:
                    raise RuntimeError(f"Installed-app conversion check failed: {process.returncode}")
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
    report = json.loads(args.report.read_text())
    report["installer_auto_launched"] = auto_launched
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    assert report["ok"] and not report["setup_wizard_shown"], report
    print("Installed GUI opened without setup and completed P7 -> P8.1 streaming conversion using bundled tools.")
    if not auto_launched:
        raise SystemExit("Installer did not launch the app for the console user.")


if __name__ == "__main__":
    main()
