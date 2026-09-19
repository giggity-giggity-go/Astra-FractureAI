"""Ultralytics Cloud YOLO adapter and bounded parallel prediction orchestration."""

from concurrent.futures import ThreadPoolExecutor
import io
import json
import math
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_MAX_RESULTS = 100
_MAX_SEGMENT_POINTS = 128
_MAX_COORDINATE = 100_000.0
_DEFAULT_TIMEOUT = 12
_RETRY_TOTAL = 2
_RETRY_BACKOFF = 0.3
_TASK_STARTUP_STAGGER_SECONDS = 0.2


def _build_retry_adapter() -> HTTPAdapter:
    """HTTP-level retry that handles transient upstream 5xx without re-raising.

    Built per-call so it never mutates a shared Session across detections.
    It only retries POSTs with 502/503/504 responses; 4xx and connection
    failures are still surfaced to the explicit except branches in _call_model
    so the existing safe error mapping remains authoritative.
    """
    return HTTPAdapter(max_retries=Retry(
        total=_RETRY_TOTAL,
        backoff_factor=_RETRY_BACKOFF,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        raise_on_status=False,
    ))


class YOLOCloudService:
    """Run the three configured YOLO tasks without reflecting upstream details."""

    def __init__(
        self,
        api_key: str,
        urls: Dict[str, Optional[str]],
        timeout: Optional[int],
        logger: Any,
        *,
        max_concurrency: int = 3,
        max_response_bytes: int = 2 * 1024 * 1024,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.urls = urls
        self.timeout = timeout if isinstance(timeout, int) and timeout > 0 else _DEFAULT_TIMEOUT
        self.logger = logger
        self.max_response_bytes = max_response_bytes
        configured_hosts = {
            urlparse(url).hostname.lower()
            for url in urls.values() if isinstance(url, str) and urlparse(url).hostname
        }
        self.allowed_hosts = {host.lower() for host in allowed_hosts} | configured_hosts
        if not self.allowed_hosts or not all(isinstance(url, str) and self._configured_url_allowed(url) for url in urls.values()):
            raise RuntimeError("YOLO provider URLs must use allowed HTTPS hosts")
        self._admission = threading.BoundedSemaphore(max_concurrency)

    def _configured_url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.hostname.lower() in self.allowed_hosts

    def _valid_url(self, url: str) -> bool:
        if not self._configured_url_allowed(url):
            return False
        parsed = urlparse(url)
        try:
            # The hostname is already restricted to the explicitly configured
            # provider allowlist. Only require DNS resolution here: local
            # proxies and VPNs may intentionally map provider names to a
            # non-public egress address before the HTTPS request is sent.
            addresses = {
                entry[4][0]
                for entry in socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or 443,
                    type=socket.SOCK_STREAM,
                )
            }
            return bool(addresses)
        except (OSError, ValueError):
            return False

    def _stagger_start(self, model_type: str) -> None:
        order = {"position": 0, "range": 1, "kind": 2}
        delay = _TASK_STARTUP_STAGGER_SECONDS * order.get(model_type, 0)
        if delay > 0:
            time.sleep(delay)

    def _call_model(self, model_type: str, image_bytes: bytes, conf: float, iou: float, imgsz: int) -> Dict[str, Any]:
        url = self.urls.get(model_type)
        if not url or not self._valid_url(url):
            return {"success": False, "error": "Model service is unavailable", "code": "UPSTREAM_UNAVAILABLE", "processing_time": 0}
        start_time = time.monotonic()
        self._stagger_start(model_type)
        session = requests.Session()
        session.trust_env = False
        session.mount("https://", _build_retry_adapter())
        session.mount("http://", _build_retry_adapter())
        session.headers["Connection"] = "close"
        response = None
        try:
            response = session.post(
                url,
                headers=self.headers,
                data={"conf": conf, "iou": iou, "imgsz": imgsz},
                files={"file": ("image.jpg", io.BytesIO(image_bytes), "image/jpeg")},
                timeout=(self.timeout, self.timeout),
                allow_redirects=False,
                stream=True,
            )
            elapsed = time.monotonic() - start_time
            if response.status_code in (429, 503) and response.headers.get("Retry-After"):
                self.logger.info("YOLO %s upstream asked to retry after %s", model_type, response.headers["Retry-After"])
            if response.status_code != 200:
                self.logger.warning("YOLO %s transport-failure kind=upstream-status status=%d", model_type, response.status_code)
                return {"success": False, "error": "Model service is unavailable", "code": "UPSTREAM_ERROR", "processing_time": elapsed}
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(65536):
                received += len(chunk)
                if received > self.max_response_bytes:
                    self.logger.warning("YOLO %s transport-failure kind=oversized", model_type)
                    return {"success": False, "error": "Model response exceeded the allowed size", "code": "UPSTREAM_RESPONSE_TOO_LARGE", "processing_time": elapsed}
                chunks.append(chunk)
            try:
                result_json = json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.logger.warning("YOLO %s transport-failure kind=invalid-json", model_type)
                return {"success": False, "error": "Model returned an invalid response", "code": "UPSTREAM_INVALID_RESPONSE", "processing_time": elapsed}
            return self._parse_result(model_type, result_json, elapsed)
        except requests.exceptions.Timeout:
            self.logger.warning("YOLO %s transport-failure kind=timeout", model_type)
            return {"success": False, "error": "Model request timed out", "code": "UPSTREAM_TIMEOUT", "processing_time": time.monotonic() - start_time}
        except requests.exceptions.RequestException:
            self.logger.warning("YOLO %s transport-failure kind=request-exception", model_type)
            return {"success": False, "error": "Model service is unavailable", "code": "UPSTREAM_UNAVAILABLE", "processing_time": time.monotonic() - start_time}
        except Exception:
            self.logger.warning("YOLO %s transport-failure kind=adapter-exception", model_type)
            return {"success": False, "error": "Model service is unavailable", "code": "UPSTREAM_ERROR", "processing_time": time.monotonic() - start_time}
        finally:
            if response is not None:
                response.close()
            session.close()

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and abs(number) <= _MAX_COORDINATE else None

    @classmethod
    def _box(cls, raw_box: Any) -> Optional[List[float]]:
        if isinstance(raw_box, dict):
            if all(key in raw_box for key in ("x1", "y1", "x2", "y2")):
                values = [raw_box[key] for key in ("x1", "y1", "x2", "y2")]
            elif all(key in raw_box for key in ("x", "y", "width", "height")):
                x, y, width, height = (raw_box[key] for key in ("x", "y", "width", "height"))
                values = [x, y, (cls._number(x) or 0) + (cls._number(width) or 0), (cls._number(y) or 0) + (cls._number(height) or 0)]
            else:
                return None
        elif isinstance(raw_box, (list, tuple)) and len(raw_box) == 4:
            values = list(raw_box)
        else:
            return None
        normalized = [cls._number(value) for value in values]
        return normalized if all(value is not None for value in normalized) else None

    @classmethod
    def _segments(cls, raw_segments: Any) -> Optional[List[List[float]]]:
        if isinstance(raw_segments, dict):
            x_values, y_values = raw_segments.get("x"), raw_segments.get("y")
            if not isinstance(x_values, list) or not isinstance(y_values, list) or len(x_values) != len(y_values):
                return None
            pairs = zip(x_values[:_MAX_SEGMENT_POINTS], y_values[:_MAX_SEGMENT_POINTS])
        elif isinstance(raw_segments, list) and raw_segments and all(isinstance(pair, (list, tuple)) and len(pair) >= 2 for pair in raw_segments):
            pairs = (pair[:2] for pair in raw_segments[:_MAX_SEGMENT_POINTS])
        elif isinstance(raw_segments, list) and len(raw_segments) % 2 == 0:
            pairs = zip(raw_segments[::2][: _MAX_SEGMENT_POINTS], raw_segments[1::2][: _MAX_SEGMENT_POINTS])
        else:
            return None
        normalized = []
        for x_value, y_value in pairs:
            x, y = cls._number(x_value), cls._number(y_value)
            if x is not None and y is not None:
                normalized.append([x, y])
        return normalized if len(normalized) >= 3 else None

    @classmethod
    def _parse_result(cls, model_type: str, raw_result: Dict[str, Any], elapsed: float) -> Dict[str, Any]:
        try:
            if not isinstance(raw_result, dict):
                raise ValueError("response must be an object")
            images = raw_result.get("images", [])
            if not isinstance(images, list) or not images:
                return {"success": True, "data": [], "processing_time": elapsed}
            first_image = images[0] if isinstance(images[0], dict) else {}
            results = first_image.get("results", [])
            if not isinstance(results, list):
                raise ValueError("results must be a list")
            data: List[Dict[str, Any]] = []
            for raw_item in results[:_MAX_RESULTS]:
                if not isinstance(raw_item, dict):
                    continue
                confidence = cls._number(raw_item.get("confidence"))
                if confidence is None or not 0 <= confidence <= 1:
                    continue
                item: Dict[str, Any] = {
                    "name": str(raw_item.get("name", ""))[:120],
                    "class": int(raw_item["class"]) if isinstance(raw_item.get("class"), int) and not isinstance(raw_item.get("class"), bool) else None,
                    "confidence": confidence,
                }
                if model_type in ("position", "range"):
                    box = cls._box(raw_item.get("box"))
                    segments = cls._segments(raw_item.get("segments"))
                    if box is not None:
                        item["box"] = box
                    if segments is not None:
                        item["segments"] = segments
                data.append(item)
            return {"success": True, "data": data, "processing_time": elapsed}
        except Exception:
            return {"success": False, "error": "Model returned an invalid response", "code": "UPSTREAM_INVALID_RESPONSE", "processing_time": elapsed}

    def predict_all(self, image_bytes: bytes, conf: float = 0.25, iou: float = 0.7, imgsz: int = 640) -> Tuple[Dict[str, Any], int]:
        if not self._admission.acquire(blocking=False):
            return {"success": False, "error": "Detection capacity is temporarily unavailable", "code": "CAPACITY_EXCEEDED", "errors": [], "processing_time": 0}, 429
        start_total = time.monotonic()
        try:
            max_workers = min(3, max(1, self._admission._initial_value if hasattr(self._admission, "_initial_value") else 3))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {name: executor.submit(self._call_model, name, image_bytes, conf, iou, imgsz) for name in ("position", "range", "kind")}
                results = {name: future.result() for name, future in futures.items()}
        finally:
            self._admission.release()
        total_wall_time = (time.monotonic() - start_total) * 1000
        errors = [{"model": name, "message": result.get("error", "Model service is unavailable"), "code": result.get("code", "UPSTREAM_ERROR")} for name, result in results.items() if not result.get("success")]
        if len(errors) == 3:
            return {"success": False, "error": "All YOLO models failed", "errors": errors, "processing_time": round(total_wall_time, 2)}, 502
        return {
            "success": True,
            "positions": results["position"].get("data", []) if results["position"].get("success") else [],
            "range": results["range"].get("data", []) if results["range"].get("success") else [],
            "kind": results["kind"].get("data", []) if results["kind"].get("success") else [],
            "processing_time": round(total_wall_time, 2),
            "position_time": round(results["position"].get("processing_time", 0) * 1000, 2),
            "range_time": round(results["range"].get("processing_time", 0) * 1000, 2),
            "kind_time": round(results["kind"].get("processing_time", 0) * 1000, 2),
            "errors": errors,
        }, 200
