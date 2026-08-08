from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "TS-Local"


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit("Install the UI with: pip install -e '.[ui]'") from exc

    from .connections import ConnectionManager
    from .security import WindowsDPAPISecretStore
    from .ui import TSLocalWindow

    root = _app_data_root()
    manager = ConnectionManager(
        root / "connections.json",
        WindowsDPAPISecretStore(root / "secrets"),
    )

    app = QApplication.instance() or QApplication(sys.argv)
    window = TSLocalWindow(connection_manager=manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
