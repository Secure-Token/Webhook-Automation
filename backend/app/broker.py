"""Message broker abstraction.

full mode: RabbitMQ (durable topic exchange, durable queue, persistent messages, publisher
           confirms, manual acks).
lite mode: in-process queue so the demo runs without Docker (not durable).
"""
import json
import logging
import queue
import threading
import time
from typing import Callable, Protocol

from app.config import get_settings

log = logging.getLogger(__name__)
EXCHANGE = "st.events"
QUEUE = "st.webhook.delivery"


class Broker(Protocol):
    def publish(self, routing_key: str, body: dict) -> None: ...
    def consume(self, handler: Callable[[dict], None], stop: threading.Event) -> None: ...


class MemoryBroker:
    _q: "queue.Queue[dict]" = queue.Queue()

    def publish(self, routing_key: str, body: dict) -> None:
        self._q.put(body)

    def consume(self, handler, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                msg = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                handler(msg)
            except Exception:  # noqa: BLE001
                log.exception("handler failed; requeueing")
                self._q.put(msg)
                time.sleep(1)


class RabbitBroker:
    def __init__(self, url: str | None = None):
        import pika  # imported lazily so lite mode does not need a broker
        self._pika = pika
        self._params = pika.URLParameters(url or get_settings().rabbitmq_url)
        self._conn = None
        self._ch = None
        self._lock = threading.Lock()

    def _connect(self):
        if self._conn and self._conn.is_open and self._ch and self._ch.is_open:
            return
        self._conn = self._pika.BlockingConnection(self._params)
        self._ch = self._conn.channel()
        self._ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
        self._ch.queue_declare(queue=QUEUE, durable=True)
        self._ch.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key="#")
        self._ch.confirm_delivery()

    def publish(self, routing_key: str, body: dict) -> None:
        with self._lock:
            try:
                self._connect()
                self._ch.basic_publish(
                    exchange=EXCHANGE, routing_key=routing_key, body=json.dumps(body).encode(),
                    properties=self._pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                    mandatory=True)
            except Exception:
                self._conn = self._ch = None
                raise

    def consume(self, handler, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                with self._lock:
                    self._connect()
                    method, _props, raw = self._ch.basic_get(queue=QUEUE, auto_ack=False)
                if method is None:
                    time.sleep(0.3)
                    continue
                try:
                    handler(json.loads(raw))
                    with self._lock:
                        self._ch.basic_ack(method.delivery_tag)
                except Exception:  # noqa: BLE001
                    log.exception("handler failed; nack+requeue")
                    with self._lock:
                        self._ch.basic_nack(method.delivery_tag, requeue=True)
                    time.sleep(1)
            except Exception as exc:  # broker unavailable: reconnect loop
                log.warning("broker unavailable: %s", exc)
                self._conn = self._ch = None
                time.sleep(2)


_memory = MemoryBroker()


def get_broker() -> Broker:
    return _memory if get_settings().run_mode == "lite" else RabbitBroker()
