"""Explicit CI check of the installed GUI and its bundled conversion engine."""
import json
from pathlib import Path
import sys
import tempfile
import traceback


def verify_installation(report_path, fixture_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from . import __version__, settings
    from .dependencies import require
    from .engine import Engine
    from .ui import MainWindow

    report = Path(report_path).resolve()
    fixture = Path(fixture_path).resolve()
    app = QApplication([sys.argv[0]])
    result = {"version": __version__, "ok": False}
    with tempfile.TemporaryDirectory(prefix="mkv-install-check-") as folder:
        settings.settings_dir = lambda: Path(folder) / "settings"
        window = MainWindow()
        window.show()
        state = "startup"

        def finish(code):
            poll.stop()
            timeout.stop()
            report.write_text(json.dumps(result, indent=2) + "\n")
            if window.conversion_wizard:
                window.conversion_wizard.accept()
            window.close()
            app.exit(code)

        def check():
            nonlocal state
            try:
                if state == "startup":
                    if not window.tools or window.worker is not None:
                        return
                    require(window.tools, "stream")
                    assert all(tool.ok for tool in window.tools.values()), window.tools
                    assert window.setup_wizard is None, "First launch opened dependency setup"
                    bundle = Path(sys._MEIPASS).resolve()
                    result["tools"] = {name: {"version": tool.version, "path": tool.path}
                                       for name, tool in window.tools.items()}
                    assert all(Path(tool.path).resolve().is_relative_to(bundle) for tool in window.tools.values())
                    result["setup_wizard_shown"] = False
                    window.grab().save(str(report.with_suffix(".png")))
                    window.options.output_dir = str(Path(folder) / "output")
                    # Exercise the real FFmpeg -> dovi_tool streaming path, plus
                    # MKVToolNix remuxing and compressed audio/subtitle hashes.
                    window.options.method = "stream"
                    window.add_discovered([(fixture, None)])
                    window.open_conversion()
                    for _ in range(3):
                        window.conversion_wizard.next()
                    state = "conversion"
                elif window.conversion_wizard.progress_page.done:
                    job = window.jobs[0]
                    assert job.status == "Done", job.result
                    media = Engine(window.tools, window.options).probe(Path(job.result))
                    assert media.profile == 8 and media.compatibility == 1
                    result.update(ok=True, conversion="Profile 7 -> Profile 8.1", method="stream",
                                  strict_verification=window.options.strict_verify,
                                  log=window.log_view.toPlainText())
                    finish(0)
            except Exception:
                result["error"] = traceback.format_exc()
                finish(1)

        def timed_out():
            result["error"] = f"Timed out during {state}"
            if window.worker:
                window.worker.cancel.set()
            report.write_text(json.dumps(result, indent=2) + "\n")
            # The supervising CI process also has a timeout. Allow the normal
            # worker shutdown path instead of destroying a running QThread.
            window.close_when_done = True
            window.close()
            app.exit(1)

        poll = QTimer(window)
        poll.timeout.connect(check)
        poll.start(100)
        timeout = QTimer(window)
        timeout.setSingleShot(True)
        timeout.timeout.connect(timed_out)
        timeout.start(90000)
        return app.exec()
