from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

from .connections import ConnectionManager
from .models import FollowerConfig, TradovateAccount


class TSLocalWindow:
    """Qt desktop shell kept behind a tiny adapter so the domain stays UI-independent."""

    def __init__(
        self,
        accounts: list[TradovateAccount] | None = None,
        connection_manager: ConnectionManager | None = None,
    ) -> None:
        try:
            from PySide6.QtWidgets import (
                QComboBox,
                QFormLayout,
                QGroupBox,
                QHBoxLayout,
                QLabel,
                QLineEdit,
                QMainWindow,
                QMessageBox,
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

        self._QTableWidgetItem = QTableWidgetItem
        self._QMessageBox = QMessageBox
        self._connection_manager = connection_manager
        self._accounts = list(accounts or [])
        self._copy_group_followers: list[FollowerConfig] = []

        self._window = QMainWindow()
        self._window.setWindowTitle("TS-Local")
        self._window.resize(1180, 820)
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

        connection_box = QGroupBox("Tradovate Connection")
        connection_form = QFormLayout(connection_box)
        self.login_label = QLineEdit()
        self.login_label.setPlaceholderText("e.g. Main Tradovate")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.environment = QComboBox()
        self.environment.addItems(["demo", "live"])
        self.app_id = QLineEdit("TS-Local")
        self.cid = QLineEdit()
        self.api_secret = QLineEdit()
        self.api_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.connect_button = QPushButton("Save + Connect")
        self.connect_button.clicked.connect(self._save_and_connect)
        connection_form.addRow("Label", self.login_label)
        connection_form.addRow("Username", self.username)
        connection_form.addRow("Password", self.password)
        connection_form.addRow("Environment", self.environment)
        connection_form.addRow("App ID", self.app_id)
        connection_form.addRow("CID (optional)", self.cid)
        connection_form.addRow("API secret (optional)", self.api_secret)
        connection_form.addRow("", self.connect_button)
        layout.addWidget(connection_box)

        accounts_box = QGroupBox("Accounts")
        accounts_layout = QVBoxLayout(accounts_box)
        self.account_table = QTableWidget(0, 5)
        self.account_table.setHorizontalHeaderLabels(
            ["Login", "Account", "Tradovate ID", "Role", "Status"]
        )
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

        self._window.setCentralWidget(root)
        self._refresh_accounts()

    def _save_and_connect(self) -> None:
        if self._connection_manager is None:
            self._QMessageBox.warning(self._window, "Connections unavailable", "No connection manager is configured.")
            return

        self.connect_button.setEnabled(False)
        self._window.statusBar().showMessage("Connecting to Tradovate…")
        try:
            saved = self._connection_manager.save_login(
                label=self.login_label.text(),
                username=self.username.text(),
                password=self.password.text(),
                environment=self.environment.currentText(),
                app_id=self.app_id.text(),
                cid=self.cid.text() or None,
                secret=self.api_secret.text() or None,
            )
            login = asyncio.run(self._connection_manager.connect(saved))
        except Exception as exc:
            self._window.statusBar().showMessage("Tradovate connection failed")
            self._QMessageBox.critical(self._window, "Tradovate connection failed", str(exc))
            return
        finally:
            self.connect_button.setEnabled(True)
            self.password.clear()
            self.api_secret.clear()

        existing_ids = {account.id for account in self._accounts}
        for account in login.accounts:
            if account.id not in existing_ids:
                self._accounts.append(account)
        self._refresh_accounts()
        self._window.statusBar().showMessage(
            f"Connected: {login.label} — {len(login.accounts)} account(s) discovered | DRY RUN"
        )

    def _refresh_accounts(self) -> None:
        self.account_table.setRowCount(0)
        self.leader.clear()
        self.follower.clear()
        login_labels = {}
        if self._connection_manager is not None:
            login_labels = {saved.id: saved.label for saved in self._connection_manager.list_saved()}

        for account in self._accounts:
            row = self.account_table.rowCount()
            self.account_table.insertRow(row)
            self.account_table.setItem(
                row, 0, self._QTableWidgetItem(login_labels.get(account.login_id, str(account.login_id)))
            )
            self.account_table.setItem(row, 1, self._QTableWidgetItem(account.name))
            self.account_table.setItem(row, 2, self._QTableWidgetItem(account.account_id))
            self.account_table.setItem(row, 3, self._QTableWidgetItem("Available"))
            self.account_table.setItem(
                row, 4, self._QTableWidgetItem("Active" if account.active else "Inactive")
            )
            label = f"{account.name} ({login_labels.get(account.login_id, 'login')})"
            self.leader.addItem(label, account.id)
            self.follower.addItem(label, account.id)

    def _add_follower(self) -> None:
        account_id = self.follower.currentData()
        if account_id is None:
            return
        if account_id == self.leader.currentData():
            self._QMessageBox.warning(
                self._window,
                "Invalid follower",
                "The leader account cannot also be its own follower.",
            )
            return
        if any(item.account_id == account_id for item in self._copy_group_followers):
            self._QMessageBox.information(
                self._window,
                "Follower already added",
                "That account is already in the follower list.",
            )
            return

        multiplier = Decimal(self.multiplier.value()) / Decimal(100)
        try:
            follower = FollowerConfig(account_id=account_id, multiplier=multiplier)
        except (InvalidOperation, ValueError):
            return
        self._copy_group_followers.append(follower)
        row = self.followers_table.rowCount()
        self.followers_table.insertRow(row)
        self.followers_table.setItem(row, 0, self._QTableWidgetItem(self.follower.currentText()))
        self.followers_table.setItem(row, 1, self._QTableWidgetItem(f"{multiplier:g}x"))
        self.followers_table.setItem(row, 2, self._QTableWidgetItem("Enabled"))

    def show(self) -> None:
        self._window.show()

    def exec(self) -> int:
        from PySide6.QtWidgets import QApplication

        return QApplication.instance().exec()
