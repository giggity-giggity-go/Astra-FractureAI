"""Bounded in-memory records that connect detection and explanation requests."""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import secrets
import threading
from typing import Any, Dict, Optional


@dataclass
class DetectionTask:
    image_base64: str
    mime: str
    yolo_result: Dict[str, Any]
    image_size: Dict[str, int]
    expires_at: datetime
    size_bytes: int
    consumed: bool = False


class DetectionTaskStore:
    def __init__(self, ttl_seconds: int, max_items: int, max_bytes: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._items: OrderedDict[str, DetectionTask] = OrderedDict()
        self._used_ids: OrderedDict[str, datetime] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def create(
        self,
        image_base64: str,
        mime: str,
        yolo_result: Dict[str, Any],
        image_size: Dict[str, int],
    ) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        size_bytes = len(image_base64.encode("ascii")) + len(
            json.dumps(
                {"mime": mime, "yolo_result": yolo_result, "image_size": image_size},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if size_bytes > self._max_bytes:
            raise ValueError("Detection task exceeds cache capacity")
        with self._lock:
            self._evict(now)
            while self._items and (
                len(self._items) >= self._max_items or self._bytes + size_bytes > self._max_bytes
            ):
                _, removed = self._items.popitem(last=False)
                self._bytes -= removed.size_bytes
            if len(self._items) >= self._max_items or self._bytes + size_bytes > self._max_bytes:
                raise ValueError("Detection task cache is full")
            task_id = secrets.token_urlsafe(32)
            expires_at = now + self._ttl
            self._items[task_id] = DetectionTask(
                image_base64=image_base64,
                mime=mime,
                yolo_result=yolo_result,
                image_size=image_size,
                expires_at=expires_at,
                size_bytes=size_bytes,
            )
            self._bytes += size_bytes
            return task_id, expires_at

    def consume(self, task_id: str) -> tuple[Optional[DetectionTask], str]:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._evict(now)
            task = self._items.pop(task_id, None)
            if task is None:
                return None, "TASK_ALREADY_USED" if task_id in self._used_ids else "TASK_NOT_FOUND"
            self._bytes -= task.size_bytes
            task.consumed = True
            self._used_ids[task_id] = task.expires_at
            return task, ""

    def _evict(self, now: datetime) -> None:
        expired = [task_id for task_id, task in self._items.items() if task.expires_at <= now]
        for task_id in expired:
            task = self._items.pop(task_id)
            self._bytes -= task.size_bytes
        expired_used = [task_id for task_id, expires_at in self._used_ids.items() if expires_at <= now]
        for task_id in expired_used:
            self._used_ids.pop(task_id)
