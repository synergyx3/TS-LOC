from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .connections import ConnectionManager
from .journal import ExecutionJournal
from .models import CopyGroup, FollowerConfig, TradovateAccount
from .session import DryRunLeaderSession


class TSLocalWindow:
    """Qt desktop shell kept behind a tiny adapter so the domain stays UI-independent."""

    def __init__(
        self,
        accounts: list[TradovateAccount] | None = None,
        connection_manager: ConnectionManager | None = None,
        journal: ExecutionJournal | None = None,
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
        self._journal = journal
        self._accounts = list(accounts or [])
        self._copy_group_followers: list[FollowerConfig] = []
        self._configured_group: CopyGroup | None = None
        self._session: DryRunLeaderSession | None = None

        self._window = QMainWindow()
        self._window.setWindowTitle("TS-Local")
        self._window.resize(1240, 900)
        self._window.setStatusBar(QStatusBar())
        self._window.statusBar().showMessage("DRY RUN — no live orders will be submitted")

        root = QWidget()
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("TS-Local")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        self.mode_label = QLabel("● DRY RUN")
        self.mode_label.setStyleSheet("font-weight: 700;")
        header.addWidget(self.mode_label)
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
        self.arm_button = QPushButton("Configure DRY RUN group")
        self.arm_button.clicked.connect(self._configure_group)
        self.start_button = QPushButton("Start DRY RUN listener")
        self.start_button.clicked.connect(self._start_session)
        self.stop_button = QPushButton("Stop listener")
        self.stop_button.clicked.connect(self._stop_session)
        self.stop_button.setEnabled(False)
        self.group_status = QLabel("Not configured")
        form.addRow("Leader", self.leader)
        form.addRow("Follower", self.follower)
        form.addRow("Multiplier", self.multiplier)
        form.addRow("", self.add_button)
        form.addRow("", self.arm_button)
        form.addRow("", self.start_button)
        form.addRow("", self.stop_button)
        form.addRow("Runtime", self.group_status)
        layout.addWidget(controls)

        self.followers_table = QTableWidget(0, 3)
        self.followers_table.setHorizontalHeaderLabels(["Follower", "Multiplier", "Enabled"])
        layout.addWidget(self.followers_table)

        activity_box = QGroupBox("Recent Copy Activity")
        activity_layout = QVBoxLayout(activity_box)
        self.activity_table = QTableWidget(0, 7)
        self.activity_table.setHorizontalHeaderLabels(
            ["Time", "Symbol", "Side", "Leader Qty", "Follower", "Follower Qty", "Result"]
        )
        self.activity_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.refresh_activity_button = QPushButton("Refresh activity")
        self.refresh_activity_button.clicked.connect(self._refresh_activity)
        activity_layout.addWidget(self.activity_table)
        activity_layout.addWidget(self.refresh_activity_button)
        layout.addWidget(activity_box)

        self._window.setCentralWidget(root)
        self._refresh_accounts()
        self._refresh_activity()

    @property
    def configured_group(self) -> CopyGroup | None:
        return self._configured_group

    def _save_and_connect(self) -> None:
        if self._connection_manager is None:
            self._QMessageBox.warning(
                self._window, "Connections unavailable", "No connection manager is configured."
            )
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

        existing_keys = {(account.login_id, account.account_id) for account in self._accounts}
        for account in login.accounts:
            key = (account.login_id, account.account_id)
            if key not in existing_keys:
                self._accounts.append(account)
                existing_keys.add(key)
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
        self._configured_group = None
        self.group_status.setText("Changed — configure again")

    def _configure_group(self) -> None:
        leader_id = self.leader.currentData()
        if leader_id is None:
            self._QMessageBox.warning(self._window, "No leader", "Connect and select a leader account first.")
            return
        if not self._copy_group_followers:
            self._QMessageBox.warning(self._window, "No followers", "Add at least one follower account first.")
            return

        self._configured_group = CopyGroup(
            id=uuid4(),
            name="Desktop Copy Group",
            leader_account_id=leader_id,
            followers=tuple(self._copy_group_followers),
            enabled=True,
        )
        self.group_status.setText(
            f"DRY RUN configured — {len(self._copy_group_followers)} follower(s)"
        )
        self._window.statusBar().showMessage(
            "Copy group configured in DRY RUN — live execution remains disabled"
        )

    def _start_session(self) -> None:
        if self._configured_group is None:
            self._configure_group()
        if self._configured_group is None:
            return
        if self._connection_manager is None or self._journal is None:
            self._QMessageBox.warning(self._window, "Runtime unavailable", "Connection manager or journal is unavailable.")
            return

        leader = next(
            (account for account in self._accounts if account.id == self._configured_group.leader_account_id),
            None,
        )
        if leader is None:
            self._QMessageBox.warning(self._window, "Leader unavailable", "The configured leader account is not connected.")
            return
        saved = next(
            (item for item in self._connection_manager.list_saved() if item.id == leader.login_id),
            None,
        )
        if saved is None:
            self._QMessageBox.warning(self._window, "Login unavailable", "The leader login is not saved.")
            return

        if self._session is not None and self._session.running:
            return
        self._session = DryRunLeaderSession(
            manager=self._connection_manager,
            saved_login=saved,
            accounts=self._accounts,
            group=self._configured_group,
            journal=self._journal,
        )
        self._session.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.group_status.setText("DRY RUN listener starting…")
        self._window.statusBar().showMessage(
            "DRY RUN listener starting — leader orders will be journaled, not sent"
        )

    def _stop_session(self) -> None:
        if self._session is not None:
            self._session.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.group_status.setText("DRY RUN stopped")
        self._window.statusBar().showMessage("DRY RUN listener stopped")
        self._refresh_activity()

    def _refresh_activity(self) -> None:
        self.activity_table.setRowCount(0)
        if self._journal is None:
            return
        for item in self._journal.recent(100):
            row = self.activity_table.rowCount()
            self.activity_table.insertRow(row)
            result = item.get("reason") or ("sent" if not item.get("skipped") else "skipped")
            values = [
                str(item.get("recorded_at", "")),
                str(item.get("symbol", "")),
                str(item.get("side", "")),
                str(item.get("leader_quantity", "")),
                str(item.get("follower_account_id", "")),
                str(item.get("follower_quantity", "")),
                str(result),
            ]
            for column, value in enumerate(values):
                self.activity_table.setItem(row, column, self._QTableWidgetItem(value))

    def show(self) -> None:
        self._window.show()

    def exec(self) -> int:
        from PySide6.QtWidgets import QApplication

        return QApplication.instance().exec()
