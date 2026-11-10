"""Real-broker test. Skipped automatically unless RabbitMQ is reachable (docker compose up rabbitmq).

    RABBITMQ_URL=amqp://guest:guest@localhost:5672/ pytest tests/test_rabbitmq_integration.py
"""
import os
import threading
import time

import pytest

from app.broker import RabbitBroker

URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def _available() -> bool:
    try:
        RabbitBroker(URL)._connect()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="RabbitMQ not reachable")


def test_publish_consume_ack_roundtrip():
    broker = RabbitBroker(URL)
    got, stop = [], threading.Event()
    broker.publish("task.created", {"event_id": "evt_rt_1", "event_type": "task.created"})
    t = threading.Thread(target=broker.consume, args=(got.append, stop), daemon=True)
    t.start()
    end = time.time() + 5
    while not any(m["event_id"] == "evt_rt_1" for m in got) and time.time() < end:
        time.sleep(0.1)
    stop.set()
    assert any(m["event_id"] == "evt_rt_1" for m in got)
