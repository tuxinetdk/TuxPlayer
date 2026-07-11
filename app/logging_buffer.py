from __future__ import annotations

import logging
import threading
from collections import deque
from typing import List


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self._records = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        entry = self.format(record)
        with self._lock:
            self._records.append(entry)

    def tail(self, limit: int = 100) -> List[str]:
        with self._lock:
            return list(self._records)[-limit:]
