"""In-memory log buffer — последние 500 строк логов API."""
import logging
from collections import deque
from datetime import datetime, timezone

_buffer: deque = deque(maxlen=500)


class MemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += " | " + self.formatException(record.exc_info)
            _buffer.append({
                "t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "lvl": record.levelname,
                "name": record.name.split(".")[-1],
                "msg": msg,
            })
        except Exception:
            pass


def get_logs() -> list:
    return list(_buffer)


def install():
    """Вешает обработчик на корневой логгер. Вызвать один раз при старте."""
    handler = MemoryLogHandler()
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
