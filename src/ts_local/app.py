from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit("Install the UI with: pip install -e '.[ui]'") from exc

    from .ui import TSLocalWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = TSLocalWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
