import time
from uuid import uuid4

from ts_local.connections import SavedLogin
from ts_local.models import CopyGroup, TradovateAccount
from ts_local.session import DryRunLeaderSession


class FakeJournal:
    def record(self, event, results):
        pass


class FakeManager:
    def create_client(self, saved_login):
        return FakeClient()


class FakeClient:
    async def authenticate(self, force=False):
        raise RuntimeError("intentional auth failure")

    async def aclose(self):
        pass

    class environment:
        websocket_url = "wss://example.invalid"


def test_session_reports_reconnect_status_and_can_stop():
    login_id = uuid4()
    leader_id = uuid4()
    saved = SavedLogin(
        id=login_id,
        label="Demo",
        username="demo",
        environment="demo",
        app_id="TS-Local",
    )
    account = TradovateAccount(
        id=leader_id,
        login_id=login_id,
        account_id="123",
        name="SIM123",
    )
    group = CopyGroup(uuid4(), "test", leader_id, ())
    states = []

    session = DryRunLeaderSession(
        manager=FakeManager(),
        saved_login=saved,
        accounts=[account],
        group=group,
        journal=FakeJournal(),
        on_state=states.append,
    )
    session.start()

    deadline = time.time() + 1
    while time.time() < deadline:
        if any(state.status and "reconnecting" in state.status for state in states):
            break
        time.sleep(0.01)

    session.stop()
    deadline = time.time() + 1
    while session.running and time.time() < deadline:
        time.sleep(0.01)

    assert any(state.status and "reconnecting" in state.status for state in states)
    assert session.running is False
