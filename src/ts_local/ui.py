from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import CopyGroup, FollowerConfig, TradovateAccount


class TSLocalWindow:
    """Qt desktop shell kept behind a tiny adapter so the domain stays UI-independent."""

    def __init__(self, accounts: list[TradovateAccount] | None = None) -> None:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import (
                QComboBox,
                QFormLayout,
                QGroupBox,
                QHBoxLayout,
                QLabel,
                QMainWindow,
                QPushButton,
                QSpinBox,
                QStatusBar,
                QTableWidget,
                QTableWidgetItem,
                QVBoxLayout,
                QWidget,
            )
        except ImportError as exc:
            raise RuntimeError("Install the UI extra with: pip install -e '.[ui]'") from exc

        self._Qt = Qt
        self._QMainWindow = QMainWindow
        self._window = QMainWindow()
        self._window.setWindowTitle("TS-Local")
        self._window.resize(1100, 700)
        self._window.setStatusBar(QStatusBar())
        self._window.statusBar().showMessage("DRY RUN — no live orders will be submitted")

        root = QWidget()
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("TS-Local")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        mode = QLabel("● DRY RUN")
        mode.setStyleSheet("font-weight: 700;")
        header.addWidget(mode)
        layout.addLayout(header)

        accounts_box = QGroupBox("Accounts")
        accounts_layout = QVBoxLayout(accounts_box)
        self.account_table = QTableWidget(0, 4)
        self.account_table.setHorizontalHeaderLabels(["Account", "ID", "Role", "Status"])
        self.account_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        accounts_layout.addWidget(self.account_table)
        layout.addWidget(accounts_box)

        controls = QGroupBox("Copy Group")
        form = QFormLayout(controls)
        self.leader = QComboBox()
        self.follower = QComboBox()
        self.multiplier = QSpinBox()
        self.multiplier.setRange(1, 1000)
        self.multiplier.setValue(100)
        self.multiplier.setSuffix("%")
        self.add_button = QPushButton("Add follower")
        self.add_button.clicked.connect(self._add_follower)
        form.addRow("Leader", self.leader)
        form.addRow("Follower", self.follower)
        form.addRow("Multiplier", self.multiplier)
        form.addRow("", self.add_button)
        layout.addWidget(controls)

        self.followers_table = QTableWidget(0, 3)
        self.followers_table.setHorizontalHeaderLabels(["Follower", "Multiplier", "Enabled"])
        layout.addWidget(self.followers_table)

        self._accounts = accounts or []
        self._copy_group_followers: list[FollowerConfig] = []
        for account in self._accounts:
            self.account_table.insertRow(self.account_table.rowCount())
            row = self.account_table.rowCount() - 1
            self.account_table.setItem(row, 0, QTableWidgetItem(account.name))
            self.account_table.setItem(row, 1, QTableWidgetItem(account.account_id))
            self.account_table.setItem(row, 2, QTableWidgetItem("Available"))
            self.account_table.setItem(row, 3, QTableWidgetItem("Active" if account.active else "Inactive"))
            self.leader.addItem(account.name, account.id)
            self.follower.addItem(account.name, account.id)

        self._window.setCentralWidget(root)

    def _add_follower(self) -> None:
        account_id = self.follower.currentData()
        if account_id is None:
            return
        multiplier = Decimal(self.multiplier.value()) / Decimal(100)
        try:
            follower = FollowerConfig(account_id=account_id, multiplier=multiplier)
        except (InvalidOperation, ValueError):
            return
        self._copy_group_followers.append(follower)
        row = self.followers_table.rowCount()
        self.followers_table.insertRow(row)
        self.followers_table.setItem(row, 0, QTableWidgetItem(self.follower.currentText()))
        self.followers_table.setItem(row, 1, QTableWidgetItem(f"{multiplier:g}x"))
        self.followers_table.setItem(row, 2, QTableWidgetItem("Enabled"))

    def show(self) -> None:
        self._window.show()

    def exec(self) -> int:
        from PySide6.QtWidgets import QApplication

        return QApplication.instance().exec()
