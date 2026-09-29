"""Keep external tools independent of the desktop bundle's dynamic libraries."""
import ctypes
import os
import subprocess
import sys
import threading

_spawn_lock = threading.Lock()


def external_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["AV_LOG_FORCE_NOCOLOR"] = "1"
    if os.name != "nt":
        locale = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"
        env.update({"LC_ALL": locale, "LANG": locale})
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            original = env.get(key + "_ORIG")
            if original is not None:
                env[key] = original
            else:
                env.pop(key, None)
        bundle = str(getattr(sys, "_MEIPASS", ""))
        if bundle:
            env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                         if not os.path.normcase(p).startswith(os.path.normcase(bundle)))
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            if bundle and bundle in env.get(key, ""):
                env.pop(key, None)
    return env


def popen_external(args, **kwargs):
    kwargs.setdefault("env", external_environment())
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    with _spawn_lock:
        frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(args, **kwargs)
        finally:
            if frozen_windows:
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
