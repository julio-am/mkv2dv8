import sys


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-installation":
        from .diagnostics import verify_installation
        return verify_installation(sys.argv[2], sys.argv[3])
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("MKV Profile Converter")
    app.setOrganizationName("MKV Profile Converter")
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        # Startup dependency checks finish before file import.
        from PySide6.QtCore import QTimer
        timer = QTimer(window)
        def import_when_ready():
            if window.worker is None and not (window.setup_wizard and window.setup_wizard.isVisible()):
                timer.stop()
                window.import_paths(sys.argv[1:])
        timer.timeout.connect(import_when_ready)
        timer.start(200)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
