"""Worker entrypoint: python -m app.workers.run [publisher|worker|all]"""
import signal
import sys
import threading

from app.broker import get_broker
from app.logging_config import configure_logging
from app.workers import event_publisher, webhook_worker


def start_background(stop: threading.Event) -> list[threading.Thread]:
    """Used by lite mode to run both workers inside the API process."""
    broker = get_broker()
    threads = [
        threading.Thread(target=event_publisher.run, args=(broker, stop), daemon=True, name="publisher"),
        threading.Thread(target=webhook_worker.run, args=(broker, stop), daemon=True, name="webhook-worker"),
    ]
    for t in threads:
        t.start()
    return threads


def main() -> None:
    configure_logging()
    role = sys.argv[1] if len(sys.argv) > 1 else "all"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    broker = get_broker()
    if role == "publisher":
        event_publisher.run(broker, stop)
    elif role == "worker":
        webhook_worker.run(broker, stop)
    else:
        threads = start_background(stop)
        try:
            while not stop.is_set():
                stop.wait(1)
        except KeyboardInterrupt:
            stop.set()
        for t in threads:
            t.join(timeout=2)


if __name__ == "__main__":
    main()
