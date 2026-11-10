import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="st_tests_")
os.environ.update({
    "RUN_MODE": "lite", "DATABASE_URL": f"sqlite:///{_tmp}/test.db", "EXECUTION_DELAY_SECONDS": "0",
    "WEBHOOK_RETRY_SCHEDULE": "0,0,0", "WEBHOOK_RETRY_JITTER": "0", "SEED_DEMO": "false",
    "ENVIRONMENT": "development", "ALLOW_LOCALHOST_WEBHOOKS": "true",
    "ADMIN_API_KEY": "test_admin_key", "DEMO_API_KEY": "test_dev_key",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "receiver"))
os.environ["RECEIVER_DB_PATH"] = f"{_tmp}/receiver.db"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.broker import _memory  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed_demo  # noqa: E402
from app.models import Developer  # noqa: E402
from app.security.authentication import hash_api_key  # noqa: E402
from app.services import webhook_service  # noqa: E402
from app.workers.event_publisher import publish_pending  # noqa: E402
import receiver_service  # noqa: E402

DEV = {"X-API-Key": "test_dev_key"}
ADMIN = {"X-API-Key": "test_admin_key"}
RECEIVER_URL = "http://localhost:9000/receiver/webhooks/secure-tokens"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_demo()
    while not _memory._q.empty():
        _memory._q.get_nowait()
    yield


@pytest.fixture
def api():
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def receiver(tmp_path):
    return receiver_service.Receiver(db_path=str(tmp_path / "r.db"))


class Env:
    """Helpers that drive the workers synchronously and route webhooks to an in-process receiver."""

    def __init__(self, api, receiver):
        self.api, self.receiver = api, receiver
        self.available = True
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if not self.available:
            raise httpx.ConnectError("receiver down")
        status, body = self.receiver.handle(request.content, dict(request.headers))
        return httpx.Response(status, json=body)

    def pump(self, rounds: int = 3):
        """publisher -> broker -> delivery worker -> due retries."""
        for _ in range(rounds):
            publish_pending(_memory)
            while not _memory._q.empty():
                msg = _memory._q.get_nowait()
                s = SessionLocal()
                try:
                    webhook_service.process_event_message(s, msg, self.client)
                finally:
                    s.close()
            s = SessionLocal()
            try:
                webhook_service.run_due_retries(s, self.client)
            finally:
                s.close()

    def subscribe(self, event_types=("*",), url=RECEIVER_URL, name="sample"):
        r = self.api.post("/api/v1/webhooks/subscriptions", headers=DEV,
                          json={"subscriber_name": name, "endpoint_url": url, "event_types": list(event_types)})
        assert r.status_code == 201, r.text
        body = r.json()
        self.receiver.set_secret(body["id"], body["signing_secret"])
        return body

    def run_task(self, **options):
        t = self.api.post("/api/v1/tasks", headers=DEV, json={"description": "Add caching layer"}).json()
        ex = self.api.post(f"/api/v1/tasks/{t['id']}/execute", headers=DEV, json=options)
        assert ex.status_code == 202, ex.text
        return t["id"], ex.json()["id"]


@pytest.fixture
def env(api, receiver):
    return Env(api, receiver)
