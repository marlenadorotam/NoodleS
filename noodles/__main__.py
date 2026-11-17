from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import uuid


def main():
    os.environ["QT_PREFERRED_BINDING"] = "PySide6"
    log_dir = Path(__file__).resolve().parent.parent / ".logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[RotatingFileHandler(log_dir / "noodles.log", maxBytes=1_000_000,
                                     backupCount=2, encoding="utf-8")],
    )
    parser = argparse.ArgumentParser(prog="NoodleS")
    parser.add_argument("graph", nargs="?", type=Path, help="A .noodles file")
    parser.add_argument("--empty", action="store_true", help="Start with an empty canvas")
    parser.add_argument("--bridge-session", type=uuid.UUID, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NoodleS.Editor")
    from Qt import QtCore, QtGui, QtWidgets
    from .window_icon import WindowIconEngine

    app = QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("NoodleS")
    app.setOrganizationName("NoodleS")
    icon_dir = Path(__file__).parent
    title_icon = QtGui.QIcon(str(icon_dir / "noodles-icon.svg"))
    taskbar_icon = QtGui.QIcon(str(icon_dir / "noodles-icon-taskbar.svg"))
    app.setWindowIcon(QtGui.QIcon(WindowIconEngine(title_icon, taskbar_icon)))
    app.setStyle("Fusion")
    try:
        from .window import MainWindow
        window = MainWindow(example=False, bridge_session=str(args.bridge_session) if args.bridge_session else None)
    except Exception:
        logging.exception("Application startup failed")
        QtWidgets.QMessageBox.critical(None, "NoodleS — Startup error",
                                      "Unable to start NoodleS.\nDetails: " + str(log_dir / "noodles.log"))
        return 1

    def report_exception(exc_type, value, traceback):
        logging.error("Unhandled UI error", exc_info=(exc_type, value, traceback))
        QtWidgets.QMessageBox.warning(window, "NoodleS — Error", str(value))

    sys.excepthook = report_exception
    window.showMaximized()
    if args.graph:
        def open_startup_graph(state, _payload):
            if state != 'connecting':
                window.serpentine.changed.disconnect(open_startup_graph)
                QtCore.QTimer.singleShot(0, lambda: window.open_document(args.graph))

        window.serpentine.changed.connect(open_startup_graph)
    window.serpentine.start()
    app.aboutToQuit.connect(window.serpentine.stop)
    app.aboutToQuit.connect(window.point_service.stop)
    QtCore.QTimer.singleShot(0, window.graph.fit_to_selection)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
